"""Sheet-metal DFM and consistency checks.

Geometry checks measure the built shapes (folded solid, flat pattern, unfused
pieces) rather than trusting the spec. Rule checks use common shop guidance;
the numbers are deliberately conservative defaults, not a specific press brake:

- minimum flange length: outer flange length ``L_out = L_straight + R + T`` (the
  far edge measured from the outside of the bend) must be ``>= 2.5 T + R``, the
  shortest leg a V-die can hold; a hem's flat return must be ``>= 4 T``.
- hole-to-bend distance: every cutout must keep ``>= 2 T + R`` from each bend
  tangent line of its wall, or the hole distorts when the bend forms.

``refold`` re-folds the flat pattern from flat-pattern data alone (bend lines and
the bend table) and requires every refolded point to land on the folded solid,
so a flat length that disagrees with the 3D part cannot pass.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field

import build123d as bd
import numpy as np
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepClass import BRepClass_FaceClassifier
from OCP.BRepIntCurveSurface import BRepIntCurveSurface_Inter
from OCP.BRepTools import BRepTools
from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
from OCP.gp import gp_Dir, gp_Lin, gp_Pnt, gp_Pnt2d
from OCP.TopAbs import TopAbs_IN

from shilpa.sheetmetal.builder import (
    SheetMetalPart,
    _rot,
    _tr,
    apply,
    cutout_face,
    poly_face,
)
from shilpa.sheetmetal.spec import bend_allowance
from shilpa.validators.geometry import Check

LEN_TOL = 1e-6  # mm, analytic comparisons
GEOM_TOL = 1e-4  # mm, kernel measurements
REL_VOL_TOL = 1e-6
BBOX_TOL = 5e-3  # mm, refolded bend arcs are sampled
ARC_SAMPLES = 64


@dataclass
class SheetMetalReport:
    passed: bool
    checks: list[Check] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def failed(self) -> list[str]:
        return sorted({c.name for c in self.checks if not c.passed})

    def to_dict(self) -> dict:
        return json.loads(json.dumps(asdict(self), default=float))


def min_flange_length(t: float, r: float) -> float:
    """Minimum outer flange length (far edge to outside of bend)."""
    return 2.5 * t + r


def min_hole_to_bend(t: float, r: float) -> float:
    return 2 * t + r


# ---------------------------------------------------------------- geometry checks


def _solid_check(part: SheetMetalPart) -> Check:
    s = part.solid
    n = len(s.solids())
    return Check("single_valid_solid", bool(s.is_valid) and n == 1, requested=1, actual=n, note=None if s.is_valid else "invalid B-rep")


def _overlap_pairs(shapes: list, measure) -> list[tuple[int, int, float]]:
    out = []
    boxes = [s.bounding_box() for s in shapes]
    for i in range(len(shapes)):
        for j in range(i + 1, len(shapes)):
            a, b = boxes[i], boxes[j]
            if a.min.X > b.max.X or b.min.X > a.max.X or a.min.Y > b.max.Y or b.min.Y > a.max.Y or a.min.Z > b.max.Z or b.min.Z > a.max.Z:
                continue
            common = shapes[i].intersect(shapes[j])
            amount = measure(common) if common is not None else 0.0
            if amount > 1e-6:
                out.append((i, j, amount))
    return out


def _piece_names(part: SheetMetalPart) -> list[str]:
    return [f"wall:{w}" for w in part.walls] + [f"bend:{b}" for b in part.bends]


def _folded_overlap(part: SheetMetalPart) -> Check:
    total = sum(p.volume for p in part.pieces)
    lost = total - part.solid.volume
    ok = lost <= REL_VOL_TOL * total
    note = None
    if not ok:
        names = _piece_names(part)
        pairs = _overlap_pairs(part.pieces, lambda s: sum(x.volume for x in s.solids()))
        note = "overlapping: " + ", ".join(f"{names[i]}/{names[j]} ({v:.3g} mm3)" for i, j, v in pairs)
    return Check("no_folded_overlap", ok, requested=0.0, actual=round(lost, 6), tolerance=REL_VOL_TOL * total, note=note)


def _flat_overlap(part: SheetMetalPart) -> Check:
    total = sum(f.area for p in part.flat_pieces for f in p.faces())
    lost = total - part.flat.area
    n = len(part.flat.faces())
    ok = lost <= REL_VOL_TOL * total and n == 1
    note = None
    if not ok:
        names = _piece_names(part)
        pairs = _overlap_pairs(part.flat_pieces, lambda s: sum(f.area for f in s.faces()))
        note = f"{n} flat region(s); overlapping: " + ", ".join(f"{names[i]}/{names[j]} ({v:.3g} mm2)" for i, j, v in pairs)
    return Check("no_flat_overlap", ok, requested=0.0, actual=round(lost, 6), tolerance=REL_VOL_TOL * total, note=note)


def _inside_point(face: bd.Face):
    """A point strictly inside ``face`` (the parametric centre may sit in a hole)."""
    umin, umax, vmin, vmax = BRepTools.UVBounds_s(face.wrapped)
    surf = BRepAdaptor_Surface(face.wrapped)
    for fu in (0.5, 0.3, 0.7, 0.1, 0.9, 0.2, 0.8, 0.4, 0.6):
        for fv in (0.5, 0.3, 0.7, 0.1, 0.9, 0.2, 0.8, 0.4, 0.6):
            u, v = umin + fu * (umax - umin), vmin + fv * (vmax - vmin)
            if BRepClass_FaceClassifier(face.wrapped, gp_Pnt2d(u, v), 1e-7).State() == TopAbs_IN:
                p = surf.Value(u, v)
                return bd.Vector(p.X(), p.Y(), p.Z())
    # Thin bands (rim faces) can dodge the grid: use the biggest mesh triangle instead.
    verts, tris = face.tessellate(1e-3)
    if not tris:
        return None
    best = max(tris, key=lambda t: (verts[t[1]] - verts[t[0]]).cross(verts[t[2]] - verts[t[0]]).length)
    centroid = (verts[best[0]] + verts[best[1]] + verts[best[2]]) / 3
    _, _, on_face = bd.Vertex(centroid).distance_to_with_closest_points(face)
    return on_face


def _chord(solid, p: bd.Vector, inward: bd.Vector) -> float | None:
    """Distance from ``p`` along ``inward`` to where the ray leaves the solid."""
    inter = BRepIntCurveSurface_Inter()
    inter.Init(solid.wrapped, gp_Lin(gp_Pnt(p.X, p.Y, p.Z), gp_Dir(inward.X, inward.Y, inward.Z)), 1e-7)
    ws = []
    while inter.More():
        if inter.W() > 1e-6:
            ws.append(inter.W())
        inter.Next()
    return min(ws) if ws else None


def _thickness(part: SheetMetalPart) -> Check:
    """Every face is either a major face (the ray through the material is exactly T
    long) or a rim of constant width T. Planar rims must satisfy the band identity
    ``area = T * (perimeter / 2 - T)``; cylindrical rims (hole walls) must be T tall."""
    T = part.thickness
    bad: list[str] = []
    major = rim = 0
    for i, f in enumerate(part.solid.faces()):
        gtype = BRepAdaptor_Surface(f.wrapped).GetType()
        if gtype not in (GeomAbs_Plane, GeomAbs_Cylinder):
            bad.append(f"face {i}: not planar or cylindrical")
            continue
        p = _inside_point(f)
        if p is None:
            bad.append(f"face {i}: no interior sample")
            continue
        chord = _chord(part.solid, p, -f.normal_at(p))
        if chord is not None and abs(chord - T) < GEOM_TOL:
            major += 1
            continue
        if gtype == GeomAbs_Cylinder:
            _, _, vmin, vmax = BRepTools.UVBounds_s(f.wrapped)
            if abs((vmax - vmin) - T) < GEOM_TOL:
                rim += 1
                continue
            bad.append(f"face {i}: cylinder with wall {chord} != T and height {vmax - vmin:.4g}")
            continue
        perimeter = sum(e.length for e in f.edges())
        band = T * (perimeter / 2 - T)
        if len(f.inner_wires()) == 0 and abs(f.area - band) <= 1e-4 * max(f.area, 1.0):
            rim += 1
            continue
        bad.append(f"face {i}: local thickness {chord if chord is None else round(chord, 4)} != {T}")
    return Check(
        "constant_thickness",
        not bad,
        requested=T,
        actual={"major_faces": major, "rim_faces": rim, "bad": len(bad)},
        tolerance=GEOM_TOL,
        note="; ".join(bad[:6]) or None,
    )


# ---------------------------------------------------------------- rule checks


def _flange_lengths(part: SheetMetalPart) -> list[Check]:
    T = part.thickness
    out = []
    for w in part.walls.values():
        if w.kind == "base":
            continue
        bend = part.bends[w.parent_bend]
        straight = min(w.final[2][1], w.final[3][1])  # a flush child on the far edge trims it
        if w.kind == "hem":
            need, actual = 4 * T, straight
            rule = "hem return >= 4T"
        else:
            need, actual = min_flange_length(T, bend.radius), straight + bend.radius + T
            rule = "L_out = L_straight + R + T >= 2.5T + R"
        out.append(Check(f"min_flange_length:{w.id}", actual >= need - LEN_TOL, requested=round(need, 6), actual=round(actual, 6), note=rule))
    return out


def _hole_rules(part: SheetMetalPart) -> list[Check]:
    T = part.thickness
    out = []
    for w in part.walls.values():
        outline = poly_face(w.final)
        for c in w.cutouts:
            face = cutout_face(c)
            common = face.intersect(outline)
            outside = face.area - (sum(x.area for x in common.faces()) if common is not None else 0.0)
            out.append(
                Check(f"cutout_inside_wall:{c.id}", outside <= 1e-6 * face.area, requested=0.0, actual=round(outside, 6), note=f"on {w.id}")
            )
            for a, b, r, bend_id in w.bend_edges:
                line = bd.Edge.make_line(bd.Vector(a[0], a[1], 0), bd.Vector(b[0], b[1], 0))
                dist = face.distance_to(line)
                need = min_hole_to_bend(T, r)
                out.append(
                    Check(
                        f"hole_to_bend:{c.id}:{bend_id}",
                        dist >= need - LEN_TOL,
                        requested=round(need, 6),
                        actual=round(dist, 6),
                        note="distance from cutout to bend tangent line >= 2T + R",
                    )
                )
    return out


# ---------------------------------------------------------------- refold


def _bend_frames(part: SheetMetalPart) -> tuple[dict, dict, list[Check]]:
    """Fold maps (flat XY -> part coords) per wall, from bend lines and the bend table only."""
    T = part.thickness
    z = np.array([0.0, 0.0, 1.0])
    maps = {"base": np.eye(4)}
    zones = {}
    checks = []
    for b in part.bends.values():  # parents precede children
        (s0, s1), (e0, e1) = (np.array(p, float) for p in b.flat_start), (np.array(p, float) for p in b.flat_end)
        d = (s1 - s0) / np.linalg.norm(s1 - s0)
        mid_e = (e0 + e1) / 2
        rel = mid_e - s0
        o = rel - d * (rel @ d)
        w_flat = float(np.linalg.norm(o))
        o = o / w_flat
        ba = bend_allowance(b.angle, b.radius, part.spec.k_for(b.radius), T)
        parallel = abs(((e1 - e0) / np.linalg.norm(e1 - e0)) @ d) > 1 - 1e-12
        checks.append(
            Check(
                f"bend_allowance:{b.id}",
                abs(w_flat - ba) < LEN_TOL and parallel,
                requested=round(ba, 9),
                actual=round(w_flat, 9),
                tolerance=LEN_TOL,
                note="flat bend-zone width = angle * (R + K*T)",
            )
        )
        o3 = np.array([o[0], o[1], 0.0])
        if b.direction == "up":
            k, c = np.cross(o3, z), T + b.radius
        else:
            k, c = np.cross(z, o3), -b.radius
        axis_pt = np.array([s0[0], s0[1], 0.0]) + c * z
        theta = math.radians(b.angle)
        parent = maps[b.parent]
        maps[b.child] = parent @ _rot(axis_pt, k, theta) @ _tr(-o3[0] * w_flat, -o3[1] * w_flat)
        zones[b.id] = (parent, s0, d, o, w_flat, axis_pt, k, theta)
    return maps, zones, checks


def _in_poly(p, poly, tol=1e-6) -> bool:
    """Point in (or on the boundary of) a simple polygon."""
    n = len(poly)
    inside = False
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        ab = b - a
        t = np.clip((p - a) @ ab / (ab @ ab), 0, 1)
        if np.linalg.norm(a + t * ab - p) < tol:
            return True
        if (a[1] > p[1]) != (b[1] > p[1]):
            x = a[0] + (p[1] - a[1]) * ab[0] / ab[1]
            if x > p[0]:
                inside = not inside
    return inside


def refold(part: SheetMetalPart) -> list[Check]:
    T = part.thickness
    maps, zones, checks = _bend_frames(part)
    walls_flat = {w.id: np.array([apply(w.toflat, p)[:2] for p in w.final]) for w in part.walls.values()}

    def fold_zone(zone, p2, w, t):
        parent, _, _, o, w_flat, axis_pt, k, theta = zone
        foot = p2 - o * t
        a = theta * min(max(t / w_flat, 0.0), 1.0)
        return (parent @ _rot(axis_pt, k, a))[:3] @ np.array([foot[0], foot[1], w, 1.0])

    pts = []
    unassigned = 0
    for v in part.flat.vertices():
        p2 = np.array([v.X, v.Y])
        hit = next((wid for wid, poly in walls_flat.items() if _in_poly(p2, poly)), None)
        if hit is not None:
            pts += [maps[hit][:3] @ np.array([p2[0], p2[1], w, 1.0]) for w in (0.0, T)]
            continue
        for b in part.bends.values():
            zone = zones[b.id]
            _, s0, d, o, w_flat, *_ = zone
            t = float((p2 - s0) @ o)
            along = float((p2 - s0) @ d)
            if -1e-6 <= t <= w_flat + 1e-6 and -1e-6 <= along <= b.width + 1e-6:
                pts += [fold_zone(zone, p2, w, t) for w in (0.0, T)]
                break
        else:
            unassigned += 1
    on_solid = [part.solid.distance_to(bd.Vector(*p)) for p in pts]
    worst = max(on_solid, default=0.0)
    checks.append(
        Check(
            "refold_points_on_solid",
            worst < GEOM_TOL and unassigned == 0,
            requested=0.0,
            actual=round(worst, 9),
            tolerance=GEOM_TOL,
            note=f"{len(pts)} refolded flat vertices; {unassigned} outside every wall and bend zone",
        )
    )
    # Bend arcs bulge past the walls (hems, outside corners): sample both ends of each zone.
    for b in part.bends.values():
        zone = zones[b.id]
        _, s0, d, o, w_flat, *_ = zone
        s1 = np.array(b.flat_start[1], float)
        for end in (s0, s1):
            for i in range(ARC_SAMPLES + 1):
                t = w_flat * i / ARC_SAMPLES
                pts += [fold_zone(zone, end + o * t, w, t) for w in (0.0, T)]
    arr = np.array(pts)
    lo, hi = arr.min(axis=0), arr.max(axis=0)
    bb = part.solid.bounding_box()
    blo, bhi = np.array([bb.min.X, bb.min.Y, bb.min.Z]), np.array([bb.max.X, bb.max.Y, bb.max.Z])
    err = float(max(np.abs(lo - blo).max(), np.abs(hi - bhi).max()))
    checks.append(
        Check(
            "refold_outer_dims",
            err < BBOX_TOL,
            requested=[round(x, 6) for x in (hi - lo)],
            actual=[round(x, 6) for x in (bhi - blo)],
            tolerance=BBOX_TOL,
            note="outer size of the flat pattern refolded through the bend table vs the folded solid",
        )
    )
    return checks


def _volume(part: SheetMetalPart) -> Check:
    """Folded volume from flat-pattern measurements: walls keep their area, each bend
    zone of width BA becomes an annular sector of mean radius R + T/2."""
    T = part.thickness
    strips = sum(b.allowance * b.width for b in part.bends.values())
    sectors = sum(math.radians(b.angle) * (b.radius + T / 2) * T * b.width for b in part.bends.values())
    expected = (part.flat.area - strips) * T + sectors
    actual = part.solid.volume
    return Check(
        "volume_from_flat",
        abs(actual - expected) <= REL_VOL_TOL * expected + 1e-6,
        requested=round(expected, 6),
        actual=round(actual, 6),
        tolerance=REL_VOL_TOL,
    )


# ---------------------------------------------------------------- entry point


def check(part: SheetMetalPart) -> SheetMetalReport:
    checks = [_solid_check(part), _folded_overlap(part), _flat_overlap(part)]
    geometry_ok = all(c.passed for c in checks)
    checks.append(_thickness(part))
    checks += _flange_lengths(part)
    checks += _hole_rules(part)
    try:
        checks += refold(part)
    except Exception as exc:  # a broken flat pattern must fail the check, not the caller
        checks.append(Check("refold_points_on_solid", False, note=f"refold failed: {exc}"))
    if geometry_ok:
        checks.append(_volume(part))
    stats = {
        "flat_size": part.flat_size(),
        "bends": len(part.bends),
        "walls": len(part.walls),
        "rule_violations": sorted({c.name.split(":")[0] for c in checks if not c.passed and c.name.split(":")[0] in ("min_flange_length", "hole_to_bend")}),
    }
    return SheetMetalReport(all(c.passed for c in checks), checks, stats)
