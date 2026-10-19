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
from ..standards import table
from ..contracts.ports import BuiltPart
from ._geom import CatalogParams, port

# designation: (d, D, B, r_s min chamfer, catalogue mass g, basic dynamic load rating C kN), from
# shilpa/standards/data/deep_groove_ball_bearings.csv (C and masses: SKF catalogue values, rounded).
DEEP_GROOVE = {
    r["designation"]: (r["d"], r["D"], r["B"], r["r_s_min"], r["mass_g"], r["dynamic_load_kN"])
    for r in table("deep_groove_ball_bearings.csv")
}

Designation = Literal[tuple(DEEP_GROOVE)]  # type: ignore[valid-type]


class BearingParams(CatalogParams):
    designation: Designation = "608"
    seal: Literal["open", "2RS", "2Z"] = "open"  # same envelope; recorded in the designation


# Used by the gearbox template; browsing offers bearing.deep_groove, which includes these sizes.
@generator("deep_groove_ball_bearing", BearingParams, "Single-row deep-groove ball bearing envelope", "ISO 15",
           mass_basis="catalog", listed=False)
def deep_groove_ball_bearing(p: BearingParams) -> BuiltPart:
    d, D, B, r, mass, c_kn = DEEP_GROOVE[p.designation]
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
            "chamfer_min": r, "dynamic_load_kN": c_kn, "mass_g": float(mass), "mass_basis": "catalog"}  # published mass, any material
    return BuiltPart(name=f"bearing_{p.designation}", solid=solid, ports=ports, source="catalog", meta=meta)
