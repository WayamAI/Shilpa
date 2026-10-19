"""Build a ``WeldmentSpec`` into one welded solid, a cut list and checks.

Algorithm, per member in rank order (shells first, then priority, then
declaration order):

1. Sweep the tube along its node line: a cylinder, a cone frustum for tapered
   round tube, or a box section, minus the matching bore. Tubes run exactly
   node to node. Joints are designed with the end node on the axis of the tube
   being joined, so a member's end disc already lies inside that tube's
   envelope (true whenever the joining tube's outer radius plus the node's
   offset from the joined axis is no more than the joined tube's outer radius;
   checked as ``end_inside_joined``).
2. Cope: subtract the *solid outer envelope* of every higher-ranked element.
   The member then ends on the joined tube's outer surface, and the joined
   tube's wall and bore stay intact, as in a real fish-mouthed joint. A member
   coped at both ends keeps a sealed internal cavity, which is a valid solid.
3. Fuse every coped member and shell. Coped pieces are disjoint by
   construction, so the per-member volumes add up to the weldment volume.

The cut list reports, per member, the node-to-node centreline length, the
long-point-to-long-point cut length measured on the coped solid in the
member's own frame, and per end the joined element and the cope angle (acute
angle between the two tube axes: the setting on a tube notcher, 90 = square T).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import build123d as bd

from ..catalog.materials import mass_g
from ..contracts.errors import ErrorCode, ShilpaError
from ..contracts.ports import BuiltPart, Port
from .spec import Member, PortSpec, RectTube, RoundTube, Shell, Vec3, WeldmentSpec

TOL = 1e-6
ENDS_TOL = 0.05  # mm: a node within this of a joined element's axis/extent still counts


# ---------------------------------------------------------------- vectors


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a: Vec3) -> float:
    return math.sqrt(_dot(a, a))


def _unit(a: Vec3) -> Vec3:
    n = _norm(a)
    if n < TOL:
        raise ShilpaError(ErrorCode.INVALID_PARAMETER, "zero-length direction")
    return (a[0] / n, a[1] / n, a[2] / n)


def _perp(z: Vec3, hint: Vec3 | None = None) -> Vec3:
    """A unit vector perpendicular to ``z``, as close to ``hint`` as possible."""
    if hint is not None:
        h = _sub(hint, tuple(_dot(hint, z) * c for c in z))
        if _norm(h) > 1e-6:
            return _unit(h)
    # Least-aligned world axis, Gram-Schmidt.
    axes = [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)]
    w = min(axes, key=lambda a: abs(_dot(a, z)))
    return _unit(_sub(w, tuple(_dot(w, z) * c for c in z)))


# ---------------------------------------------------------------- elements


@dataclass
class _Element:
    id: str
    kind: str  # "member" | "shell"
    p0: Vec3
    p1: Vec3
    axis: Vec3
    length: float
    plane: bd.Plane
    outer: bd.Solid  # solid envelope
    tube: bd.Solid  # hollow tube as swept
    r_outer: tuple[float, float]  # outer "radius" at start and end (half the smaller side for rect)
    material: str
    profile_label: str
    raw_volume: float  # analytic tube volume before coping
    spec: Member | Shell
    rect: tuple[float, float] | None = None  # (width, height) along plane x / y for box sections


def _round_tube(plane: bd.Plane, length: float, prof: RoundTube) -> tuple[bd.Solid, bd.Solid, float]:
    d0, d1 = prof.ods
    r0, r1, w = d0 / 2, d1 / 2, prof.wall
    if abs(r0 - r1) < TOL:
        outer = bd.Solid.make_cylinder(r0, length, plane)
        inner = bd.Solid.make_cylinder(r0 - w, length, plane)
        vol = math.pi * (r0**2 - (r0 - w) ** 2) * length
    else:
        # Tapered: wall measured radially, which is within cos(half-angle) of the normal wall.
        outer = bd.Solid.make_cone(r0, r1, length, plane)
        inner = bd.Solid.make_cone(r0 - w, r1 - w, length, plane)
        vol = _frustum(r0, r1, length) - _frustum(r0 - w, r1 - w, length)
    return outer, outer.cut(inner).solid(), vol


def _frustum(r0: float, r1: float, h: float) -> float:
    return math.pi * h * (r0 * r0 + r0 * r1 + r1 * r1) / 3


def _rect_tube(p0: Vec3, axis: Vec3, length: float, prof: RectTube) -> tuple[bd.Plane, bd.Solid, bd.Solid, float]:
    up = _perp(axis, prof.up)  # height direction
    x = _cross(up, axis)  # width direction, so plane y == up
    plane = bd.Plane(origin=p0, x_dir=x, z_dir=axis)
    w, h, t = prof.width, prof.height, prof.wall

    def box(a: float, b: float) -> bd.Solid:
        return bd.Solid.make_box(a, b, length, bd.Plane(origin=plane.from_local_coords((-a / 2, -b / 2, 0)), x_dir=x, z_dir=axis))

    outer = box(w, h)
    vol = (w * h - (w - 2 * t) * (h - 2 * t)) * length
    return plane, outer, outer.cut(box(w - 2 * t, h - 2 * t)).solid(), vol


def _element(spec: Member | Shell, nodes: dict[str, Vec3]) -> _Element:
    if isinstance(spec, Shell):
        if spec.node is not None:
            c, a = nodes[spec.node], _unit(spec.axis)
            p0 = tuple(c[i] - a[i] * spec.length / 2 for i in range(3))
            p1 = tuple(c[i] + a[i] * spec.length / 2 for i in range(3))
        else:
            p0, p1 = nodes[spec.start_node], nodes[spec.end_node]
        prof = RoundTube(od=spec.od, wall=(spec.od - spec.bore) / 2)
    else:
        p0, p1 = nodes[spec.start_node], nodes[spec.end_node]
        prof = spec.profile
    length = _norm(_sub(p1, p0))
    if length < TOL:
        raise ShilpaError(ErrorCode.INVALID_PARAMETER, f"{spec.id}: zero length", feature_id=spec.id)
    axis = _unit(_sub(p1, p0))
    if isinstance(prof, RectTube):
        plane, outer, tube, vol = _rect_tube(p0, axis, length, prof)
        r = (min(prof.width, prof.height) / 2,) * 2
    else:
        plane = bd.Plane(origin=p0, x_dir=_perp(axis), z_dir=axis)
        outer, tube, vol = _round_tube(plane, length, prof)
        r = (prof.ods[0] / 2, prof.ods[1] / 2)
    rect = (prof.width, prof.height) if isinstance(prof, RectTube) else None
    return _Element(spec.id, "shell" if isinstance(spec, Shell) else "member", p0, p1, axis, length,
                    plane, outer, tube, r, spec.material, prof.label(), vol, spec, rect)


def _radius_at(e: _Element, t: float) -> float:
    return e.r_outer[0] + (e.r_outer[1] - e.r_outer[0]) * min(max(t / e.length, 0.0), 1.0)


def _line_info(e: _Element, p: Vec3) -> tuple[float, float]:
    """(distance of ``p`` from e's axis, axial parameter of its projection)."""
    d = _sub(p, e.p0)
    t = _dot(d, e.axis)
    perp = _sub(d, tuple(t * c for c in e.axis))
    return _norm(perp), t


# ---------------------------------------------------------------- result


@dataclass
class WeldmentResult:
    part: BuiltPart | None
    nodes: dict[str, Vec3]
    cut_list: list[dict[str, Any]]
    checks: list[dict[str, Any]]
    pieces: dict[str, Any] = field(default_factory=dict)  # coped solid per member/shell id

    @property
    def ok(self) -> bool:
        return self.part is not None and all(c["passed"] for c in self.checks if c.get("severity", "error") == "error")

    def failed(self) -> list[dict[str, Any]]:
        return [c for c in self.checks if not c["passed"]]


def build_weldment(spec: WeldmentSpec, strict: bool = False) -> WeldmentResult:
    """Build, cope, fuse and check. With ``strict`` a failed error-level check raises."""
    nodes = spec.resolve_nodes()
    specs: list[Member | Shell] = list(spec.shells) + list(spec.members)
    # Rank: higher priority first; declaration order breaks ties (shells declared before members).
    order = sorted(range(len(specs)), key=lambda i: (-specs[i].priority, i))
    elems = [_element(specs[i], nodes) for i in order]

    checks: list[dict[str, Any]] = []
    pieces: dict[str, Any] = {}
    cut_list: list[dict[str, Any]] = []
    for rank, e in enumerate(elems):
        higher = elems[:rank]
        bb = e.outer.bounding_box()
        cutters = [h.outer for h in higher if _bbox_overlap(bb, h.outer.bounding_box())]
        try:
            coped = e.tube.cut(*cutters) if cutters else e.tube
        except Exception as exc:  # OCP boolean failures
            raise ShilpaError(ErrorCode.KERNEL_FAILURE, f"coping {e.id} failed: {exc}", feature_id=e.id) from exc
        solids = coped.solids() if coped is not None else []
        n = len(solids)
        checks.append({"name": f"member_intact:{e.id}", "passed": n == 1,
                       "detail": "consumed by coping" if n == 0 else (f"split into {n} pieces" if n > 1 else "ok")})
        if n == 0:
            cut_list.append(_cut_entry(e, None, higher, checks))
            continue
        piece = solids[0] if n == 1 else bd.Compound(solids)
        pieces[e.id] = piece
        cut_list.append(_cut_entry(e, piece, higher, checks))

    # Later cuts use a piece's outer envelope as a tool, and OCCT booleans may raise tolerances on shared
    # sub-shapes in place, so a piece valid when coped can be invalid now. Such defects make the frame fuse
    # come out inside-out (negative volume); ShapeFix heals them. Checked once, after all coping.
    for pid, piece in list(pieces.items()):
        if not piece.is_valid:
            fixed = piece.fix()
            checks.append({"name": f"piece_valid:{pid}", "passed": bool(fixed.is_valid), "severity": "warning",
                           "detail": "healed with ShapeFix" if fixed.is_valid else "invalid after coping; ShapeFix failed"})
            pieces[pid] = fixed

    part = None
    if pieces:
        shapes = list(pieces.values())
        try:
            fused = shapes[0].fuse(*shapes[1:]).clean() if len(shapes) > 1 else shapes[0]
        except Exception as exc:
            raise ShilpaError(ErrorCode.KERNEL_FAILURE, f"fusing weldment failed: {exc}") from exc
        fsolids = fused.solids()
        checks.append({"name": "single_solid", "passed": len(fsolids) == 1, "detail": f"{len(fsolids)} solids"})
        solid = fsolids[0] if len(fsolids) == 1 else fused
        ok = bool(solid.is_valid) and solid.volume > 0
        checks.append({"name": "valid_solid", "passed": ok,
                       "detail": "" if ok else f"valid={solid.is_valid}, volume {solid.volume:.1f} (inside-out when negative)"})
        vol_sum = sum(p.volume for p in shapes)
        checks.append({"name": "volume_additive", "passed": abs(solid.volume - vol_sum) <= 1e-4 * vol_sum + 1e-3,
                       "detail": f"fused {solid.volume:.3f} vs pieces {vol_sum:.3f}", "severity": "warning"})
        mass = sum(mass_g(pieces[c["id"]].volume, c["material"]) for c in cut_list if c["id"] in pieces)
        part = BuiltPart(
            name=spec.name,
            solid=solid,
            ports={p.name: _port(p, nodes) for p in spec.ports},
            source="weldment",
            meta={**spec.meta, "volume_mm3": round(solid.volume, 3), "mass_g": round(mass, 3),
                  "member_count": len(spec.members), "shell_count": len(spec.shells)},
        )
    result = WeldmentResult(part, nodes, cut_list, checks, pieces)
    if strict and not result.ok:
        raise ShilpaError(ErrorCode.VALIDATION_FAILED, f"weldment {spec.name} failed checks",
                          details={"failed": result.failed()})
    return result


def _bbox_overlap(a: bd.BoundBox, b: bd.BoundBox, pad: float = 0.01) -> bool:
    return (a.min.X <= b.max.X + pad and b.min.X <= a.max.X + pad and a.min.Y <= b.max.Y + pad
            and b.min.Y <= a.max.Y + pad and a.min.Z <= b.max.Z + pad and b.min.Z <= a.max.Z + pad)


def _cut_entry(e: _Element, piece, higher: list[_Element], checks: list[dict]) -> dict[str, Any]:
    if piece is not None:
        local = e.plane.to_local_coords(piece).bounding_box(optimal=True)
        cut_len, z0, z1 = local.max.Z - local.min.Z, local.min.Z, local.max.Z
    else:
        cut_len, z0, z1 = 0.0, 0.0, 0.0
    ends = []
    for which, node_pt, t_end in (("start", e.p0, 0.0), ("end", e.p1, e.length)):
        ends.append(_end_info(e, which, node_pt, t_end, higher, checks))
    entry = {
        "id": e.id,
        "kind": e.kind,
        "profile": e.profile_label,
        "material": e.material,
        "centreline_length": round(e.length, 3),
        "cut_length": round(cut_len, 3),  # long point to long point after coping
        "kept_from": round(z0, 3),  # axial extent kept, from the start node
        "kept_to": round(z1, 3),
        "raw_volume": round(e.raw_volume, 3),
        "volume": round(piece.volume, 3) if piece is not None else 0.0,
        "ends": ends,
    }
    checks.append({"name": f"positive_length:{e.id}", "passed": cut_len > 0.0, "detail": f"{cut_len:.3f} mm"})
    return entry


def _end_info(e: _Element, which: str, p: Vec3, t_end: float, higher: list[_Element], checks: list[dict]) -> dict:
    """Which higher-ranked element this end is coped against, and at what angle."""
    best = None
    for h in higher:
        dist, t = _line_info(h, p)
        if -ENDS_TOL <= t <= h.length + ENDS_TOL and dist <= _radius_at(h, t) + ENDS_TOL:
            if best is None or dist < best[1] - 1e-9:
                best = (h, dist, t)
    if best is None:
        return {"end": which, "type": "square", "against": None, "cope_angle_deg": None, "offset_mm": None}
    h, dist, t = best
    cosang = abs(_dot(e.axis, h.axis))
    angle = math.degrees(math.acos(min(1.0, cosang)))
    r_end = e.r_outer[0] if which == "start" else e.r_outer[1]
    inside, detail = _disc_inside(e.axis, p, r_end, h, dist, t)
    checks.append({"name": f"end_inside_joined:{e.id}.{which}", "passed": inside, "severity": "warning", "detail": detail})
    return {"end": which, "type": "cope", "against": h.id, "cope_angle_deg": round(angle, 3), "offset_mm": round(dist, 3)}


def _extent(r: float, normal: Vec3, v: Vec3) -> float:
    """Half-extent along unit ``v`` of a disc of radius ``r`` with unit ``normal``."""
    return r * math.sqrt(max(0.0, 1.0 - _dot(normal, v) ** 2))


def _disc_inside(a: Vec3, p: Vec3, r: float, h: _Element, dist: float, t: float) -> tuple[bool, str]:
    """Is the end disc (centre ``p``, radius ``r``, normal ``a``) inside h's envelope?

    If it is, the swept tube cannot poke out of the far side of the joined tube.
    """
    ext_axial = _extent(r, a, h.axis)
    axial = t - ext_axial >= -ENDS_TOL and t + ext_axial <= h.length + ENDS_TOL
    note = "ok" if axial else "overhangs"
    if h.rect is None:
        ok = r + dist <= _radius_at(h, t) + ENDS_TOL and axial
        return ok, f"end radius {r:.2f} + offset {dist:.2f} vs {h.id} radius {_radius_at(h, t):.2f}; axial {note}"
    local = h.plane.to_local_coords(bd.Vector(*p))
    xd, yd = tuple(h.plane.x_dir), tuple(h.plane.y_dir)
    ex, ey = abs(local.X) + _extent(r, a, xd), abs(local.Y) + _extent(r, a, yd)
    ok = ex <= h.rect[0] / 2 + ENDS_TOL and ey <= h.rect[1] / 2 + ENDS_TOL and axial
    return ok, f"end footprint {2 * ex:.2f} x {2 * ey:.2f} vs {h.id} section {h.rect[0]:g} x {h.rect[1]:g}; axial {note}"


def _port(p: PortSpec, nodes: dict[str, Vec3]) -> Port:
    z = _unit(p.z) if p.z is not None else _unit(_sub(nodes[p.z_nodes[1]], nodes[p.z_nodes[0]]))
    x = _perp(z, p.x)
    return Port(name=p.name, origin=nodes[p.node], z=z, x=x, label=p.label, contract=dict(p.contract))
