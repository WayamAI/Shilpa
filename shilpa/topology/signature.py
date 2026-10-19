"""Geometric signatures of faces and edges (persistent naming, roadmap "topology references").

A signature is the small, kernel-independent description CADIR pairs with a
feature-role name: surface or curve type, orientation, centroid, size and box. It
disambiguates entities that share a name (one face split in two by a cut), lets a
name be found again in a shape whose topology was rebuilt (a reimported STEP file,
a FreeCAD recompute) and is what the FreeCAD lowering matches subelements by.

Directions: plane normals keep their outward sign; axes of cylinders, cones, tori,
circles and line directions are unsigned and stored with a canonical sign.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import build123d as bd
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.GeomAbs import (GeomAbs_Circle, GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Line, GeomAbs_Plane, GeomAbs_Sphere,
                         GeomAbs_Torus)

ND = 6  # rounding of stored coordinates (mm)
_SURF = {GeomAbs_Plane: "PLANE", GeomAbs_Cylinder: "CYLINDER", GeomAbs_Cone: "CONE", GeomAbs_Sphere: "SPHERE",
         GeomAbs_Torus: "TORUS"}
_CURVE = {GeomAbs_Line: "LINE", GeomAbs_Circle: "CIRCLE"}

Vec = tuple[float, float, float]


@dataclass(frozen=True)
class Signature:
    kind: str  # "face" | "edge"
    geom: str  # PLANE, CYLINDER, CONE, SPHERE, TORUS, LINE, CIRCLE, OTHER
    center: Vec  # centre of mass
    size: float  # area (faces) or length (edges)
    direction: Vec | None = None  # plane normal (signed) or axis / line direction (canonical sign)
    radius: float | None = None  # cylinders, cones (reference radius), spheres, tori (major), circles
    axis_point: Vec | None = None  # a point on the axis (cylinders, cones, tori, circles)
    bbox: tuple[Vec, Vec] | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Signature":
        d = dict(d)
        for k in ("center", "direction", "axis_point"):
            if d.get(k) is not None:
                d[k] = tuple(d[k])
        if d.get("bbox") is not None:
            d["bbox"] = (tuple(d["bbox"][0]), tuple(d["bbox"][1]))
        return cls(**d)


def _t(v) -> Vec:
    return (round(v.X, ND), round(v.Y, ND), round(v.Z, ND))


def _p(p) -> Vec:
    return (round(p.X(), ND), round(p.Y(), ND), round(p.Z(), ND))


def canonical_axis(d: Vec) -> Vec:
    """Unsigned direction: the sign that makes the first non-zero component positive (Z first)."""
    x, y, z = d
    if z < -1e-9 or (abs(z) <= 1e-9 and (y < -1e-9 or (abs(y) <= 1e-9 and x < 0))):
        x, y, z = -x, -y, -z
    return (round(x, ND) + 0.0, round(y, ND) + 0.0, round(z, ND) + 0.0)


def _bbox(shape) -> tuple[Vec, Vec]:
    bb = shape.bounding_box()
    return _t(bb.min), _t(bb.max)


def face_signature(face: bd.Face) -> Signature:
    surf = BRepAdaptor_Surface(face.wrapped)
    geom = _SURF.get(surf.GetType(), "OTHER")
    direction = radius = axis_point = None
    if geom == "PLANE":
        direction = _t(face.normal_at())  # outward, orientation-aware
    elif geom in ("CYLINDER", "CONE", "TORUS"):
        g = {"CYLINDER": surf.Cylinder, "CONE": surf.Cone, "TORUS": surf.Torus}[geom]()
        d, loc = g.Axis().Direction(), g.Axis().Location()
        direction = canonical_axis((d.X(), d.Y(), d.Z()))
        axis_point = _foot((loc.X(), loc.Y(), loc.Z()), direction)
        radius = round({"CYLINDER": lambda: g.Radius(), "CONE": lambda: g.RefRadius(),
                        "TORUS": lambda: g.MajorRadius()}[geom](), ND)
    elif geom == "SPHERE":
        s = surf.Sphere()
        radius, axis_point = round(s.Radius(), ND), _p(s.Location())
    return Signature("face", geom, _t(face.center(bd.CenterOf.MASS)), round(face.area, ND), direction, radius, axis_point,
                     _bbox(face))


def edge_signature(edge: bd.Edge) -> Signature:
    curve = BRepAdaptor_Curve(edge.wrapped)
    geom = _CURVE.get(curve.GetType(), "OTHER")
    direction = radius = axis_point = None
    if geom == "LINE":
        d = curve.Line().Direction()
        direction = canonical_axis((d.X(), d.Y(), d.Z()))
    elif geom == "CIRCLE":
        c = curve.Circle()
        d = c.Axis().Direction()
        direction = canonical_axis((d.X(), d.Y(), d.Z()))
        radius, axis_point = round(c.Radius(), ND), _p(c.Location())
    return Signature("edge", geom, _t(edge.center(bd.CenterOf.MASS)), round(edge.length, ND), direction, radius, axis_point,
                     _bbox(edge))


def signature(entity) -> Signature:
    return face_signature(entity) if isinstance(entity, bd.Face) else edge_signature(entity)


def _foot(p: Vec, d: Vec) -> Vec:
    """Point of the axis line (through p along unit d) nearest the origin, so equal axes compare equal."""
    k = sum(a * b for a, b in zip(p, d))
    return tuple(round(a - k * b, ND) + 0.0 for a, b in zip(p, d))


def sort_key(sig: Signature) -> tuple:
    """Deterministic order for entities that share a role (centroid, then size)."""
    return tuple(round(c, 3) for c in sig.center) + (round(sig.size, 3),)


def distance(a: Signature, b: Signature, scale: float = 1.0) -> float:
    """Dissimilarity of two signatures; ``inf`` when they cannot be the same entity.

    ``scale`` is a characteristic length (the part's diagonal) that makes centroid and size
    differences dimensionless, so the score works for a 10 mm pin and a 2 m frame alike.
    """
    if a.kind != b.kind or a.geom != b.geom:
        return math.inf
    s = max(scale, 1e-9)
    score = math.dist(a.center, b.center) / s
    score += abs(a.size - b.size) / max(a.size, b.size, 1e-9)
    if a.direction and b.direction:
        dot = sum(x * y for x, y in zip(a.direction, b.direction))
        if a.geom == "PLANE":
            if dot < 0.5:
                return math.inf  # opposite normals are different faces
            score += 1 - dot
        else:
            score += 1 - abs(dot)
    if a.radius is not None and b.radius is not None:
        score += abs(a.radius - b.radius) / max(a.radius, b.radius, 1e-9)
    return score
