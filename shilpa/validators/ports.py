"""Port-to-geometry validation for ``BuiltPart`` (roadmap layer 3).

A port is only useful if it sits on the feature it names: a mate that aligns
two face ports trusts that each origin lies on a real planar face, and a
coaxial mate trusts that each axis port runs down a real bore or boss. This
module measures the part's own solid and checks every declared port against
it, so a generator that misplaces a port (wrong offset, flipped normal, wrong
diameter) is caught before an assembly is built on it.

Port kinds and what each must satisfy:

* ``face``: ``z`` is the outward normal of a contact face. Some planar face of
  the solid has outward normal within ``ang_tol`` of ``z``, its plane passes
  within ``tol`` of the origin, and the origin lies within ``tol`` of the
  region bounded by the face's outer wire (so an annular seat whose origin is
  the bore centre still counts, but a face off to the side does not).
* ``axis``: ``z`` runs along a part axis. Some cylindrical face or circular
  edge (tube ends, chamfered bores) has its axis parallel to ``z`` (either
  sign) within ``ang_tol`` and passing within ``tol`` of the origin. When the
  contract names a diameter (first present of ``DIAMETER_KEYS``), a coaxial
  candidate of that diameter within ``tol`` must exist; the check reports
  every coaxial diameter found.
* ``point``: a reference location with no surface of its own (clamp centres,
  marks). The origin lies on or inside the solid within ``tol``. A centre
  that sits between two features by construction (a saddle's rail clamp
  centre midway between its rails) declares ``contract["straddle"] = s``
  (mm): instead of the origin, the points ``s`` either side of it along the
  port's y axis (``z`` cross ``x``) must each lie on or inside the solid.

Kind inference, first rule that fires wins:

1. An explicit ``kind`` attribute on the port (not part of the ``Port`` model
   today; read with ``getattr`` so a future field works) or ``contract["kind"]``.
2. A strong axis word (``AXIS_WORDS``: axis, axle, bore, spindle) in the name
   or label: ``spindle_axis``, ``rear_dropout`` ("rear axle centre"),
   ``stem_clamp`` ("bar axis to the left").
3. A face word (``FACE_WORDS``: face, seat, flange, top, end, plane, ...) in
   the name or label: ``drive_shell_seat``, ``dropout_left`` ("locknut face").
4. A diameter key (``DIAMETER_KEYS``) in the contract: ``min_insertion``
   ("minimum insertion mark", ``seatpost_d``) runs down the post axis.
5. A point word (``POINT_WORDS``: centre, mark, ...) in the label:
   ``saddle_clamp`` ("saddle rail clamp centre").
6. A weak axis word (``WEAK_AXIS_WORDS``: shell, tube, steerer, thread, clamp,
   pedal, ...) in the name or label: ``pedal_left`` ("left pedal thread").
7. Otherwise ``point``.

Words are matched on whole tokens of the snake_case name and the label, so
``outer`` does not match ``out``. Tolerances are software comparison
tolerances, not manufacturing tolerances.
"""

from __future__ import annotations

import math
import re
from typing import Literal

import build123d as bd
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Cylinder, GeomAbs_Plane

from ..contracts.ports import BuiltPart, Port
from .geometry import Check

PORT_TOL = 0.05  # mm: plane offset, axis offset, diameter, point distance
PORT_ANG_TOL = 0.5  # degrees: normal / axis direction

PortKind = Literal["face", "axis", "point"]

AXIS_WORDS = {"axis", "axle", "bore", "spindle"}
FACE_WORDS = {"face", "faces", "seat", "seats", "flange", "mount", "pad", "plate", "top", "end",
              "tip", "underside", "plane", "abutment", "locknut", "cover"}
POINT_WORDS = {"centre", "center", "mark", "point", "origin"}
WEAK_AXIS_WORDS = {"hub", "shell", "tube", "seatpost", "post", "steerer", "bb", "head", "outer",
                   "inner", "thread", "clamp", "race", "pedal", "shaft", "pin", "hole", "diameter"}

# Contract keys that name the diameter of the feature an axis port runs along,
# in priority order: the first one present is the one checked.
DIAMETER_KEYS = ("diameter", "bore_d", "od", "id", "inner_d", "outer_d", "axle_d", "spindle_d",
                 "seatpost_d", "steerer_d", "clamp_d", "grip_d", "cup_bore", "bore", "crown_race_d",
                 "nominal_d", "shaft_d", "pin_d", "hole_d", "bsd", "d", "D")


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _diameter_key(contract: dict) -> str | None:
    for k in DIAMETER_KEYS:
        v = contract.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            return k
    return None


