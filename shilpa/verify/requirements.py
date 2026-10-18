"""Per-requirement executable tests (roadmap: "Verification becomes test-driven").

A requirement such as "four 6 mm through holes, 10 mm from each edge" becomes a few
small tests that are *data*: a ``RequirementTest`` names a test kind, its arguments, a
tolerance and the requirement text it covers. Tests run against an exported STEP
file (reimported, like the validators) or an in-memory build123d shape, never against
the recipe, so a suite written from the request alone can judge any geometry.

Categories follow CADTestBench: validity, topology, geometric types, dimensions and
ratios, volume/mass and spatial arrangement.

Frame. Shilpa models are Z up and sit on the XY plane. Before measuring, the shape is
put in a canonical pose so tests do not depend on arbitrary planner choices: rotated
90 degrees about Z when its Y extent exceeds its X extent (X is the longer horizontal
side), translated so the bounding box is centred on X=Y=0 with its bottom at Z=0.
Positions that remain ambiguous (sign of X/Y, the quarter turn of a square part) are
compared up to that symmetry.

Scores. ``SuiteResult.passed`` is the CADTestBench Pass Rate verdict (every test
passes) and ``SuiteResult.score`` the Requirement Score (fraction of tests passed).
A missing or invalid shape fails every test.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any, Literal

import build123d as bd
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepClass import BRepClass_FaceClassifier
from OCP.BRepGProp import BRepGProp_Face
from OCP.GeomAbs import GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Plane, GeomAbs_Sphere, GeomAbs_Torus
from OCP.gp import gp_Dir, gp_Lin, gp_Pnt, gp_Pnt2d, gp_Vec
from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
from OCP.TopAbs import TopAbs_IN
from pydantic import BaseModel, ConfigDict, Field

LEN_TOL = 0.01  # mm, same comparison tolerance as the validators
ANG_TOL = 0.05  # degrees
VOL_REL = 1e-4  # relative, same as the language eval
SYM_REL = 1e-6  # symmetric-difference volume / part volume
MAX_LEN_TOL = 0.5  # generated tests may not loosen the oracle beyond these
MAX_VOL_REL = 0.02

Category = Literal["validity", "topology", "geometric_type", "dimension", "volume", "spatial"]
Kind = Literal[
    # validity
    "valid_solid",
    # topology
    "solid_count", "face_count", "hole_count",
    # geometric types
    "face_type_count", "edge_radius", "chamfer",
    # dimensions and ratios
    "bbox", "bbox_extent", "bbox_ratio", "hole_diameter", "hole_depth", "cylinder", "hole_distance",
    "hole_edge_offset", "hole_pattern_circle", "hole_angular_phase", "hole_positions", "wall_thickness",
    "feature_distance",
    # volume and mass
    "volume", "mass",
    # spatial arrangement
    "relative_position", "concentric", "centered", "symmetric",
]

CATEGORY_OF: dict[str, str] = {
    "valid_solid": "validity",
    "solid_count": "topology", "face_count": "topology", "hole_count": "topology",
    "face_type_count": "geometric_type", "edge_radius": "geometric_type", "chamfer": "geometric_type",
    "volume": "volume", "mass": "volume",
    "relative_position": "spatial", "concentric": "spatial", "centered": "spatial", "symmetric": "spatial",
}
for _k in ("bbox", "bbox_extent", "bbox_ratio", "hole_diameter", "hole_depth", "cylinder", "hole_distance",
           "hole_edge_offset", "hole_pattern_circle", "hole_angular_phase", "hole_positions", "wall_thickness",
           "feature_distance"):
    CATEGORY_OF[_k] = "dimension"

KIND_HELP: dict[str, str] = {
    "valid_solid": "{} the shape is a valid closed B-rep with exactly one solid",
    "solid_count": "{count}",
    "face_count": "{count, op: eq|ge|le}",
    "hole_count": "{count, diameter?, through?: bool} holes = concave full cylinders, counted by unique axis",
    "face_type_count": "{surface: plane|cylinder|cone|sphere|torus, count, op: eq|ge|le, axis?: x|y|z (plane normal or cylinder axis), diameter?}",
    "edge_radius": "{radius, count?, convexity: concave|convex|any} partial cylinders left by fillets (concave) or rounds (convex)",
    "chamfer": "{distance?, count?, op?} chamfer faces = cones or inclined planes; distance = 45 degree leg",
    "bbox": "{values: [a, b, c], ordered?: false} overall size; compared sorted unless ordered (then canonical X, Y, Z)",
    "bbox_extent": "{axis: x|y|z, value} canonical extent (Z = height)",
    "bbox_ratio": "{axis: x|y|z, other_axis: x|y|z, value} extent(axis) / extent(other_axis)",
    "hole_diameter": "{diameter, count?} at least one (or exactly count) holes of this diameter",
    "hole_depth": "{diameter, value} axial length of the hole of this diameter",
    "cylinder": "{type: hole|boss, diameter, length?, count?, axis?} full cylinders; length is axial extent",
    "hole_distance": "{value, diameter?, mode: any|nearest} axis-to-axis distance: some pair (any) or every hole's nearest neighbour",
    "hole_edge_offset": "{value, diameter?} every such hole's axis is value from the nearest outer side of the bounding box",
    "hole_pattern_circle": "{pcd, diameter?, count?, equal_spacing?: true} holes on a circle of diameter pcd about the part centre",
    "hole_angular_phase": "{value (deg), diameter?} angular position of the pattern measured from +X, modulo the pattern pitch",
    "hole_positions": "{points: [[x, y], ...], diameter?} hole centres in the canonical frame (sign symmetric)",
    "wall_thickness": "{value, mode: eq|min|all, values?} walls between parallel planar faces; eq/min: thinnest wall; all: every thin wall equals value (or one of values)",
    "feature_distance": "{a: feature, b: feature, value} distance between the two features' axes/centres",
    "volume": "{value} mm^3",
    "mass": "{density (g/cm^3), value (g)}",
    "relative_position": "{a: feature, b: feature, axis: x|y|z, relation: gt|lt|eq, value?} coordinate of a vs b (+ value)",
    "concentric": "{a: feature, b: feature} the two features share an axis",
    "centered": "{a: feature} the feature's axis passes through the part's centre in its plane",
    "symmetric": "{plane: yz|xz} mirror symmetry about the canonical centre plane (yz: left/right, xz: front/back)",
}


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FeatureRef(_S):
    """Selects geometric features without knowing the recipe."""

    type: Literal["hole", "boss", "fillet", "round", "cylinder", "solid"]
    diameter: float | None = None
    which: Literal["all", "top", "bottom"] = "all"  # top/bottom: highest / lowest matching feature


class RequirementTest(_S):
    id: str
    requirement: str = Field(description="the requirement text this test covers")
    kind: Kind
    category: Category | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    tol: float | None = None  # absolute (mm, degrees or count)
    rel_tol: float | None = None  # relative, for volume and mass

    def model_post_init(self, _ctx) -> None:
        if self.category is None:
            self.category = CATEGORY_OF[self.kind]


@dataclass
class TestResult:
    id: str
    kind: str
    category: str
    requirement: str
    passed: bool
    expected: Any = None
    actual: Any = None
    note: str | None = None


@dataclass
class SuiteResult:
    passed: bool  # Pass Rate verdict: every test passed
    score: float  # Requirement Score: fraction of tests passed
    total: int
    failed: int
    results: list[TestResult] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        return {"passed": self.passed, "score": round(self.score, 4), "total": self.total, "failed": self.failed,
                "error": self.error, "results": [r.__dict__ for r in self.results]}


# ---------------------------------------------------------------- measurement


_SURF = {GeomAbs_Plane: "plane", GeomAbs_Cylinder: "cylinder", GeomAbs_Cone: "cone", GeomAbs_Sphere: "sphere",
         GeomAbs_Torus: "torus"}
_AX = {"x": 0, "y": 1, "z": 2}


@dataclass
class CylFeature:
    diameter: float
    axis: tuple[float, float, float]  # unit, canonical sign
    point: tuple[float, float, float]  # on the axis, at the middle of the axial extent
    t_min: float
    t_max: float
    kind: str  # hole | boss | fillet | round

    @property
    def length(self) -> float:
        return self.t_max - self.t_min

    @property
    def axis_name(self) -> str | None:
        for name, i in _AX.items():
            if abs(abs(self.axis[i]) - 1) < 1e-6:
                return name
        return None

    def plane_xy(self) -> tuple[float, float]:
        """Axis position in the plane normal to the axis: (x, y) for Z axes, (y, z) for X, (x, z) for Y."""
        p = self.point
        return {"z": (p[0], p[1]), "x": (p[1], p[2]), "y": (p[0], p[2])}.get(self.axis_name or "z", (p[0], p[1]))


def _canon_axis(d) -> tuple[float, float, float]:
    a = (round(d[0], 9), round(d[1], 9), round(d[2], 9))
    if a[2] < 0 or (a[2] == 0 and (a[1] < 0 or (a[1] == 0 and a[0] < 0))):
        a = (-a[0], -a[1], -a[2])
    return a


def canonicalize(shape) -> bd.Shape:
    """Rotate so X is the longer horizontal extent, centre on X=Y=0 and put the bottom at Z=0."""
    bb = shape.bounding_box()
    if bb.size.Y > bb.size.X + LEN_TOL:
        shape = shape.rotate(bd.Axis.Z, 90)
        bb = shape.bounding_box()
    c = bb.center()
    return shape.moved(bd.Location((-c.X, -c.Y, -bb.min.Z)))


class Probe:
    """Lazily computed measurements of one shape in the canonical frame."""

    def __init__(self, shape, canonical: bool = True):
        self.shape = canonicalize(shape) if canonical else shape
        bb = self.shape.bounding_box()
        self.bb_min = (bb.min.X, bb.min.Y, bb.min.Z)
        self.bb_max = (bb.max.X, bb.max.Y, bb.max.Z)
        self.size = (bb.size.X, bb.size.Y, bb.size.Z)
        self.center = tuple((a + b) / 2 for a, b in zip(self.bb_min, self.bb_max))

    @cached_property
    def valid(self) -> bool:
        return bool(self.shape.is_valid)

    @cached_property
    def solids(self) -> int:
        return len(self.shape.solids())

    @cached_property
    def volume(self) -> float:
        return float(self.shape.volume)

    @cached_property
    def faces(self) -> list:
        return list(self.shape.faces())

    def surface_type(self, face) -> str:
        return _SURF.get(BRepAdaptor_Surface(face.wrapped).GetType(), "other")

    @cached_property
    def _intersector(self):
        it = IntCurvesFace_ShapeIntersector()
        it.Load(self.shape.wrapped, 1e-7)
        return it

    def ray_hits(self, origin, direction, t0: float = -1e7, t1: float = 1e7) -> list[float]:
        it = self._intersector
        it.Perform(gp_Lin(gp_Pnt(*origin), gp_Dir(*direction)), t0, t1)
        return sorted(it.WParameter(i) for i in range(1, it.NbPnt() + 1))

    @cached_property
    def cylinders(self) -> list[CylFeature]:
        groups: dict[tuple, dict] = {}
        for face in self.faces:
            surf = BRepAdaptor_Surface(face.wrapped)
            if surf.GetType() != GeomAbs_Cylinder:
                continue
            cyl = surf.Cylinder()
            ax = cyl.Axis()
            d = ax.Direction()
            axis = _canon_axis((d.X(), d.Y(), d.Z()))
            dv = bd.Vector(*axis)
            loc = bd.Vector(ax.Location().X(), ax.Location().Y(), ax.Location().Z())
            u0, u1, v0, v1 = surf.FirstUParameter(), surf.LastUParameter(), surf.FirstVParameter(), surf.LastVParameter()
            um, vm = (u0 + u1) / 2, (v0 + v1) / 2
            p = surf.Value(um, vm)
            pt = bd.Vector(p.X(), p.Y(), p.Z())
            pn, nv = gp_Pnt(), gp_Vec()
            BRepGProp_Face(face.wrapped).Normal(um, vm, pn, nv)
            n = bd.Vector(nv.X(), nv.Y(), nv.Z())
            radial = (pt - loc) - dv * (pt - loc).dot(dv)
            concave = radial.dot(n) < 0
            ts = []
            for v in (v0, v1):
                q = surf.Value(um, v)
                ts.append(bd.Vector(q.X(), q.Y(), q.Z()).dot(dv))
            proj = loc - dv * loc.dot(dv)
            key = (round(cyl.Radius(), 4), axis, (round(proj.X, 3), round(proj.Y, 3), round(proj.Z, 3)), concave)
            g = groups.setdefault(key, {"r": cyl.Radius(), "axis": axis, "proj": proj, "concave": concave,
                                        "sweep": 0.0, "t": []})
            g["sweep"] += abs(u1 - u0)
            g["t"] += ts
        out = []
        for g in groups.values():
            full = g["sweep"] >= 2 * math.pi - 1e-6
            kind = ("hole" if g["concave"] else "boss") if full else ("fillet" if g["concave"] else "round")
            t0, t1 = min(g["t"]), max(g["t"])
            dv = bd.Vector(*g["axis"])
            mid = g["proj"] + dv * ((t0 + t1) / 2)
            out.append(CylFeature(round(2 * g["r"], 6), g["axis"], (mid.X, mid.Y, mid.Z), t0, t1, kind))
        return out

    def holes(self, diameter: float | None = None, tol: float = LEN_TOL) -> list[CylFeature]:
        return [c for c in self.cylinders if c.kind == "hole" and (diameter is None or abs(c.diameter - diameter) <= tol)]

    def is_through(self, hole: CylFeature) -> bool:
        """A through hole's axis line meets no face of the part (a blind hole's axis meets its bottom)."""
        return not self.ray_hits(hole.point, hole.axis)

    def select(self, ref: dict | FeatureRef, tol: float = LEN_TOL) -> list[CylFeature]:
        ref = FeatureRef.model_validate(ref) if isinstance(ref, dict) else ref
        if ref.type == "solid":
            return [CylFeature(0.0, (0.0, 0.0, 1.0), self.center, self.bb_min[2], self.bb_max[2], "solid")]
        kinds = {"cylinder": {"hole", "boss"}}.get(ref.type, {ref.type})
        sel = [c for c in self.cylinders if c.kind in kinds and (ref.diameter is None or abs(c.diameter - ref.diameter) <= tol)]
        if sel and ref.which in ("top", "bottom"):
            pick = max if ref.which == "top" else min
            sel = [pick(sel, key=lambda c: c.point[2])]
        return sel

    @cached_property
    def planar_thicknesses(self) -> list[float]:
        """Material thickness behind sample points on planar faces, measured along the inward normal."""
        out = []
        for face in self.faces:
            surf = BRepAdaptor_Surface(face.wrapped)
            if surf.GetType() != GeomAbs_Plane:
                continue
            u0, u1, v0, v1 = surf.FirstUParameter(), surf.LastUParameter(), surf.FirstVParameter(), surf.LastVParameter()
            prop = BRepGProp_Face(face.wrapped)
            n_grid = 7
            for i in range(n_grid):
                for j in range(n_grid):
                    u = u0 + (u1 - u0) * (i + 0.5) / n_grid
                    v = v0 + (v1 - v0) * (j + 0.5) / n_grid
                    cls = BRepClass_FaceClassifier(face.wrapped, gp_Pnt2d(u, v), 1e-7)
                    if cls.State() != TopAbs_IN:
                        continue
                    p, nv = gp_Pnt(), gp_Vec()
                    prop.Normal(u, v, p, nv)
                    if nv.Magnitude() < 1e-12:
                        continue
                    nv.Normalize()
                    inward = (-nv.X(), -nv.Y(), -nv.Z())
                    it = self._intersector
                    it.Perform(gp_Lin(p, gp_Dir(*inward)), 0.0, 1e7)
                    hits = sorted((it.WParameter(k), k) for k in range(1, it.NbPnt() + 1) if it.WParameter(k) > 1e-6)
                    if not hits:
                        continue
                    # A wall is material between two parallel planes; a ray that leaves through a hole or
                    # a curved face is measuring something else.
                    exit_face = it.Face(hits[0][1])
                    es = BRepAdaptor_Surface(exit_face)
                    if es.GetType() != GeomAbs_Plane:
                        continue
                    en = es.Plane().Axis().Direction()
                    if abs(abs(en.X() * inward[0] + en.Y() * inward[1] + en.Z() * inward[2]) - 1) > 1e-6:
                        continue
                    out.append(hits[0][0])
        return out


# ---------------------------------------------------------------- test kinds


class _Fail(Exception):
    pass


def _cmp(op: str, actual: float, want: float, tol: float) -> bool:
    if op == "ge":
        return actual >= want - tol
    if op == "le":
        return actual <= want + tol
    return abs(actual - want) <= tol


def _need(args: dict, key: str):
    if args.get(key) is None:
        raise _Fail(f"missing argument '{key}'")
    return args[key]


def _hole_set(pr: Probe, a: dict, tol: float) -> list[CylFeature]:
    d = a.get("diameter")
    hs = pr.holes(float(d) if d is not None else None, max(tol, LEN_TOL))
    if not hs:
        raise _Fail(f"no holes{'' if d is None else f' of diameter {d}'}")
    return hs


def _axis_distance(a: CylFeature, b: CylFeature) -> float:
    pa, pb = bd.Vector(*a.point), bd.Vector(*b.point)
    da = bd.Vector(*a.axis)
    if a.kind != "solid" and b.kind != "solid" and abs(abs(da.dot(bd.Vector(*b.axis))) - 1) < 1e-6:
        w = pb - pa
        return (w - da * w.dot(da)).length  # parallel axes: perpendicular distance
    if a.kind != "solid" and b.kind == "solid":
        w = pb - pa
        return (w - da * w.dot(da)).length
    if b.kind != "solid" and a.kind == "solid":
        return _axis_distance(b, a)
    return (pb - pa).length


def t_valid_solid(pr, a, t):
    ok = pr.valid and pr.solids == 1
    return ok, True, {"valid": pr.valid, "solids": pr.solids}


def t_solid_count(pr, a, t):
    want = int(_need(a, "count"))
    return pr.solids == want, want, pr.solids


def t_face_count(pr, a, t):
    want = int(_need(a, "count"))
    n = len(pr.faces)
    return _cmp(a.get("op") or "eq", n, want, 0), want, n


def t_hole_count(pr, a, t):
    want = int(_need(a, "count"))
    d = a.get("diameter")
    hs = pr.holes(float(d) if d is not None else None, t.tol or LEN_TOL)
    if a.get("through") is not None:
        hs = [h for h in hs if pr.is_through(h) == bool(a["through"])]
    return _cmp(a.get("op") or "eq", len(hs), want, 0), want, len(hs)


def t_face_type_count(pr, a, t):
    surface = _need(a, "surface")
    axis = a.get("axis")
    d = a.get("diameter")
    n = 0
    for face in pr.faces:
        if pr.surface_type(face) != surface:
            continue
        surf = BRepAdaptor_Surface(face.wrapped)
        if axis:
            i = _AX[axis]
            if surface == "plane":
                dirn = surf.Plane().Axis().Direction()
            elif surface == "cylinder":
                dirn = surf.Cylinder().Axis().Direction()
            elif surface == "cone":
                dirn = surf.Cone().Axis().Direction()
            else:
                dirn = None
            if dirn is None or abs(abs((dirn.X(), dirn.Y(), dirn.Z())[i]) - 1) > 1e-6:
                continue
        if d is not None:
            if surface != "cylinder" or abs(2 * surf.Cylinder().Radius() - float(d)) > (t.tol or LEN_TOL):
                continue
        n += 1
    want = int(_need(a, "count"))
    return _cmp(a.get("op") or "eq", n, want, 0), want, n


def t_edge_radius(pr, a, t):
    r = float(_need(a, "radius"))
    conv = a.get("convexity") or "any"
    kinds = {"concave": {"fillet"}, "convex": {"round"}}.get(conv, {"fillet", "round"})
    tol = t.tol or LEN_TOL
    sel = [c for c in pr.cylinders if c.kind in kinds and abs(c.diameter / 2 - r) <= tol]
    if a.get("count") is None:
        return len(sel) >= 1, f">=1 x R{r:g}", len(sel)
    want = int(a["count"])
    return _cmp(a.get("op") or "eq", len(sel), want, 0), want, len(sel)


def _chamfer_faces(pr: Probe) -> list:
    out = []
    for face in pr.faces:
        st = pr.surface_type(face)
        if st == "cone":
            out.append(face)
        elif st == "plane":
            dn = BRepAdaptor_Surface(face.wrapped).Plane().Axis().Direction()
            comps = sorted(abs(c) for c in (dn.X(), dn.Y(), dn.Z()))
            if comps[2] < 1 - 1e-6:  # not axis aligned
                out.append(face)
    return out


def t_chamfer(pr, a, t):
    faces = _chamfer_faces(pr)
    if a.get("distance") is not None:
        d = float(a["distance"])
        tol = t.tol or LEN_TOL
        legs = []
        for f in faces:
            bb = f.bounding_box()
            ext = [e for e in (bb.size.X, bb.size.Y, bb.size.Z) if e > 1e-6]
            legs.append(min(ext) if ext else 0.0)
        faces = [f for f, leg in zip(faces, legs) if abs(leg - d) <= tol]
    if a.get("count") is None:
        return len(faces) >= 1, ">=1 chamfer face", len(faces)
    want = int(a["count"])
    return _cmp(a.get("op") or "eq", len(faces), want, 0), want, len(faces)


def t_bbox(pr, a, t):
    want = [float(x) for x in _need(a, "values")]
    if len(want) != 3:
        raise _Fail("bbox needs three values")
    tol = t.tol or LEN_TOL
    got = list(pr.size)
    if not a.get("ordered"):
        want, got = sorted(want), sorted(got)
    ok = all(abs(x - y) <= tol for x, y in zip(want, got))
    return ok, [round(x, 4) for x in want], [round(x, 4) for x in got]


def t_bbox_extent(pr, a, t):
    i = _AX[_need(a, "axis")]
    want = float(_need(a, "value"))
    return abs(pr.size[i] - want) <= (t.tol or LEN_TOL), want, round(pr.size[i], 4)


def t_bbox_ratio(pr, a, t):
    i, j = _AX[_need(a, "axis")], _AX[_need(a, "other_axis")]
    want = float(_need(a, "value"))
    got = pr.size[i] / pr.size[j]
    return abs(got - want) <= (t.tol or 1e-3), want, round(got, 5)


def t_hole_diameter(pr, a, t):
    d = float(_need(a, "diameter"))
    n = len(pr.holes(d, t.tol or LEN_TOL))
    if a.get("count") is None:
        return n >= 1, f">=1 x {d:g}", n
    return n == int(a["count"]), int(a["count"]), n


def t_hole_depth(pr, a, t):
    hs = _hole_set(pr, a, t.tol or LEN_TOL)
    want = float(_need(a, "value"))
    got = [round(h.length, 4) for h in hs]
    return all(abs(g - want) <= (t.tol or LEN_TOL) for g in got), want, got


def t_cylinder(pr, a, t):
    typ = a.get("type") or "boss"
    d = float(_need(a, "diameter"))
    tol = t.tol or LEN_TOL
    sel = pr.select({"type": typ, "diameter": d}, tol)
    if a.get("axis"):
        sel = [c for c in sel if c.axis_name == a["axis"]]
    if a.get("length") is not None:
        sel = [c for c in sel if abs(c.length - float(a["length"])) <= tol]
    want = int(a["count"]) if a.get("count") is not None else None
    got = len(sel)
    desc = {"lengths": [round(c.length, 4) for c in pr.select({"type": typ, "diameter": d}, tol)], "matching": got}
    return (got == want) if want is not None else got >= 1, want if want is not None else ">=1", desc


def t_hole_distance(pr, a, t):
    hs = _hole_set(pr, a, t.tol or LEN_TOL)
    if len(hs) < 2:
        raise _Fail("fewer than two holes")
    want = float(_need(a, "value"))
    tol = t.tol or LEN_TOL
    dists = {}
    for i, h in enumerate(hs):
        for j, g in enumerate(hs):
            if i < j:
                dists[(i, j)] = _axis_distance(h, g)
    if (a.get("mode") or "any") == "nearest":
        nearest = [min(dists[tuple(sorted((i, j)))] for j in range(len(hs)) if j != i) for i in range(len(hs))]
        return all(abs(x - want) <= tol for x in nearest), want, sorted({round(x, 4) for x in nearest})
    return any(abs(x - want) <= tol for x in dists.values()), want, sorted({round(x, 4) for x in dists.values()})


def _plane_bounds(pr: Probe, axis: str) -> tuple[tuple[float, float], tuple[float, float]]:
    i, j = {"z": (0, 1), "x": (1, 2), "y": (0, 2)}[axis]
    return (pr.bb_min[i], pr.bb_max[i]), (pr.bb_min[j], pr.bb_max[j])


def t_hole_edge_offset(pr, a, t):
    hs = _hole_set(pr, a, t.tol or LEN_TOL)
    want = float(_need(a, "value"))
    got = []
    for h in hs:
        (x0, x1), (y0, y1) = _plane_bounds(pr, h.axis_name or "z")
        x, y = h.plane_xy()
        got.append(min(x - x0, x1 - x, y - y0, y1 - y))
    return all(abs(g - want) <= (t.tol or LEN_TOL) for g in got), want, sorted({round(g, 4) for g in got})


def _polar(pr: Probe, h: CylFeature) -> tuple[float, float]:
    (x0, x1), (y0, y1) = _plane_bounds(pr, h.axis_name or "z")
    x, y = h.plane_xy()
    dx, dy = x - (x0 + x1) / 2, y - (y0 + y1) / 2
    return math.hypot(dx, dy), math.degrees(math.atan2(dy, dx)) % 360


def t_hole_pattern_circle(pr, a, t):
    hs = _hole_set(pr, a, t.tol or LEN_TOL)
    want = float(_need(a, "pcd"))
    tol = t.tol or LEN_TOL
    pol = [_polar(pr, h) for h in hs]
    ok = all(abs(2 * r - want) <= tol for r, _ in pol)
    actual: dict = {"pcd": sorted({round(2 * r, 4) for r, _ in pol}), "count": len(hs)}
    if a.get("count") is not None:
        ok = ok and len(hs) == int(a["count"])
    if a.get("equal_spacing", True) and len(hs) > 1:
        ang = sorted(th for _, th in pol)
        gaps = [(ang[(k + 1) % len(ang)] - ang[k]) % 360 for k in range(len(ang))]
        pitch = 360 / len(ang)
        ok = ok and all(abs(g - pitch) <= ANG_TOL for g in gaps)
        actual["gaps_deg"] = sorted({round(g, 3) for g in gaps})
    return ok, {"pcd": want, "count": a.get("count")}, actual


def t_hole_angular_phase(pr, a, t):
    hs = _hole_set(pr, a, t.tol or ANG_TOL)
    want = float(_need(a, "value"))
    pitch = 360 / len(hs)
    phases = [(_polar(pr, h)[1]) % pitch for h in hs]

    def close(p, w):
        d = (p - w) % pitch
        return min(d, pitch - d) <= (t.tol or ANG_TOL)

    ok = all(close(p, want % pitch) for p in phases) or all(close(p, (-want) % pitch) for p in phases)
    return ok, round(want % pitch, 4), sorted({round(p, 3) for p in phases})


def t_hole_positions(pr, a, t):
    hs = _hole_set(pr, a, t.tol or LEN_TOL)
    pts = [tuple(float(v) for v in p) for p in _need(a, "points")]
    tol = t.tol or LEN_TOL
    got = [h.plane_xy() for h in hs]

    def match(cands):
        if len(cands) != len(got):
            return False
        left = list(got)
        for p in cands:
            k = next((i for i, g in enumerate(left) if math.dist(p, g) <= tol), None)
            if k is None:
                return False
            left.pop(k)
        return True

    variants = [[(sx * x, sy * y) for x, y in pts] for sx in (1, -1) for sy in (1, -1)]
    if abs(pr.size[0] - pr.size[1]) <= LEN_TOL:  # square footprint: quarter turns are indistinguishable
        variants += [[(-y, x) for x, y in v] for v in variants]
    ok = any(match(v) for v in variants)
    return ok, [list(p) for p in pts], [[round(x, 4), round(y, 4)] for x, y in got]


def t_wall_thickness(pr, a, t):
    th = pr.planar_thicknesses
    if not th:
        raise _Fail("no planar faces to sample")
    tol = t.tol or LEN_TOL
    m = min(th)
    mode = a.get("mode") or "eq"
    if mode == "all":
        # Every thin section (thinner than twice the largest stated wall) must be one of the stated walls.
        allowed = [float(v) for v in (a.get("values") or [_need(a, "value")])]
        thin = sorted({round(x, 4) for x in th if x < 2 * max(allowed) - tol})
        ok = bool(thin) and all(any(abs(x - w) <= tol for w in allowed) for x in thin)
        return ok, allowed, thin
    want = float(_need(a, "value"))
    if mode == "min":
        return m >= want - tol, f">={want:g}", round(m, 4)
    return abs(m - want) <= tol, want, round(m, 4)


def _one(pr: Probe, ref, tol: float, label: str) -> list[CylFeature]:
    sel = pr.select(ref, max(tol, LEN_TOL))
    if not sel:
        raise _Fail(f"feature {label} {ref} not found")
    return sel


def t_feature_distance(pr, a, t):
    tol = t.tol or LEN_TOL
    A, B = _one(pr, _need(a, "a"), tol, "a"), _one(pr, _need(a, "b"), tol, "b")
    want = float(_need(a, "value"))
    ds = sorted({round(_axis_distance(x, y), 4) for x in A for y in B})
    return any(abs(d - want) <= tol for d in ds), want, ds


def t_relative_position(pr, a, t):
    tol = t.tol or LEN_TOL
    A, B = _one(pr, _need(a, "a"), tol, "a"), _one(pr, _need(a, "b"), tol, "b")
    i = _AX[a.get("axis") or "z"]
    rel = a.get("relation") or "gt"
    off = float(a.get("value") or 0.0)
    ca = sum(f.point[i] for f in A) / len(A)
    cb = sum(f.point[i] for f in B) / len(B)
    diff = ca - cb
    if rel == "gt":
        ok = diff > off + tol if a.get("value") is None else diff >= off - tol
    elif rel == "lt":
        ok = diff < -off - tol if a.get("value") is None else diff <= -off + tol
    else:
        ok = abs(diff - off) <= tol
    return ok, f"{rel} {off:g}", round(diff, 4)


def t_concentric(pr, a, t):
    tol = t.tol or LEN_TOL
    A, B = _one(pr, _need(a, "a"), tol, "a"), _one(pr, _need(a, "b"), tol, "b")
    best = math.inf
    for x in A:
        for y in B:
            if abs(abs(bd.Vector(*x.axis).dot(bd.Vector(*y.axis))) - 1) < 1e-6:
                best = min(best, _axis_distance(x, y))
    return best <= tol, 0.0, None if best == math.inf else round(best, 5)


def t_centered(pr, a, t):
    tol = t.tol or LEN_TOL
    A = _one(pr, _need(a, "a"), tol, "a")
    offs = []
    for f in A:
        (x0, x1), (y0, y1) = _plane_bounds(pr, f.axis_name or "z")
        x, y = f.plane_xy()
        offs.append(math.hypot(x - (x0 + x1) / 2, y - (y0 + y1) / 2))
    return any(o <= tol for o in offs), 0.0, sorted(round(o, 4) for o in offs)


def t_symmetric(pr, a, t):
    plane = {"yz": bd.Plane.YZ, "xz": bd.Plane.XZ}[a.get("plane") or "yz"]
    m = pr.shape.mirror(plane)
    diff = (pr.shape - m).volume + (m - pr.shape).volume
    rel = diff / max(pr.volume, 1e-12)
    return rel <= (t.rel_tol or SYM_REL), 0.0, float(f"{rel:.3e}")


def t_volume(pr, a, t):
    want = float(_need(a, "value"))
    rel = abs(pr.volume - want) / max(abs(want), 1e-12)
    return rel <= (t.rel_tol or VOL_REL), want, round(pr.volume, 4)


def t_mass(pr, a, t):
    rho = float(_need(a, "density"))  # g/cm^3 = 1e-3 g/mm^3
    want = float(_need(a, "value"))
    got = pr.volume * rho * 1e-3
    rel = abs(got - want) / max(abs(want), 1e-12)
    return rel <= (t.rel_tol or VOL_REL), want, round(got, 4)


_KINDS = {name[2:]: fn for name, fn in globals().items() if name.startswith("t_") and callable(fn)}
assert set(_KINDS) == set(CATEGORY_OF), set(_KINDS) ^ set(CATEGORY_OF)


# ---------------------------------------------------------------- running


def load_shape(source) -> bd.Shape:
    if isinstance(source, (str, Path)):
        return bd.import_step(str(source))
    return source


def run_tests(tests: list[RequirementTest | dict], source, canonical: bool = True) -> SuiteResult:
    """Run a suite against a STEP path or a build123d shape. ``source=None`` means no geometry."""
    tests = [RequirementTest.model_validate(x) if isinstance(x, dict) else x for x in tests]
    if not tests:
        return SuiteResult(False, 0.0, 0, 0, [], "empty test suite")
    probe, err = None, None
    if source is None:
        err = "no geometry"
    else:
        try:
            probe = Probe(load_shape(source), canonical=canonical)
        except Exception as exc:  # unreadable STEP, empty shape
            err = f"could not load geometry: {exc}"
    results = []
    for t in tests:
        if probe is None:
            results.append(TestResult(t.id, t.kind, t.category, t.requirement, False, note=err))
            continue
        try:
            ok, expected, actual = _KINDS[t.kind](probe, t.args, t)
            results.append(TestResult(t.id, t.kind, t.category, t.requirement, bool(ok), expected, actual))
        except _Fail as exc:
            results.append(TestResult(t.id, t.kind, t.category, t.requirement, False, note=str(exc)))
        except Exception as exc:  # a broken test is a failed test, never a crash
            results.append(TestResult(t.id, t.kind, t.category, t.requirement, False, note=f"error: {type(exc).__name__}: {exc}"))
    n_pass = sum(r.passed for r in results)
    return SuiteResult(n_pass == len(results), n_pass / len(results), len(results), len(results) - n_pass, results, err)


def aggregate(suites: list[SuiteResult | None]) -> dict:
    """Pass Rate and mean Requirement Score over tasks; ``None`` (no suite / no build) counts as a failure."""
    n = len(suites)
    if not n:
        return {"tasks": 0, "pass_rate": None, "requirement_score": None}
    passed = sum(1 for s in suites if s is not None and s.passed)
    score = sum(s.score for s in suites if s is not None) / n
    return {"tasks": n, "passed": passed, "pass_rate": round(passed / n, 4), "requirement_score": round(score, 4)}


def clamp_tolerances(t: RequirementTest) -> RequirementTest:
    """Keep model-written tests from loosening the oracle beyond fixed ceilings."""
    if t.tol is not None:
        t.tol = min(abs(t.tol), MAX_LEN_TOL) or None
    if t.rel_tol is not None:
        t.rel_tol = min(abs(t.rel_tol), MAX_VOL_REL) or None
    return t
