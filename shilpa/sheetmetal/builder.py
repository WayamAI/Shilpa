"""Native build123d sheet-metal builder: folded solid and flat pattern from one tree.

Every wall has a local frame (u, v in its flat plane, w through the thickness,
material at 0 <= w <= T) and two placements: ``to3d`` in the folded part and
``toflat`` in the flat pattern. A child wall's placements are its parent's
composed with one bend:

- folded: rotate the unbent child frame about the bend axis by the bend angle;
- flat:   translate the unbent child frame by the bend allowance.

Walls are extruded from the same 2D faces in both placements and bends are an
exact revolve (folded) or a strip of width ``BA = angle * (R + K * T)`` (flat), so
the unfold is correct by construction: nothing is ever unfolded numerically.

Frame math is plain 4x4 numpy so the placements stay exact and kernel-free;
``checks.refold`` re-derives the fold from flat-pattern data independently.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import build123d as bd
import numpy as np

from shilpa.contracts.errors import ErrorCode, ShilpaError
from shilpa.contracts.ports import BuiltPart, Port
from shilpa.sheetmetal.spec import (
    Cutout,
    EdgeFlange,
    Hem,
    RectOutline,
    SheetMetalSpec,
    bend_allowance,
)

Pt2 = tuple[float, float]
RECT_ALIASES = {"south": 0, "east": 1, "north": 2, "west": 3}
FLANGE_EDGES = {"near": 0, "side_a": 1, "far": 2, "side_b": 3}
EPS = 1e-9
TOOL_OVERHANG = 1.0  # cutting tools stick this far outside the wall to avoid coincident boundaries


# ---------------------------------------------------------------- frame math


def _tr(x: float, y: float, z: float = 0.0) -> np.ndarray:
    m = np.eye(4)
    m[:3, 3] = (x, y, z)
    return m


def _basis(origin, u, v, w) -> np.ndarray:
    m = np.eye(4)
    m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = u, v, w, origin
    return m


def _rot(point, axis, angle: float) -> np.ndarray:
    """Rigid rotation by ``angle`` (radians, right-hand rule) about the line point + t*axis."""
    k = np.asarray(axis, float) / np.linalg.norm(axis)
    kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    r = np.eye(3) + math.sin(angle) * kx + (1 - math.cos(angle)) * kx @ kx
    m = np.eye(4)
    m[:3, :3] = r
    p = np.asarray(point, float)
    m[:3, 3] = p - r @ p
    return m


def apply(m: np.ndarray, p) -> np.ndarray:
    q = np.asarray(p, float)
    if q.shape[0] == 2:
        q = np.array([q[0], q[1], 0.0])
    return m[:3, :3] @ q + m[:3, 3]


def to_location(m: np.ndarray) -> bd.Location:
    return bd.Location(bd.Plane(origin=tuple(m[:3, 3]), x_dir=tuple(m[:3, 0]), z_dir=tuple(m[:3, 2])))


# ---------------------------------------------------------------- 2D helpers


def _v(p) -> np.ndarray:
    return np.asarray(p, float)


def _edge_dir(a, b) -> tuple[np.ndarray, np.ndarray, float]:
    """Unit direction, outward normal (right of the direction for a CCW outline) and length."""
    d = _v(b) - _v(a)
    n = float(np.linalg.norm(d))
    d = d / n
    return d, np.array([d[1], -d[0]]), n


def poly_face(points) -> bd.Face:
    return bd.Face(bd.Wire.make_polygon([(float(x), float(y), 0.0) for x, y in points], close=True))


def circle_face(cx: float, cy: float, r: float) -> bd.Face:
    return bd.Face(bd.Wire([bd.Edge.make_circle(r)])).moved(bd.Location((cx, cy, 0)))


def _slot_face(cx, cy, length, width, angle_deg) -> bd.Face:
    r = width / 2
    a = math.radians(angle_deg)
    d = np.array([math.cos(a), math.sin(a)])
    n = np.array([-d[1], d[0]])
    c = np.array([cx, cy])
    p1, p2 = c - d * length / 2, c + d * length / 2

    def P(q):
        return bd.Vector(float(q[0]), float(q[1]), 0.0)

    edges = [
        bd.Edge.make_line(P(p1 - n * r), P(p2 - n * r)),
        bd.Edge.make_three_point_arc(P(p2 - n * r), P(p2 + d * r), P(p2 + n * r)),
        bd.Edge.make_line(P(p2 + n * r), P(p1 + n * r)),
        bd.Edge.make_three_point_arc(P(p1 + n * r), P(p1 - d * r), P(p1 - n * r)),
    ]
    return bd.Face(bd.Wire(edges))


def cutout_face(c: Cutout) -> bd.Face:
    cx, cy = c.center
    if c.shape == "circle":
        return circle_face(cx, cy, c.diameter / 2)
    if c.shape == "slot":
        return _slot_face(cx, cy, c.length, c.diameter, c.angle)
    a = math.radians(c.angle)
    ca, sa = math.cos(a), math.sin(a)
    if c.shape == "rect":
        pts = [(-c.width / 2, -c.height / 2), (c.width / 2, -c.height / 2), (c.width / 2, c.height / 2), (-c.width / 2, c.height / 2)]
    else:
        pts = list(c.points)
    return poly_face([(cx + x * ca - y * sa, cy + x * sa + y * ca) for x, y in pts])


def _faces(shape) -> list[bd.Face]:
    return list(shape.faces()) if shape is not None else []


def offset_polygon(points: list[Pt2], setbacks: list[float]) -> list[Pt2]:
    """Move each edge ``i`` inward by ``setbacks[i]``; vertices are the new line intersections."""
    n = len(points)
    lines = []
    for i in range(n):
        d, o, _ = _edge_dir(points[i], points[(i + 1) % n])
        lines.append((_v(points[i]) - o * setbacks[i], d))
    out = []
    for j in range(n):
        (p1, d1), (p2, d2) = lines[j - 1], lines[j]
        cross = d1[0] * d2[1] - d1[1] * d2[0]
        if abs(cross) < 1e-12:
            if abs(setbacks[j - 1] - setbacks[j]) > 1e-9:
                raise ShilpaError(ErrorCode.PRECONDITION_FAILED, "collinear edges with different flange setbacks")
            out.append(tuple(p2))
            continue
        t = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / cross
        out.append(tuple(p1 + d1 * t))
    for i in range(n):
        d0, _, _ = _edge_dir(points[i], points[(i + 1) % n])
        d1 = _v(out[(i + 1) % n]) - _v(out[i])
        if float(d0 @ d1) <= 1e-6:
            raise ShilpaError(
                ErrorCode.PRECONDITION_FAILED,
                f"flange setbacks consume edge {i} of the parent wall",
                details={"setbacks": setbacks},
            )
    return out


# ---------------------------------------------------------------- tree


@dataclass
class Wall:
    id: str
    outline: list[Pt2]  # nominal, CCW in local (u, v)
    edge_names: dict[str, int]
    to3d: np.ndarray
    toflat: np.ndarray
    parent_bend: str | None = None
    straight_length: float | None = None  # flanges and hems: nominal straight wall
    kind: str = "base"  # base | flange | hem
    final: list[Pt2] = field(default_factory=list)  # after full-width setbacks
    tools: list[bd.Face] = field(default_factory=list)  # notches, bend reliefs, corner reliefs
    cutouts: list[Cutout] = field(default_factory=list)
    bend_edges: list[tuple[Pt2, Pt2, float, str]] = field(default_factory=list)  # tangent lines: a, b, R, bend id
    face2d: bd.Face | Any = None  # local, all cuts applied
    solid: Any = None
    flat: Any = None


@dataclass
class Bend:
    id: str  # = child wall id
    parent: str
    child: str
    angle: float  # degrees
    direction: str
    radius: float
    k: float
    allowance: float
    width: float
    setback: float
    a: Pt2  # parent-local ends of the tangent line (a -> b runs along the parent edge)
    b: Pt2
    flat_start: tuple[Pt2, Pt2] = ((0, 0), (0, 0))  # tangent line on the parent side, flat coords
    flat_end: tuple[Pt2, Pt2] = ((0, 0), (0, 0))  # tangent line on the child side
    solid: Any = None
    flat: Any = None

    def row(self) -> dict:
        return {
            "id": self.id,
            "parent": self.parent,
            "angle": self.angle,
            "direction": self.direction,
            "radius": self.radius,
            "k": round(self.k, 6),
            "allowance": round(self.allowance, 6),
            "width": round(self.width, 6),
            "setback": round(self.setback, 6),
        }


@dataclass
class SheetMetalPart:
    spec: SheetMetalSpec
    walls: dict[str, Wall]
    bends: dict[str, Bend]
    solid: Any  # fused folded solid
    flat: Any  # fused flat pattern (planar face in XY)
    pieces: list[Any]  # unfused folded walls and bends
    flat_pieces: list[Any]

    @property
    def thickness(self) -> float:
        return self.spec.thickness

    def bend_lines(self) -> list[tuple[str, Pt2, Pt2]]:
        """Bend centre lines in the flat pattern (id, start, end)."""
        out = []
        for b in self.bends.values():
            (s0, s1), (e0, e1) = b.flat_start, b.flat_end
            out.append((b.id, tuple((_v(s0) + _v(e0)) / 2), tuple((_v(s1) + _v(e1)) / 2)))
        return out

    def flat_size(self) -> tuple[float, float]:
        bb = self.flat.bounding_box()
        return (float(bb.size.X), float(bb.size.Y))

    def meta(self) -> dict:
        bb = self.solid.bounding_box()
        fb = self.flat.bounding_box()
        rho = self.spec.density_kg_m3()
        vol = float(self.solid.volume)
        return {
            "material": self.spec.material,
            "thickness": self.spec.thickness,
            "flat_size": [round(fb.size.X, 6), round(fb.size.Y, 6)],
            "flat_bbox_min": [round(fb.min.X, 6), round(fb.min.Y, 6)],
            "flat_area": round(float(self.flat.area), 6),
            "outer_size": [round(bb.size.X, 6), round(bb.size.Y, 6), round(bb.size.Z, 6)],
            "volume": round(vol, 6),
            "density_kg_m3": rho,
            "mass_kg": round(vol * rho * 1e-9, 9) if rho else None,
            "bend_table": [b.row() for b in self.bends.values()],
            "bend_allowance_rule": "BA = angle_rad * (R + K * T)",
            "walls": sorted(self.walls),
        }

    # ------------------------------------------------------------ outputs

    def ports(self) -> dict[str, Port]:
        """Mounting holes and wall faces.

        ``hole_<cutout>``: centre of a circular cutout on the wall's w = 0 face,
        z out of that face. ``<wall>_bottom`` / ``<wall>_top``: the wall's flat
        centroid on its w = 0 / w = T face with z outward. For the base, bottom is
        -Z; a flange's bottom face is the one continuous with the base bottom.
        """
        T = self.thickness
        ports: dict[str, Port] = {}

        def unit(v):
            v = np.asarray(v, float)
            return tuple(float(c) for c in v / np.linalg.norm(v))

        for w in self.walls.values():
            m = w.to3d
            u, wn = m[:3, 0], m[:3, 2]
            face = w.face2d
            c = face.center() if face is not None else bd.Vector(0, 0, 0)
            for side, z, nrm in (("bottom", 0.0, -wn), ("top", T, wn)):
                ports[f"{w.id}_{side}"] = Port(
                    name=f"{w.id}_{side}",
                    origin=tuple(float(x) for x in apply(m, (c.X, c.Y, z))),
                    z=unit(nrm),
                    x=unit(u),
                    label=f"{w.kind} {w.id} {side} face",
                    contract={"kind": "face", "wall": w.id, "side": side, "thickness": T},
                )
            for cut in w.cutouts:
                if cut.shape != "circle" or not cut.mounting:
                    continue
                ports[f"hole_{cut.id}"] = Port(
                    name=f"hole_{cut.id}",
                    origin=tuple(float(x) for x in apply(m, (cut.center[0], cut.center[1], 0.0))),
                    z=unit(-wn),
                    x=unit(u),
                    label=f"mounting hole on {w.id}",
                    contract={"kind": "hole", "diameter": cut.diameter, "wall": w.id, "thickness": T},
                )
        return ports

    def built_part(self) -> BuiltPart:
        return BuiltPart(name=self.spec.name, solid=self.solid, ports=self.ports(), source="sheet_metal", meta=self.meta())

    def export_step(self, path: str | Path) -> Path:
        path = Path(path)
        if not bd.export_step(self.solid, str(path)):
            raise ShilpaError(ErrorCode.EXPORT_FAILED, f"STEP export failed: {path}")
        return path

    def export_dxf(self, path: str | Path) -> Path:
        """Flat pattern: outline and cutouts on OUTLINE, bend centre lines on BEND,
        bend-zone tangent lines on BEND_EXTENT."""
        path = Path(path)
        dxf = bd.ExportDXF(unit=bd.Unit.MM)
        dxf.add_layer("OUTLINE")
        dxf.add_layer("BEND", color=bd.ColorIndex.RED, line_type=bd.LineType.DASHED)
        dxf.add_layer("BEND_EXTENT", color=bd.ColorIndex.CYAN, line_type=bd.LineType.DOT)
        dxf.add_shape(self.flat, layer="OUTLINE")

        def line(p, q):
            return bd.Edge.make_line(bd.Vector(p[0], p[1], 0), bd.Vector(q[0], q[1], 0))

        dxf.add_shape([line(p, q) for _, p, q in self.bend_lines()], layer="BEND")
        extents = []
        for b in self.bends.values():
            extents += [line(*b.flat_start), line(*b.flat_end)]
        dxf.add_shape(extents, layer="BEND_EXTENT")
        dxf.write(str(path))
        return path


# ---------------------------------------------------------------- builder


def _wall_of(ref: str) -> tuple[str, str]:
    wall, edge = ref.split(".", 1)
    return wall, edge


@dataclass
class _Child:
    feat: EdgeFlange | Hem
    edge: int
    angle: float
    direction: str
    radius: float
    k: float
    allowance: float
    straight: float
    setback: float
    full: bool
    kind: str
    inset_start: float = 0.0
    inset_end: float = 0.0


def _resolve(spec: SheetMetalSpec, wall: Wall, feat: EdgeFlange | Hem) -> _Child:
    T = spec.thickness
    _, edge = _wall_of(feat.edge)
    if edge not in wall.edge_names or edge == "near":
        raise ShilpaError(
            ErrorCode.UNKNOWN_REFERENCE,
            f"{feat.edge}: wall {wall.id!r} has edges {sorted(k for k in wall.edge_names if k != 'near')}",
            feature_id=feat.id,
            field="edge",
        )
    full = feat.offset_start <= 0 and feat.offset_end <= 0
    if isinstance(feat, Hem):
        gap = feat.gap if feat.gap is not None else (T if feat.kind == "open" else 0.1 * T)
        r = gap / 2
        k = spec.k_for(r)
        return _Child(feat, wall.edge_names[edge], 180.0, feat.direction, r, k, bend_allowance(180.0, r, k, T), feat.length, 0.0, full, "hem")
    r = feat.bend_radius if feat.bend_radius is not None else spec.bend_radius
    k = spec.k_for(r)
    half = math.tan(math.radians(feat.angle) / 2)
    straight = feat.length - {"outer": (r + T) * half, "inner": r * half, "flat": 0.0}[feat.length_type]
    if straight <= 1e-6:
        raise ShilpaError(
            ErrorCode.INVALID_PARAMETER,
            f"flange {feat.id}: {feat.length_type} length {feat.length} leaves no straight wall at R={r}, angle={feat.angle}",
            feature_id=feat.id,
            field="length",
        )
    setback = (r + T) * half if feat.position == "flush" else 0.0
    return _Child(feat, wall.edge_names[edge], feat.angle, feat.direction, r, k, bend_allowance(feat.angle, r, k, T), straight, setback, full, "flange")


def _relief_tool(kind: str, pa, d, o, t_lo: float, t_hi: float, depth: float) -> bd.Face:
    """Cut between t_lo and t_hi along the edge, from outside the wall to ``depth`` inside it."""

    def P(t, q):
        p = pa + d * t + o * q
        return (float(p[0]), float(p[1]))

    if kind == "obround":
        r = (t_hi - t_lo) / 2
        rect = poly_face([P(t_lo, TOOL_OVERHANG), P(t_hi, TOOL_OVERHANG), P(t_hi, -depth + r), P(t_lo, -depth + r)])
        c = P((t_lo + t_hi) / 2, -depth + r)
        return rect.fuse(circle_face(c[0], c[1], r)).clean().faces()[0]
    return poly_face([P(t_lo, TOOL_OVERHANG), P(t_hi, TOOL_OVERHANG), P(t_hi, -depth), P(t_lo, -depth)])


def _merge_flat(pieces: list, thickness: float):
    """Union of the flat regions as one face (or a compound if disconnected).

    OCCT will not unify coplanar faces of a face compound, so the regions are
    extruded into a flat plate, fused and cleaned, and the z = 0 face read back.
    """
    plates = [bd.Solid.extrude(f, bd.Vector(0, 0, thickness)) for p in pieces for f in p.faces()]
    plate = plates[0].fuse(*plates[1:]).clean() if len(plates) > 1 else plates[0]
    bottom = [f for f in plate.faces() if abs(f.normal_at().Z + 1) < 1e-9 and abs(f.center().Z) < 1e-9]
    return bottom[0] if len(bottom) == 1 else bd.Compound(bottom)


def build(spec: SheetMetalSpec) -> SheetMetalPart:
    """Build the folded solid and flat pattern for ``spec``."""
    T = spec.thickness
    feats: list[EdgeFlange | Hem] = [*spec.flanges, *spec.hems]
    if isinstance(spec.base, RectOutline):
        w2, d2 = spec.base.width / 2, spec.base.depth / 2
        outline = [(-w2, -d2), (w2, -d2), (w2, d2), (-w2, d2)]
        names = {f"edge_{i}": i for i in range(4)} | RECT_ALIASES
    else:
        outline = [tuple(p) for p in spec.base.points]
        names = {f"edge_{i}": i for i in range(len(outline))}
    base = Wall("base", outline, names, np.eye(4), np.eye(4))
    walls: dict[str, Wall] = {"base": base}
    bends: dict[str, Bend] = {}

    def process(wall: Wall) -> None:
        kids = [_resolve(spec, wall, f) for f in feats if _wall_of(f.edge)[0] == wall.id]
        n = len(wall.outline)
        by_edge: dict[int, list[_Child]] = {}
        for c in kids:
            by_edge.setdefault(c.edge, []).append(c)
        for e, cs in by_edge.items():
            if len(cs) > 1 and any(c.full for c in cs):
                raise ShilpaError(
                    ErrorCode.PRECONDITION_FAILED,
                    f"wall {wall.id} edge {e}: a full-width flange cannot share its edge ({[c.feat.id for c in cs]})",
                    feature_id=cs[0].feat.id,
                )
        setbacks = [0.0] * n
        for c in kids:
            if c.full:
                setbacks[c.edge] = c.setback
        wall.final = offset_polygon(wall.outline, setbacks) if any(setbacks) else list(wall.outline)

        # Corner reliefs where two full-width flanges meet at a vertex of this wall.
        cr = spec.corner_relief
        if cr.kind != "none":
            size = cr.size if cr.size is not None else T
            full_on = {c.edge: c for c in kids if c.full}
            for j in range(n):
                prev, nxt = full_on.get((j - 1) % n), full_on.get(j)
                if prev is None or nxt is None:
                    continue
                prev.inset_end += size
                nxt.inset_start += size
                v = _v(wall.final[j])
                d_prev, _, _ = _edge_dir(wall.final[(j - 1) % n], wall.final[j])
                d_next, _, _ = _edge_dir(wall.final[j], wall.final[(j + 1) % n])
                if cr.kind == "circle":
                    wall.tools.append(circle_face(float(v[0]), float(v[1]), size))
                else:
                    wall.tools.append(poly_face([v, v + d_next * size, v + (d_next - d_prev) * size, v - d_prev * size]))

        rw = spec.relief.width if spec.relief.width is not None else T
        for c in kids:
            f = c.feat
            pa, pb = _v(wall.final[c.edge]), _v(wall.final[(c.edge + 1) % n])
            d, o, length = _edge_dir(pa, pb)
            t0 = f.offset_start + c.inset_start
            t1 = length - f.offset_end - c.inset_end
            if t1 - t0 <= 1e-6:
                raise ShilpaError(ErrorCode.INVALID_PARAMETER, f"{f.id}: offsets leave no flange width", feature_id=f.id)
            shift = 0.0 if c.full else c.setback
            if not c.full:
                rd = spec.relief.depth if spec.relief.depth is not None else c.radius + T
                lo, hi = max(t0, 0.0), min(t1, length)
                if c.setback > 0 and hi > lo:
                    wall.tools.append(_relief_tool("rect", pa, d, o, lo, hi, c.setback))  # room for the bend
                if t0 > 1e-9:
                    wall.tools.append(_relief_tool(spec.relief.kind, pa, d, o, t0 - rw, t0, shift + rd))
                if t1 < length - 1e-9:
                    wall.tools.append(_relief_tool(spec.relief.kind, pa, d, o, t1, t1 + rw, shift + rd))
            a = pa + d * t0 - o * shift
            b = pa + d * t1 - o * shift
            width = t1 - t0
            wall.bend_edges.append((tuple(a), tuple(b), c.radius, f.id))

            # Child frames: unbent frame at the tangent-line midpoint, u along -d so the
            # child outline stays CCW with w continuous across the bend.
            m = (a + b) / 2
            unbent = _basis((m[0], m[1], 0.0), (-d[0], -d[1], 0.0), (o[0], o[1], 0.0), (0.0, 0.0, 1.0))
            theta = math.radians(c.angle)
            if c.direction == "up":
                axis_pt, phi = (m[0], m[1], T + c.radius), -theta
            else:
                axis_pt, phi = (m[0], m[1], -c.radius), theta
            fold = _rot(axis_pt, (d[0], d[1], 0.0), phi)
            child = Wall(
                f.id,
                [(-width / 2, 0.0), (width / 2, 0.0), (width / 2, c.straight), (-width / 2, c.straight)],
                dict(FLANGE_EDGES),
                wall.to3d @ fold @ unbent,
                wall.toflat @ _tr(o[0] * c.allowance, o[1] * c.allowance) @ unbent,
                parent_bend=f.id,
                straight_length=c.straight,
                kind=c.kind,
            )
            child.bend_edges.append(((-width / 2, 0.0), (width / 2, 0.0), c.radius, f.id))

            bend = Bend(f.id, wall.id, f.id, c.angle, c.direction, c.radius, c.k, c.allowance, width, c.setback, tuple(a), tuple(b))
            # The parent's cross-section at the tangent line, swept about the bend axis.
            section = bd.Face(
                bd.Wire.make_polygon(
                    [(a[0], a[1], 0.0), (b[0], b[1], 0.0), (b[0], b[1], T), (a[0], a[1], T)], close=True
                )
            )
            axis_dir = (d[0], d[1], 0.0) if phi > 0 else (-d[0], -d[1], 0.0)
            bend.solid = bd.Solid.revolve(section, math.degrees(abs(phi)), bd.Axis(axis_pt, axis_dir)).moved(to_location(wall.to3d))
            ba = o * c.allowance
            bend.flat = poly_face([a, b, b + ba, a + ba]).moved(to_location(wall.toflat))
            flat2 = [tuple(float(x) for x in apply(wall.toflat, p)[:2]) for p in (a, b, a + ba, b + ba)]
            bend.flat_start, bend.flat_end = (flat2[0], flat2[1]), (flat2[2], flat2[3])
            bends[f.id] = bend
            walls[f.id] = child
            process(child)

        # The wall's own face: final outline minus notches, reliefs and user cutouts.
        wall.cutouts = [c for c in spec.cutouts if c.face == wall.id]
        face = poly_face(wall.final)
        tools = wall.tools + [cutout_face(c) for c in wall.cutouts]
        if tools:
            cut = face.cut(*tools)
            fs = _faces(cut)
            if not fs:
                raise ShilpaError(ErrorCode.KERNEL_FAILURE, f"wall {wall.id}: cutouts remove the whole wall", feature_id=wall.id)
            face = fs[0] if len(fs) == 1 else bd.Compound(fs)
        wall.face2d = face
        prisms = [bd.Solid.extrude(fc, bd.Vector(0, 0, T)) for fc in _faces(face)]
        wall.solid = (prisms[0] if len(prisms) == 1 else bd.Compound(prisms)).moved(to_location(wall.to3d))
        wall.flat = face.moved(to_location(wall.toflat))

    process(base)
    missing = [f.id for f in feats if f.id not in walls]
    if missing:
        raise ShilpaError(
            ErrorCode.UNKNOWN_REFERENCE,
            f"features attached to unknown or circular parents: {missing}",
            feature_id=missing[0],
            field="edge",
        )
    bad_faces = sorted({c.face for c in spec.cutouts} - set(walls))
    if bad_faces:
        raise ShilpaError(ErrorCode.UNKNOWN_REFERENCE, f"cutouts on unknown walls {bad_faces}", field="face")

    pieces = [w.solid for w in walls.values()] + [b.solid for b in bends.values()]
    flat_pieces = [w.flat for w in walls.values()] + [b.flat for b in bends.values()]
    try:
        solid = pieces[0].fuse(*pieces[1:]).clean() if len(pieces) > 1 else pieces[0]
        flat = _merge_flat(flat_pieces, spec.thickness)
    except Exception as exc:  # OCCT boolean failure
        raise ShilpaError(ErrorCode.KERNEL_FAILURE, f"sheet-metal fuse failed: {exc}") from exc
    if isinstance(solid, bd.Compound) and len(solid.solids()) == 1:
        solid = solid.solids()[0]
    return SheetMetalPart(spec, walls, bends, solid, flat, pieces, flat_pieces)


def build_part(spec: SheetMetalSpec) -> BuiltPart:
    return build(spec).built_part()
