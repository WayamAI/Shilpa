"""Small geometry and port helpers shared by catalog generators."""

from __future__ import annotations

import math

import build123d as bd
from pydantic import BaseModel, ConfigDict

from ..contracts.ports import Port

Vec3 = tuple[float, float, float]


class CatalogParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material: str | None = None  # enables a mass estimate


def ring(r_in: float, r_out: float, z0: float, z1: float) -> bd.Solid:
    """Annulus about Z from z0 to z1; ``r_in`` 0 gives a plain cylinder."""
    plane = bd.Plane.XY.offset(z0)
    outer = bd.Solid.make_cylinder(r_out, z1 - z0, plane)
    return outer if r_in <= 0 else outer.cut(bd.Solid.make_cylinder(r_in, z1 - z0, plane)).solid()


def cone_ring(r0: float, r1: float, wall: float, z0: float, z1: float) -> bd.Solid:
    """Hollow frustum about Z, outer radius r0 at z0 to r1 at z1, radial wall ``wall``."""
    plane = bd.Plane.XY.offset(z0)
    outer = bd.Solid.make_cone(r0, r1, z1 - z0, plane)
    return outer.cut(bd.Solid.make_cone(r0 - wall, r1 - wall, z1 - z0, plane)).solid()


def ring_volume(r_in: float, r_out: float, h: float) -> float:
    return math.pi * (r_out**2 - r_in**2) * h


def fuse(*shapes) -> bd.Solid:
    out = shapes[0].fuse(*shapes[1:]).clean() if len(shapes) > 1 else shapes[0]
    solids = out.solids()
    if len(solids) != 1:
        raise ValueError(f"expected one solid after fuse, got {len(solids)}")
    return solids[0]


def _unit(v: Vec3) -> Vec3:
    n = math.sqrt(sum(c * c for c in v))
    return (v[0] / n, v[1] / n, v[2] / n)


def port(name: str, origin: Vec3, z: Vec3 = (0, 0, 1), x: Vec3 | None = None, label: str = "", **contract) -> Port:
    z = _unit(z)
    if x is None:
        x = (1.0, 0.0, 0.0) if abs(z[0]) < 0.9 else (0.0, 1.0, 0.0)
    d = sum(a * b for a, b in zip(x, z))
    x = _unit(tuple(a - d * b for a, b in zip(x, z)))
    return Port(name=name, origin=tuple(float(c) for c in origin), z=z, x=x, label=label, contract=contract)
