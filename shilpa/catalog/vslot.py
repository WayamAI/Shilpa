"""20-series V-slot aluminium extrusion and its hardware (OpenBuilds-compatible).

Rails: ``vslot.rail`` builds 2020, 2040, 2060, 2080, 4040, 4080 and C-beam
profiles. The cross-section is ported from bd_vslot (MIT, Copyright (c) 2024
James Keal, keeeal/bd-vslot): the same per-cell slot and cavity polylines,
rebuilt here with direct face booleans because bd_vslot's builder-mode
``LocationList`` with an empty list raises on build123d 0.13.

Hardware (``vslot.wheel``, ``vslot.tnut``) is built by bd_vslot itself.

Placement conventions:

* Rail: profile centred on the XY origin, extruded from z = 0 to z = length.
  ``end_a`` (z = 0, normal -Z) and ``end_b`` (z = length, +Z) are the cut
  ends; each module cell has a ``bore_<i>_<j>`` axis port down its 4.2 mm
  centre bore (tap M5). Every exposed slot has a ``slot_<side>_<k>`` port at
  mid-length on the slot centreline: ``z`` is the outward normal of that rail
  face, ``x`` runs along the rail, and the port straddles the slot opening
  (the slot mouth is open, so the reference points sit on the lands either
  side). Sides are ``xp``/``xn``/``yp``/``yn``; ``k`` counts along the side.
* Wheel: axis along Z, centred on z = 0, ``bore_axis`` fits two 625 bearings.
* T-nut: bolt axis along Z. ``seat`` is the top of the wings at z = 0, which
  bears on the inside of the slot lips (``lip_thickness`` below the rail
  face); the neck rises 1.5 mm above it into the slot mouth, the V-body sits
  below. The seat is two strips either side of the neck, so the port
  straddles them.
"""

from __future__ import annotations

from itertools import product
from typing import Literal

import build123d as bd
import numpy as np
from bd_vslot import HOLE_TOLERANCE, BoltSize, VSlot2020MiniWheel, VSlot2020SlidingTNut, VSlot2020Wheel
from pydantic import Field

from . import generator
from ..contracts.errors import ErrorCode, ShilpaError
from ..contracts.ports import BuiltPart
from ._geom import CatalogParams, port

PITCH = 20.0  # module cell size, mm
CENTRE_BORE_D = 4.2  # M5 tapping drill
SLOT_MOUTH = 2 * 4.58  # slot width at the rail face
STRADDLE = 7.0  # slot-port reference points, mm either side of the slot centreline
SYSTEM = "V-Slot 20"  # slot family: rails, nuts and brackets must agree on it
LIP = 1.8  # slot lip thickness: the T-nut seat sits this far inside the rail face

# Slot and cavity outlines for one cell, in the cell frame (cell centre at the origin,
# feature on the +X side), from bd_vslot.rails.
_SLOT = [(3.75, 0), (3.9, 0.15), (3.9, 2.84), (6.56, 5.5), (8.2, 5.5), (8.2, 3.125), (8.545, 3.125), (10, 4.58),
         (10, 0)]
_EDGE_CAVITY = [(10, 0), (3.9, 0), (3.9, 3.16), (7.3, 6.56), (7.3, 8.2), (10, 8.2), (10, 0)]
_CORNER_CAVITY = [(10, 0), (3.9, 0), (3.9, 2.84), (9.26, 8.2), (10, 8.2), (10, 0)]
_CENTER_CAVITY = [(10, 0), (3.9, 0), (3.9, 2.84), (3.37, 3.37), (10, 10), (10, 0)]

PROFILES: dict[str, np.ndarray] = {
    "2020": np.ones((1, 1), bool),
    "2040": np.ones((2, 1), bool),
    "2060": np.ones((3, 1), bool),
    "2080": np.ones((4, 1), bool),
    "4040": np.ones((2, 2), bool),
    "4080": np.ones((4, 2), bool),
}
_c = np.ones((4, 2), bool)
_c[1:-1, 1:] = False
PROFILES["c_beam"] = _c

Profile = Literal["2020", "2040", "2060", "2080", "4040", "4080", "c_beam"]
SIDES = ("xp", "yp", "xn", "yn")  # rotation 0, 90, 180, 270 deg


def _face(points, mirror: bool = False) -> bd.Face:
    pts = [(x, -y) for x, y in points] if mirror else list(points)
    return bd.Face(bd.Wire.make_polygon([bd.Vector(x, y) for x, y in pts], close=True))


def _slot_face() -> bd.Face:
    half = list(_SLOT)
    full = half + [(x, -y) for x, y in reversed(half)]
    return bd.Face(bd.Wire.make_polygon([bd.Vector(x, y) for x, y in full], close=True))