def port_kind(port: Port) -> PortKind:
    """Classify a port as ``face``, ``axis`` or ``point`` (rules in the module docstring)."""
    explicit = getattr(port, "kind", None) or port.contract.get("kind")
    if explicit in ("face", "axis", "point"):
        return explicit
    name, label = _words(port.name.replace("_", " ")), _words(port.label)
    both = name | label
    if both & AXIS_WORDS:
        return "axis"
    if both & FACE_WORDS:
        return "face"
    if _diameter_key(port.contract):
        return "axis"
    if label & POINT_WORDS:
        return "point"
    if both & WEAK_AXIS_WORDS:
        return "axis"
    return "point"


# ---------------------------------------------------------------- vectors


def _vec(t) -> bd.Vector:
    return bd.Vector(*t)


def _angle_deg(a: bd.Vector, b: bd.Vector) -> float:
    c = max(-1.0, min(1.0, a.normalized().dot(b.normalized())))
    return math.degrees(math.acos(c))


def _line_offset(p: bd.Vector, loc: bd.Vector, d: bd.Vector) -> float:
    """Distance from ``p`` to the line through ``loc`` along unit ``d``."""
    v = p - loc
    return (v - d * v.dot(d)).length


def _r(v: float, nd: int = 4) -> float:
    return round(float(v), nd)


# ---------------------------------------------------------------- checks


def _outside(face, p: bd.Vector) -> float:
    """Distance from ``p`` to ``face`` with its outer wire filled, so an annular seat accepts its bore centre."""
    try:
        return bd.Face(face.outer_wire()).distance_to(p)
    except Exception:  # a wire OCC cannot fill: fall back to the face itself
        return face.distance_to(p)


def _face_check(solid, port: Port, tol: float, ang_tol: float) -> Check:
    o, z = _vec(port.origin), _vec(port.z)
    best = None  # (score, summary) over faces with normal ≈ z
    flipped = False  # a face would pass with -z: the classic sign error
    for face in solid.faces():
        surf = BRepAdaptor_Surface(face.wrapped)
        if surf.GetType() != GeomAbs_Plane:
            continue
        n = face.normal_at(face.center())  # build123d honours face orientation: outward
        p0 = face.center()
        offset = abs((o - p0).dot(n))
        ang = _angle_deg(n, z)
        if ang > 180 - ang_tol and offset <= tol and _outside(face, o) <= tol:
            flipped = True
        if ang > ang_tol:
            continue
        outside = _outside(face, o)
        score = max(offset, outside)
        if best is None or score < best[0]:
            best = (score, {"angle_deg": _r(ang, 3), "plane_offset": _r(offset), "outside_face_by": _r(outside),
                            "face_center": [_r(c, 3) for c in p0]})
    requested = {"normal": [_r(c, 4) for c in port.z], "origin": [_r(c, 3) for c in port.origin]}
    tolerance = {"mm": tol, "deg": ang_tol}
    name = f"port_{port.name}_face"
    if best is None:
        note = "no planar face with outward normal along z"
        if flipped:
            note += "; a face through the origin has normal -z (z flipped?)"
        return Check(name, False, requested, None, tolerance, note)
    ok = best[1]["plane_offset"] <= tol and best[1]["outside_face_by"] <= tol
    note = None
    if not ok:
        note = "closest planar face with outward normal along z misses the origin"
        if flipped:
            note += "; a face through the origin has normal -z (z flipped?)"
    return Check(name, ok, requested, best[1], tolerance, note)


def _axis_candidates(solid):
    """(kind, location, unit direction, diameter) for every cylindrical face and circular edge."""
    out = []
    for face in solid.faces():
        surf = BRepAdaptor_Surface(face.wrapped)
        if surf.GetType() != GeomAbs_Cylinder:
            continue
        ax = surf.Cylinder().Axis()
        loc, d = ax.Location(), ax.Direction()
        out.append(("cylinder", bd.Vector(loc.X(), loc.Y(), loc.Z()), bd.Vector(d.X(), d.Y(), d.Z()),
                    2 * surf.Cylinder().Radius()))
    for edge in solid.edges():
        curve = BRepAdaptor_Curve(edge.wrapped)
        if curve.GetType() != GeomAbs_Circle:
            continue
        circ = curve.Circle()
        ax = circ.Axis()
        loc, d = ax.Location(), ax.Direction()
        out.append(("circle", bd.Vector(loc.X(), loc.Y(), loc.Z()), bd.Vector(d.X(), d.Y(), d.Z()), 2 * circ.Radius()))
    return out


