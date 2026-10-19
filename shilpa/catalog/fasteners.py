"""ISO metric fasteners, M3-M12 coarse thread, built with bd_warehouse (Apache-2.0).

* ISO 4762 socket head cap screw: head on +Z, head underside at z = 0, shank
  down to z = -length. Ports ``head_seat`` (outward normal -Z, mates a part's
  top face), ``thread_tip`` and ``thread_axis``.
* ISO 4032 hex nut and ISO 7089 plain washer: bearing face ``face_a`` at z = 0
  (normal -Z) and ``face_b`` on top (normal +Z), plus ``thread_axis``/``bore_axis``.

Threads are modelled as plain cylinders at the nominal major diameter, as in
normal CAD practice; helical threads cost seconds per part and add nothing to
fit checks. bd_warehouse ``simple=True`` models the screw shank at the thread
minor diameter (M6: 4.917), so the screw's shank is replaced by a nominal
cylinder; the nut's simple bore is already at the major diameter, so a screw
in a nut touches it without overlapping. bd_warehouse tabulates ISO 7089 washer thickness at the
maximum h (e.g. M6: 1.8 mm; the nominal is 1.6 mm), so washers are up to
0.2-0.5 mm thick on the conservative side.
"""

from __future__ import annotations

from typing import Literal

import build123d as bd
from bd_warehouse.fastener import HexNut, PlainWasher, SocketHeadCapScrew
from pydantic import Field, model_validator

from . import generator
from ..contracts.ports import BuiltPart
from ._geom import CatalogParams, port

Size = Literal["M3", "M4", "M5", "M6", "M8", "M10", "M12"]
PITCH = {"M3": 0.5, "M4": 0.7, "M5": 0.8, "M6": 1.0, "M8": 1.25, "M10": 1.5, "M12": 1.75}
# ISO 273 clearance holes (fine / medium / coarse), mm.
CLEARANCE = {
    "M3": (3.2, 3.4, 3.6), "M4": (4.3, 4.5, 4.8), "M5": (5.3, 5.5, 5.8), "M6": (6.4, 6.6, 7.0),
    "M8": (8.4, 9.0, 10.0), "M10": (10.5, 11.0, 12.0), "M12": (13.0, 13.5, 14.5),
}
# ISO 4762 nominal length range per size (as tabled by bd_warehouse), mm.
LENGTH_RANGE = {"M3": (5, 30), "M4": (6, 40), "M5": (8, 50), "M6": (8, 60), "M8": (10, 80), "M10": (16, 100), "M12": (20, 120)}


def _thread(size: str) -> str:
    return f"{size}x{PITCH[size]:g}"


def _solid(obj):
    solids = obj.solids()
    return solids[0] if len(solids) == 1 else obj


class ScrewParams(CatalogParams):
    size: Size = "M6"
    length: float = Field(20.0, gt=0, description="nominal length under the head, mm")

    @model_validator(mode="after")
    def _nominal(self):
        lo, hi = LENGTH_RANGE[self.size]
        if not lo - 1e-9 <= self.length <= hi + 1e-9:
            raise ValueError(f"{self.size} cap screw length must be within {lo:g}-{hi:g} mm")
        return self


@generator("iso4762_socket_head_cap_screw", ScrewParams, "Socket head cap screw, ISO 4762", "ISO 4762")
def socket_head_cap_screw(p: ScrewParams) -> BuiltPart:
    s = SocketHeadCapScrew(f"{p.size}-{PITCH[p.size]:g}", p.length, "iso4762", simple=True)
    d = float(p.size[1:])
    thread = _thread(p.size)
    fine, medium, coarse = CLEARANCE[p.size]
    head_d, head_h = round(s.head_diameter, 3), round(s.head_height, 3)
    common = {"thread": thread, "nominal_d": d}
    ports = {
        "head_seat": port("head_seat", (0, 0, 0), (0, 0, -1), label="head underside, mates the clamped face",
                          **common, head_d=head_d, clearance_hole_d={"fine": fine, "medium": medium, "coarse": coarse}),
        "thread_axis": port("thread_axis", (0, 0, 0), (0, 0, -1), label="screw axis, pointing into the joint",
                            **common, length=p.length),
        "thread_tip": port("thread_tip", (0, 0, -p.length), (0, 0, -1), label="thread end", **common),
        "head_top": port("head_top", (0, 0, head_h), (0, 0, 1), label="top of head (counterbore depth)",
                         head_h=head_h, head_d=head_d),
    }
    # Shank at the nominal (major) diameter over the full length; it swallows bd_warehouse's minor-diameter shank.
    shank = bd.Solid.make_cylinder(d / 2, p.length, bd.Plane.XY.offset(-p.length))
    solid = _solid(_solid(s).fuse(shank).clean())
    return BuiltPart(
        name=f"iso4762_{p.size.lower()}x{p.length:g}",
        solid=solid,
        ports=ports,
        source="catalog",
        meta={"standard": "ISO 4762", "size": p.size, "designation": f"ISO 4762 {p.size}x{p.length:g}",
              "thread": thread, "length": p.length, "head_d": head_d, "head_h": head_h, "provenance": "bd_warehouse"},
    )


class NutParams(CatalogParams):
    size: Size = "M6"


@generator("iso4032_hex_nut", NutParams, "Hex nut style 1, ISO 4032", "ISO 4032")
def hex_nut(p: NutParams) -> BuiltPart:
    n = HexNut(f"{p.size}-{PITCH[p.size]:g}", "iso4032", simple=True)
    h = round(n.nut_thickness, 3)
    bb = n.bounding_box()
    af = round(bb.max.Y - bb.min.Y, 3)
    thread = _thread(p.size)
    ports = {
        "face_a": port("face_a", (0, 0, 0), (0, 0, -1), label="bearing face", thread=thread, width_across_flats=af),
        "face_b": port("face_b", (0, 0, h), (0, 0, 1), label="bearing face (reversible)", thread=thread, width_across_flats=af),
        "thread_axis": port("thread_axis", (0, 0, 0), (0, 0, 1), label="nut axis", thread=thread),
    }
    return BuiltPart(
        name=f"iso4032_{p.size.lower()}", solid=_solid(n), ports=ports, source="catalog",
        meta={"standard": "ISO 4032", "size": p.size, "designation": f"ISO 4032 {p.size}", "thread": thread,
              "thickness": h, "width_across_flats": af, "provenance": "bd_warehouse"},
    )


class WasherParams(CatalogParams):
    size: Size = "M6"


@generator("iso7089_washer", WasherParams, "Plain washer, normal series, ISO 7089", "ISO 7089")
def plain_washer(p: WasherParams) -> BuiltPart:
    w = PlainWasher(p.size, "iso7089")
    bb = w.bounding_box()
    h, d2 = round(bb.max.Z - bb.min.Z, 3), round(bb.max.X - bb.min.X, 3)
    d1 = float(w.washer_data["d1"])
    contract = {"for": p.size, "inner_d": d1, "outer_d": d2, "thickness": h}
    ports = {
        "face_a": port("face_a", (0, 0, 0), (0, 0, -1), label="washer face", **contract),
        "face_b": port("face_b", (0, 0, h), (0, 0, 1), label="washer face", **contract),
        "bore_axis": port("bore_axis", (0, 0, 0), (0, 0, 1), label="washer axis", **contract),
    }
    return BuiltPart(
        name=f"iso7089_{p.size.lower()}", solid=_solid(w), ports=ports, source="catalog",
        meta={"standard": "ISO 7089", "size": p.size, "designation": f"ISO 7089 {p.size}", **contract,
              "provenance": "bd_warehouse"},
    )