def _layout(array: np.ndarray):
    """Cells, exposed slots and cavities, as in bd_vslot.rails.VSlot2020RailProfile."""
    nx, ny = array.shape

    def get(i, j):
        return 0 <= i < nx and 0 <= j < ny and bool(array[i, j])

    cells, slots = [], []
    cavities: list[tuple[list, bool, tuple[int, int, int]]] = []
    for i, j in product(range(nx), range(ny)):
        if not array[i, j]:
            continue
        cells.append((i, j))
        if all(map(get, (i + 1, i, i - 1, i), (j, j + 1, j, j - 1))):
            continue
        for n, (di, dj) in enumerate(((1, 0), (0, 1), (-1, 0), (0, -1))):
            at = (i, j, n)
            if not get(i + di, j + dj):
                slots.append(at)
                continue
            if di:
                for s, mir in ((1, False), (-1, True)):
                    if get(i, j + s * di):
                        cavities.append((_CENTER_CAVITY if get(i + di, j + s * di) else _CORNER_CAVITY, mir, at))
                    else:
                        cavities.append((_EDGE_CAVITY, mir, at))
            else:
                for s, mir in ((1, True), (-1, False)):
                    if get(i + s * dj, j):
                        cavities.append((_CENTER_CAVITY if get(i + s * dj, j + dj) else _CORNER_CAVITY, mir, at))
                    else:
                        cavities.append((_EDGE_CAVITY, mir, at))
    return cells, slots, cavities


def rail_section(name: Profile) -> tuple[bd.Face, dict]:
    """The rail cross-section face (centred on the origin) and its layout."""
    array = PROFILES[name]
    nx, ny = array.shape
    cx, cy = (nx - 1) * PITCH / 2, (ny - 1) * PITCH / 2
    cells, slots, cavities = _layout(array)

    def loc(i, j, n=0):
        return bd.Location((PITCH * i - cx, PITCH * j - cy, 0), (0, 0, 90 * n))

    body = bd.Face.fuse(*[loc(i, j) * bd.Face.make_rect(PITCH, PITCH) for i, j in cells]).clean()
    cuts = [loc(i, j) * bd.Face(bd.Wire.make_circle(CENTRE_BORE_D / 2)) for i, j in cells]
    slot = _slot_face()
    cuts += [loc(i, j, n) * slot for i, j, n in slots]
    cuts += [loc(i, j, n) * _face(pts, mir) for pts, mir, (i, j, n) in cavities]
    section = body.cut(*cuts).clean()
    faces = section.faces()
    if len(faces) != 1:
        raise ShilpaError(ErrorCode.VALIDATION_FAILED, f"rail section {name} produced {len(faces)} faces")
    return faces[0], {"cells": cells, "slots": slots, "centre": (cx, cy), "size": (nx * PITCH, ny * PITCH)}


class RailParams(CatalogParams):
    profile: Profile = "2020"
    length: float = Field(250.0, ge=10, le=6000)
    material: str | None = "aluminium"


@generator("vslot.rail", RailParams, "20-series V-slot aluminium extrusion (2020 to 4080, C-beam)",
           "OpenBuilds V-Slot 20 series")
def rail(p: RailParams) -> BuiltPart:
    section, lay = rail_section(p.profile)
    solid = bd.Solid.extrude(section, bd.Vector(0, 0, p.length))
    cx, cy = lay["centre"]
    w, h = lay["size"]
    dims = {"profile": p.profile, "length": p.length, "width": w, "height": h, "slot_mouth": SLOT_MOUTH,
            "lip_thickness": LIP, "centre_bore_d": CENTRE_BORE_D, "slot_system": SYSTEM}
    # End ports at the centre of the cell nearest the section centre, so they sit on the end face.
    ei, ej = min(lay["cells"], key=lambda c: (PITCH * c[0] - cx) ** 2 + (PITCH * c[1] - cy) ** 2)
    end = (PITCH * ei - cx, PITCH * ej - cy)
    ports = {
        "end_a": port("end_a", (*end, 0), (0, 0, -1), label="cut end face", slot_system=SYSTEM),
        "end_b": port("end_b", (*end, p.length), (0, 0, 1), label="cut end face", slot_system=SYSTEM),
    }
    for i, j in lay["cells"]:
        ports[f"bore_{i}_{j}"] = port(f"bore_{i}_{j}", (PITCH * i - cx, PITCH * j - cy, 0), (0, 0, 1),
                                      label="centre bore, tap M5 for an end fastener", hole_d=CENTRE_BORE_D,
                                      thread="M5x0.8")
    counts = {s: 0 for s in SIDES}
    for i, j, n in sorted(lay["slots"], key=lambda s: (s[2], s[0], s[1])):
        side = SIDES[n]
        nz = [(1, 0, 0), (0, 1, 0), (-1, 0, 0), (0, -1, 0)][n]
        origin = (PITCH * i - cx + 10 * nz[0], PITCH * j - cy + 10 * nz[1], p.length / 2)
        name = f"slot_{side}_{counts[side]}"
        counts[side] += 1
        ports[name] = port(name, origin, nz, (0, 0, 1), label="T-slot centreline at mid-length",
                           kind="point", straddle=STRADDLE, slot_system=SYSTEM, lip_thickness=LIP,
                           slot_mouth=SLOT_MOUTH)
    meta = {"standard": "OpenBuilds V-Slot 20 series", "size": f"{p.profile} x {p.length:g}",
            "designation": f"V-slot {p.profile.replace('_', '-')} x {p.length:g} mm",
            "provenance": "bd_vslot profile (MIT)", **dims}
    return BuiltPart(name=f"vslot_{p.profile}_{p.length:g}".replace(".", "_"), solid=solid, ports=ports,
                     source="catalog", meta=meta)


