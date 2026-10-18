"""Independent geometry measurement and validation (blueprint sections 8, 19).

Measurements are taken from the exported STEP file after reimport, not from the
in-memory shape the adapter produced, so a bug in the build path cannot hide
behind its own numbers. Tolerances are software comparison tolerances, not
manufacturing tolerances.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import build123d as bd
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Cylinder

DIM_TOL = 0.01  # mm
ROUNDTRIP_REL_VOL = 1e-5
ORACLE_REL_VOL = 1e-6


@dataclass
class Cylinder:
    diameter: float
    axis: tuple[float, float, float]
    center: tuple[float, float]  # axis location projected on the plane normal to the axis (XY for Z axes)
    kind: str  # "hole" / "boss" (full 360 degrees, concave / convex) | "fillet" / "round" (partial)


@dataclass
class Measurement:
    valid: bool
    solid_count: int
    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]
    bbox_size: tuple[float, float, float]
    volume: float
    area: float
    cylinders: list[Cylinder]


@dataclass
class Check:
    name: str
    passed: bool
    requested: object = None
    actual: object = None
    tolerance: object = None
    note: str | None = None


@dataclass
class ValidationReport:
    passed: bool
    measurement: Measurement | None
    checks: list[Check] = field(default_factory=list)

    def to_dict(self) -> dict:
        return json.loads(json.dumps(asdict(self), default=float))


def _r(v: float, nd: int = 6) -> float:
    return round(float(v), nd)


def cylinders(shape) -> list[Cylinder]:
    seen: dict[tuple, Cylinder] = {}
    sweep: dict[tuple, float] = {}
    for face in shape.faces():
        surf = BRepAdaptor_Surface(face.wrapped)
        if surf.GetType() != GeomAbs_Cylinder:
            continue
        cyl = surf.Cylinder()
        ax = cyl.Axis()
        d, loc = ax.Direction(), ax.Location()
        axis = (_r(d.X()), _r(d.Y()), _r(d.Z()))
        if axis[2] < 0 or (axis[2] == 0 and (axis[1] < 0 or (axis[1] == 0 and axis[0] < 0))):
            axis = (-axis[0], -axis[1], -axis[2])
        radius = cyl.Radius()
        # Concave (hole) when the outward face normal points toward the axis.
        u = (surf.FirstUParameter() + surf.LastUParameter()) / 2
        v = (surf.FirstVParameter() + surf.LastVParameter()) / 2
        p = surf.Value(u, v)
        pt = bd.Vector(p.X(), p.Y(), p.Z())
        n = face.normal_at(pt)
        a = bd.Vector(loc.X(), loc.Y(), loc.Z())
        dv = bd.Vector(*axis)
        radial = (pt - a) - dv * (pt - a).dot(dv)
        kind = "hole" if radial.dot(n) < 0 else "boss"
        # Project the axis location so two halves of one cylinder group together.
        a_proj = a - dv * a.dot(dv)
        if abs(axis[2]) > 0.999999:
            center = (_r(a_proj.X, 4), _r(a_proj.Y, 4))
        else:
            center = (_r(a_proj.X, 4), _r(a_proj.Y, 4))
        key = (round(radius, 4), axis, center, kind)
        seen.setdefault(key, Cylinder(_r(2 * radius), axis, center, kind))
        sweep[key] = sweep.get(key, 0.0) + abs(surf.LastUParameter() - surf.FirstUParameter())
    # A concave fillet is a partial cylinder; only a full 360 degree sweep is a hole or boss.
    out = []
    for key, cyl in seen.items():
        if sweep[key] >= 2 * math.pi - 1e-6:
            out.append(cyl)
        else:
            out.append(Cylinder(cyl.diameter, cyl.axis, cyl.center, "fillet" if cyl.kind == "hole" else "round"))
    return out


def measure(shape) -> Measurement:
    bb = shape.bounding_box()
    valid = bool(shape.is_valid)
    return Measurement(
        valid=valid,
        solid_count=len(shape.solids()),
        bbox_min=(_r(bb.min.X), _r(bb.min.Y), _r(bb.min.Z)),
        bbox_max=(_r(bb.max.X), _r(bb.max.Y), _r(bb.max.Z)),
        bbox_size=(_r(bb.size.X), _r(bb.size.Y), _r(bb.size.Z)),
        volume=_r(shape.volume, 6),
        area=_r(shape.area, 6),
        cylinders=cylinders(shape),
    )


def hole_groups(m: Measurement) -> dict[float, int]:
    """Count unique concave cylinder axes per diameter."""
    out: dict[float, set] = {}
    for c in m.cylinders:
        if c.kind == "hole":
            out.setdefault(round(c.diameter, 4), set()).add((c.axis, c.center))
    return {d: len(s) for d, s in out.items()}


def validate(step_path: Path, assertions: dict, built_volume: float | None = None, oracle: dict | None = None) -> ValidationReport:
    checks: list[Check] = []
    try:
        reimported = bd.import_step(str(step_path))
    except Exception as exc:
        return ValidationReport(False, None, [Check("step_reimport", False, note=str(exc))])
    m = measure(reimported)
    checks.append(Check("step_reimport", True))

    if assertions.get("valid_brep", True):
        checks.append(Check("valid_brep", m.valid, True, m.valid))
    checks.append(Check("solid_count", m.solid_count == assertions.get("solid_count", 1), assertions.get("solid_count", 1), m.solid_count))

    if built_volume is not None:
        rel = abs(m.volume - built_volume) / max(built_volume, 1e-12)
        checks.append(Check("step_roundtrip_volume", rel <= ROUNDTRIP_REL_VOL, _r(built_volume), m.volume, ROUNDTRIP_REL_VOL, f"relative difference {rel:.2e}"))

    if "bbox" in assertions:
        want = [float(x) for x in assertions["bbox"]]
        ok = all(abs(a - b) <= DIM_TOL for a, b in zip(want, m.bbox_size))
        checks.append(Check("bbox", ok, [_r(x) for x in want], list(m.bbox_size), DIM_TOL))

    if "volume" in assertions:
        want = float(assertions["volume"])
        rel = abs(m.volume - want) / max(want, 1e-12)
        checks.append(Check("volume", rel <= 1e-5, want, m.volume, 1e-5, f"relative difference {rel:.2e}"))

    groups = hole_groups(m)
    for h in assertions.get("holes", []):
        d = round(float(h["diameter"]), 4)
        got = sum(n for dia, n in groups.items() if abs(dia - d) <= DIM_TOL)
        checks.append(Check(f"holes_d{d:g}", got == h["count"], h["count"], got, DIM_TOL, "unique concave axes of this diameter"))

    if oracle:
        checks += oracle_checks(m, oracle)

    return ValidationReport(all(c.passed for c in checks), m, checks)


def oracle_checks(m: Measurement, oracle: dict) -> list[Check]:
    """Compare against analytic expectations computed outside the CAD path (evals corpus)."""
    out = []
    if "bbox" in oracle:
        ok = all(abs(a - b) <= DIM_TOL for a, b in zip(oracle["bbox"], m.bbox_size))
        out.append(Check("oracle_bbox", ok, oracle["bbox"], list(m.bbox_size), DIM_TOL))
    if "volume" in oracle:
        rel = abs(m.volume - oracle["volume"]) / oracle["volume"]
        out.append(Check("oracle_volume", rel <= ORACLE_REL_VOL, oracle["volume"], m.volume, ORACLE_REL_VOL, f"relative difference {rel:.2e}"))
    if "solid_count" in oracle:
        out.append(Check("oracle_solid_count", m.solid_count == oracle["solid_count"], oracle["solid_count"], m.solid_count))
    if "hole_centers" in oracle:
        d = oracle["hole_centers"]["diameter"]
        want = sorted((round(x, 3), round(y, 3)) for x, y in oracle["hole_centers"]["centers"])
        got = sorted(
            (round(c.center[0], 3), round(c.center[1], 3))
            for c in m.cylinders
            if c.kind == "hole" and abs(c.diameter - d) <= DIM_TOL and abs(c.axis[2]) > 0.999999
        )
        ok = len(want) == len(got) and all(math.dist(a, b) <= DIM_TOL for a, b in zip(want, got))
        out.append(Check("oracle_hole_centers", ok, want, got, DIM_TOL))
    if "holes" in oracle:
        groups = hole_groups(m)
        for d, n in oracle["holes"].items():
            got = sum(c for dia, c in groups.items() if abs(dia - float(d)) <= DIM_TOL)
            out.append(Check(f"oracle_holes_d{float(d):g}", got == n, n, got, DIM_TOL))
    return out


FLOAT32_SLACK = 1e-5  # relative: STL and glTF store float32 coordinates


def mesh_extent_tolerance(size_mm, linear: float, angular: float) -> float:
    """Largest shortfall of a tessellated extent: chord sagitta of the biggest arc plus linear deflection.

    A fixed tolerance only works for small parts; a 180 mm disc meshed at 0.1 rad is legitimately
    about 0.1 mm short across a diameter.
    """
    r = max(size_mm) / 2
    return round(max(0.05, r * (1 - math.cos(angular / 2)) + linear), 4)


def validate_stl(path: Path, expect_size_mm: tuple[float, float, float], linear: float = 0.01, angular: float = 0.1) -> list[Check]:
    import trimesh

    mesh = trimesh.load(str(path), force="mesh")
    size = tuple(float(x) for x in mesh.extents)
    tol = mesh_extent_tolerance(expect_size_mm, linear, angular)
    # A mesh may sit inside the exact extent by up to tol; outside only by float32 rounding.
    ok = all(-FLOAT32_SLACK * max(b, 1.0) <= b - a <= tol for a, b in zip(size, expect_size_mm))
    return [
        Check("stl_watertight", bool(mesh.is_watertight), True, bool(mesh.is_watertight)),
        Check("stl_extent_mm", ok, list(expect_size_mm), [_r(s, 4) for s in size], tol, "tolerance from tessellation settings"),
    ]


def validate_glb(path: Path, expect_size_mm: tuple[float, float, float], linear: float = 0.05, angular: float = 0.2) -> list[Check]:
    import trimesh

    scene = trimesh.load(str(path), force="scene")
    size = tuple(float(x) for x in scene.extents)  # glTF is in metres
    want = tuple(s / 1000 for s in expect_size_mm)
    tol = mesh_extent_tolerance(expect_size_mm, linear, angular) / 1000
    ok = all(-FLOAT32_SLACK * max(b, 1e-3) <= b - a <= tol for a, b in zip(sorted(size), sorted(want)))
    return [Check("glb_extent_m", ok, [_r(s, 6) for s in want], [_r(s, 6) for s in size], tol, "glTF uses metres, Y up")]
