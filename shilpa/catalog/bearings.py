"""Deep-groove ball bearings (ISO 15 boundary dimensions) as envelopes.

The solid is the d x D x B annulus with the corner chamfer r_s min, centred on
the origin with the bore along Z. That is the envelope that matters for fits
and interference; balls and cages are not modelled. Masses are the published
catalogue masses (SKF, rounded), not the envelope volume. 608, 6000 and 6200
dimensions and masses cross-check against bd_warehouse's bearing table.
"""

from __future__ import annotations

from typing import Literal

import build123d as bd

from . import generator
from ..contracts.ports import BuiltPart
from ._geom import CatalogParams, port

# designation: (d, D, B, r_s min chamfer, catalogue mass g)
DEEP_GROOVE = {
    "608": (8, 22, 7, 0.3, 12),
    "6000": (10, 26, 8, 0.3, 19),
    "6001": (12, 28, 8, 0.3, 22),
    "6002": (15, 32, 9, 0.3, 30),
    "6003": (17, 35, 10, 0.3, 39),
    "6004": (20, 42, 12, 0.6, 69),
    "6005": (25, 47, 12, 0.6, 80),
    "6200": (10, 30, 9, 0.6, 32),
    "6201": (12, 32, 10, 0.6, 37),
    "6202": (15, 35, 11, 0.6, 45),
    "6203": (17, 40, 12, 0.6, 65),
    "6204": (20, 47, 14, 1.0, 106),
    "6205": (25, 52, 15, 1.0, 128),
}

Designation = Literal["608", "6000", "6001", "6002", "6003", "6004", "6005",
                      "6200", "6201", "6202", "6203", "6204", "6205"]


class BearingParams(CatalogParams):
    designation: Designation = "608"
    seal: Literal["open", "2RS", "2Z"] = "open"  # same envelope; recorded in the designation


@generator("deep_groove_ball_bearing", BearingParams, "Single-row deep-groove ball bearing envelope", "ISO 15",
           mass_basis="catalog")
def deep_groove_ball_bearing(p: BearingParams) -> BuiltPart:
    d, D, B, r, mass = DEEP_GROOVE[p.designation]
    plane = bd.Plane.XY.offset(-B / 2)
    solid = bd.Solid.make_cylinder(D / 2, B, plane).cut(bd.Solid.make_cylinder(d / 2, B, plane))
    solid = solid.chamfer(r, None, list(solid.edges().filter_by(bd.GeomType.CIRCLE))).solid()
    dims = {"designation": p.designation, "d": d, "D": D, "B": B}
    ports = {
        "bore_axis": port("bore_axis", (0, 0, 0), (0, 0, 1), label="bore, fits a shaft", bore_d=d, fit="shaft", **dims),
        "outer": port("outer", (0, 0, 0), (0, 0, 1), label="outside diameter, fits a housing", od=D, fit="housing", **dims),
        "face_a": port("face_a", (0, 0, -B / 2), (0, 0, -1), label="side face", **dims),
        "face_b": port("face_b", (0, 0, B / 2), (0, 0, 1), label="side face", **dims),
    }
    suffix = "" if p.seal == "open" else f"-{p.seal}"
    meta = {"standard": "ISO 15", "size": f"{d}x{D}x{B}", "designation": f"{p.designation}{suffix}", **dims,
            "chamfer_min": r, "mass_g": float(mass), "mass_basis": "catalog"}  # published mass, any material
    return BuiltPart(name=f"bearing_{p.designation}", solid=solid, ports=ports, source="catalog", meta=meta)