class WheelParams(CatalogParams):
    size: Literal["standard", "mini"] = "standard"
    material: str | None = "acetal"


# size: (outer d, bore d, outer thickness, inner thickness, axle offset from the rail centre)
WHEELS = {"standard": (23.9, 16.0, 10.2, 5.9, 20.0), "mini": (15.2, 10.0, 8.8, 5.8, 15.0)}


@generator("vslot.wheel", WheelParams, "V-groove wheel that rides in a 20-series V-slot", "OpenBuilds V-Slot 20 series")
def wheel(p: WheelParams) -> BuiltPart:
    od, bore, t_out, _t_in, axle = WHEELS[p.size]
    part = VSlot2020Wheel() if p.size == "standard" else VSlot2020MiniWheel()
    solid = part.solids()[0]
    bearing = "2x 625" if p.size == "standard" else "2x MR105"
    dims = {"od": od, "bore_d": bore, "width": t_out, "bearings": bearing, "axle_offset_from_rail_centre": axle,
            "slot_system": SYSTEM}
    ports = {
        "bore_axis": port("bore_axis", (0, 0, 0), (0, 0, 1), label="bore, takes two bearings", bore_d=bore,
                          fit="bearing"),
        "face_a": port("face_a", (0, 0, -t_out / 2), (0, 0, -1), label="side face"),
        "face_b": port("face_b", (0, 0, t_out / 2), (0, 0, 1), label="side face"),
    }
    meta = {"standard": "OpenBuilds V-Slot 20 series", "size": p.size, "designation": f"V-slot {p.size} wheel",
            "provenance": "bd_vslot", **dims}
    return BuiltPart(name=f"vslot_wheel_{p.size}", solid=solid, ports=ports, source="catalog", meta=meta)


THREADS = {"M3": "M3x0.5", "M4": "M4x0.7", "M5": "M5x0.8"}  # same designations as the ISO fasteners


class TNutParams(CatalogParams):
    thread: Literal["M3", "M4", "M5"] = "M5"
    material: str | None = "steel"


@generator("vslot.tnut", TNutParams, "Sliding T-nut for 20-series V-slot", "OpenBuilds V-Slot 20 series")
def tnut(p: TNutParams) -> BuiltPart:
    size = BoltSize[p.thread]
    part = VSlot2020SlidingTNut(size)
    solid = part.solids()[0]
    bb = solid.bounding_box()
    # bd_vslot draws the nut with the wing tops at z = 3 and the neck to z = 4.5; put the wing tops at z = 0.
    solid = solid.moved(bd.Location((0, 0, -(bb.min.Z + 3.0))))
    hole_d = round(2 * (size.value + HOLE_TOLERANCE), 3)
    dims = {"thread": THREADS[p.thread], "hole_d": hole_d, "slot_system": SYSTEM, "length": round(bb.size.X, 3), "height": round(bb.size.Z, 3),
            "neck_height": 1.5}
    ports = {
        "thread_axis": port("thread_axis", (0, 0, 0), (0, 0, 1), label="thread axis, bolt enters from +Z",
                            thread=THREADS[p.thread], hole_d=hole_d),
        "seat": port("seat", (0, 0, 0), (0, 0, 1), (1, 0, 0), label="wing tops, bear on the slot lips",
                     kind="point", straddle=3.9, slot_system=SYSTEM),
    }
    meta = {"standard": "OpenBuilds V-Slot 20 series", "size": p.thread, "designation": f"V-slot sliding T-nut {p.thread}",
            "provenance": "bd_vslot", **dims}
    return BuiltPart(name=f"vslot_tnut_{p.thread.lower()}", solid=solid, ports=ports, source="catalog", meta=meta)