def _axis_check(solid, port: Port, tol: float, ang_tol: float) -> Check:
    o, z = _vec(port.origin), _vec(port.z).normalized()
    key = _diameter_key(port.contract)
    want = float(port.contract[key]) if key else None
    coaxial: list[tuple[str, float]] = []
    nearest_parallel = None  # smallest axis offset among parallel candidates, for the report
    for kind, loc, d, dia in _axis_candidates(solid):
        ang = _angle_deg(d, z)
        if min(ang, 180 - ang) > ang_tol:
            continue
        off = _line_offset(o, loc, d.normalized())
        if off > tol:
            if nearest_parallel is None or off < nearest_parallel:
                nearest_parallel = off
            continue
        coaxial.append((kind, dia))
    requested = {"axis": [_r(c, 4) for c in port.z], "origin": [_r(c, 3) for c in port.origin]}
    if key:
        requested[key] = want
    tolerance = {"mm": tol, "deg": ang_tol}
    name = f"port_{port.name}_axis"
    if not coaxial:
        note = "no cylindrical face or circular edge coaxial with the port axis"
        if nearest_parallel is not None:
            note += f"; nearest parallel axis is {nearest_parallel:.3f} mm away"
        return Check(name, False, requested, None, tolerance, note)
    diameters = sorted({_r(dia, 3) for _, dia in coaxial})
    actual = {"coaxial_diameters": diameters}
    if want is None:
        return Check(name, True, requested, actual, tolerance, "contract has no diameter; coaxiality only")
    closest = min(diameters, key=lambda dia: abs(dia - want))
    actual["closest_diameter"] = closest
    ok = abs(closest - want) <= tol
    note = None if ok else f"no coaxial feature of {key}={want:g}"
    return Check(name, ok, requested, actual, tolerance, note)


def _inside_or_distance(solid, p: bd.Vector, tol: float) -> float:
    solids = solid.solids() if hasattr(solid, "solids") else [solid]
    return 0.0 if any(s.is_inside(p, tol) for s in solids) else solid.distance_to(p)


def _point_check(solid, port: Port, tol: float) -> Check:
    o = _vec(port.origin)
    span = port.contract.get("straddle")
    if isinstance(span, (int, float)) and not isinstance(span, bool) and span > 0:
        # A centre between two features (rail clamp centre between the rails): the points ``span`` either
        # side of the origin along the port's y axis (z cross x) must each lie on or inside the solid.
        y = _vec(port.z).cross(_vec(port.x)).normalized()
        ends = [_inside_or_distance(solid, o + y * (s * span), tol) for s in (1, -1)]
        dist = max(ends)
        return Check(f"port_{port.name}_point", dist <= tol, [_r(c, 3) for c in port.origin],
                     {"straddle_distances": [_r(e) for e in ends]}, tol,
                     f"points {span:g} mm either side of the origin along y must lie on or inside the solid")
    dist = _inside_or_distance(solid, o, tol)
    return Check(f"port_{port.name}_point", dist <= tol, [_r(c, 3) for c in port.origin],
                 {"distance_to_solid": _r(dist)}, tol, "origin must lie on or inside the solid")


def check_port(part: BuiltPart, port: Port, tol: float = PORT_TOL, ang_tol: float = PORT_ANG_TOL,
               kind: PortKind | None = None) -> Check:
    """Check one port against ``part.solid``; ``kind`` overrides inference."""
    kind = kind or port_kind(port)
    if kind == "face":
        return _face_check(part.solid, port, tol, ang_tol)
    if kind == "axis":
        return _axis_check(part.solid, port, tol, ang_tol)
    return _point_check(part.solid, port, tol)


def check_ports(part: BuiltPart, tol: float = PORT_TOL, ang_tol: float = PORT_ANG_TOL) -> list[Check]:
    """One ``Check`` per port, in declaration order, named ``port_<name>_<kind>``."""
    if part.solid is None:
        return [Check("ports_solid", False, note=f"part {part.name!r} has no solid to check ports against")]
    return [check_port(part, p, tol, ang_tol) for p in part.ports.values()]
