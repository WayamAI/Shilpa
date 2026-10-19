"""Structural sections (tables in ``shilpa/standards/data``, sources in sources.json).

Each section is drawn as its 2D profile in the XY plane (root radii and EN
10219 corner radii included) and extruded along +Z from z = 0 to ``length``.
The section properties come from that profile, not from a table: area, mass
per metre (at the material's density), second moments about the centroidal X
and Y axes and the elastic section moduli; the tests compare them with the
published values, which checks both the dimensions and the drawing.

Frames: I / H beams and hollow sections are centred on the origin with the
height along Y (so bending about X is the strong axis, EN "y-y"); channels
have the back of the web on x = 0 and the flanges toward +X; angles have the
heel at the origin and the legs along +X and +Y. Ports: ``end_a`` / ``end_b``
on the cut ends, plus the outer faces a member is usually fixed by (flanges,
channel back, angle legs, tube sides).
"""

from __future__ import annotations

from typing import Any, Literal

import build123d as bd
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from pydantic import Field

from . import generator
from ..contracts.ports import BuiltPart
from ..standards import table
from ._geom import CatalogParams, port
from .materials import density
from .mechanical import _part

BEAMS = {r["designation"]: r for r in table("en10365_beams.csv")}
CHANNELS = {r["designation"]: r for r in table("en10365_channels.csv")}
ANGLES = {r["designation"]: r for r in table("en10056_angles.csv")}
HOLLOW = {r["designation"]: r for r in table("en10219_hollow.csv")}


def _lit(values) -> Any:
    return Literal[tuple(values)]  # type: ignore[valid-type]


def section_properties(face) -> dict[str, float]:
    """Area, centroid, centroidal second moments and elastic moduli of a planar XY profile (mm units)."""
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face.wrapped, props)
    c = props.CentreOfMass()
    m = props.MatrixOfInertia()
    bb = face.bounding_box()
    ixx, iyy = m.Value(1, 1), m.Value(2, 2)  # about the X and Y axes through the centroid
    cy = max(bb.max.Y - c.Y(), c.Y() - bb.min.Y)
    cx = max(bb.max.X - c.X(), c.X() - bb.min.X)
    return {"area_mm2": props.Mass(), "cx": c.X(), "cy": c.Y(), "Ixx_mm4": ixx, "Iyy_mm4": iyy,
            "Wx_mm3": ixx / cy, "Wy_mm3": iyy / cx}


def _polygon(points) -> bd.Face:
    return bd.Face(bd.Wire.make_polygon([bd.Vector(x, y) for x, y in points], close=True))


def _fillet(face: bd.Face, radius: float, corners) -> bd.Face:
    if radius <= 0:
        return face
    verts = [v for v in face.vertices() if any(abs(v.X - x) < 1e-6 and abs(v.Y - y) < 1e-6 for x, y in corners)]
    return face.fillet_2d(radius, verts)


def _member(gen: str, designation: str, face, length: float, origin_xy, sides: dict, material: str | None,
            standard: str, meta: dict) -> BuiltPart:
    solid = bd.Solid.extrude(face, bd.Vector(0, 0, length))
    sp = section_properties(face)
    ox, oy = origin_xy
    ports = {
        "end_a": port("end_a", (ox, oy, 0), (0, 0, -1), label="cut end", kind="face"),
        "end_b": port("end_b", (ox, oy, length), (0, 0, 1), label="cut end", kind="face"),
    }
    for name, (origin, normal, label) in sides.items():
        x = (0, 0, 1)
        ports[name] = port(name, (origin[0], origin[1], length / 2), normal, x, label=label, kind="face")
    rho = density(material or "steel")
    props = {
        "area_cm2": round(sp["area_mm2"] / 100, 3),
        "mass_kg_per_m": round(sp["area_mm2"] * rho / 1000, 3),
        "Ixx_cm4": round(sp["Ixx_mm4"] / 1e4, 2), "Iyy_cm4": round(sp["Iyy_mm4"] / 1e4, 2),
        "Wx_cm3": round(sp["Wx_mm3"] / 1e3, 2), "Wy_cm3": round(sp["Wy_mm3"] / 1e3, 2),
        "centroid_xy": [round(sp["cx"], 3), round(sp["cy"], 3)],
    }
    return _part(gen, solid, ports, {"standard": standard, "designation": f"{designation} x {length:g} mm",
                                     "size": designation, "section": designation, "length": length, **meta, **props},
                 f"{designation}_{length:g}")


class _Length(CatalogParams):
    length: float = Field(1000.0, gt=0, le=24000, description="mm")
    material: str | None = "steel"


class BeamParams(_Length):
    designation: _lit(list(BEAMS)) = "IPE 200"


@generator("section.i_beam", BeamParams, "I and H beams IPE, HEA, HEB (EN 10365)", "EN 10365")
def i_beam(p) -> BuiltPart:
    r = BEAMS[p.designation]
    h, b, tw, tf, rad = (float(r[k]) for k in ("h", "b", "tw", "tf", "r"))
    y1 = h / 2 - tf
    face = _polygon([(-b / 2, -h / 2), (b / 2, -h / 2), (b / 2, -y1), (tw / 2, -y1), (tw / 2, y1), (b / 2, y1),
                     (b / 2, h / 2), (-b / 2, h / 2), (-b / 2, y1), (-tw / 2, y1), (-tw / 2, -y1), (-b / 2, -y1)])
    face = _fillet(face, rad, [(sx * tw / 2, sy * y1) for sx in (-1, 1) for sy in (-1, 1)])
    sides = {"top_flange": ((0, h / 2), (0, 1, 0), "top of the top flange"),
             "bottom_flange": ((0, -h / 2), (0, -1, 0), "underside of the bottom flange")}
    return _member("section.i_beam", p.designation, face, p.length, (0, 0), sides, p.material, "EN 10365",
                   {"series": r["series"], "h": h, "b": b, "tw": tw, "tf": tf, "r": rad})


class ChannelParams(_Length):
    designation: _lit(list(CHANNELS)) = "UPN 100"


UPN_TAPER = 0.08  # flange inner face slope (8 %); tf is the thickness half-way along the flange


@generator("section.channel", ChannelParams, "Channels UPN with 8 % taper flanges (EN 10365)", "EN 10365")
def channel(p) -> BuiltPart:
    r = CHANNELS[p.designation]
    h, b, tw, tf, rad = (float(r[k]) for k in ("h", "b", "tw", "tf", "r"))
    xm = tw + (b - tw) / 2
    t_root, t_toe = tf + UPN_TAPER * (xm - tw), tf - UPN_TAPER * (b - xm)  # flange thickness at the web and the toe
    face = _polygon([(0, -h / 2), (b, -h / 2), (b, -h / 2 + t_toe), (tw, -h / 2 + t_root), (tw, h / 2 - t_root),
                     (b, h / 2 - t_toe), (b, h / 2), (0, h / 2)])
    face = _fillet(face, rad, [(tw, -h / 2 + t_root), (tw, h / 2 - t_root)])
    sides = {"back": ((0, 0), (-1, 0, 0), "back of the web"),
             "bottom_flange": ((b / 2, -h / 2), (0, -1, 0), "underside of the bottom flange")}
    return _member("section.channel", p.designation, face, p.length, (tw / 2, 0), sides, p.material, "EN 10365",
                   {"h": h, "b": b, "tw": tw, "tf": tf, "r": rad, "note": "toe radius not modelled"})


class AngleParams(_Length):
    designation: _lit(list(ANGLES)) = "L 50x5"


@generator("section.angle", AngleParams, "Equal-leg angles (EN 10056-1)", "EN 10056-1")
def angle(p) -> BuiltPart:
    r = ANGLES[p.designation]
    a, t, rad = float(r["a"]), float(r["t"]), float(r["r"])
    face = _fillet(_polygon([(0, 0), (a, 0), (a, t), (t, t), (t, a), (0, a)]), min(rad, a - t - 0.5), [(t, t)])
    sides = {"leg_x": ((a / 2, 0), (0, -1, 0), "outer face of the leg along X"),
             "leg_y": ((0, a / 2), (-1, 0, 0), "outer face of the leg along Y")}
    return _member("section.angle", p.designation, face, p.length, (t / 2, t / 2), sides, p.material, "EN 10056-1",
                   {"a": a, "t": t, "r": rad})


def _outer_radius(t: float) -> float:
    return 2 * t if t <= 6 else 2.5 * t if t <= 10 else 3 * t


def _box(h: float, b: float, t: float) -> bd.Face:
    ro = _outer_radius(t)
    outer = bd.Face(bd.Wire.make_rect(b, h))
    outer = outer.fillet_2d(ro, outer.vertices())
    inner_r = max(ro - t, 0.0)
    inner = bd.Face(bd.Wire.make_rect(b - 2 * t, h - 2 * t))
    inner = inner.fillet_2d(inner_r, inner.vertices()) if inner_r > 0 else inner
    return outer.cut(inner).faces()[0]


def _hollow(shape: str):
    names = [k for k, v in HOLLOW.items() if v["shape"] == shape]

    class HollowParams(_Length):
        designation: _lit(names) = names[len(names) // 3]

    return HollowParams


SquareParams, RectParams, RoundParams = _hollow("SHS"), _hollow("RHS"), _hollow("CHS")


def _box_member(gen: str, p) -> BuiltPart:
    r = HOLLOW[p.designation]
    h, b, t = float(r["h"]), float(r["b"]), float(r["t"])
    sides = {"bottom": ((0, -h / 2), (0, -1, 0), "bottom face"), "side": ((b / 2, 0), (1, 0, 0), "side face")}
    return _member(gen, p.designation, _box(h, b, t), p.length, (0, 0), sides, p.material, "EN 10219-2",
                   {"h": h, "b": b, "t": t, "outer_radius": _outer_radius(t)})


@generator("section.square_tube", SquareParams, "Square hollow sections SHS (EN 10219-2)", "EN 10219-2")
def square_tube(p) -> BuiltPart:
    return _box_member("section.square_tube", p)


@generator("section.rect_tube", RectParams, "Rectangular hollow sections RHS (EN 10219-2)", "EN 10219-2")
def rect_tube(p) -> BuiltPart:
    return _box_member("section.rect_tube", p)


@generator("section.round_tube", RoundParams, "Circular hollow sections CHS (EN 10219-2)", "EN 10219-2")
def round_tube(p) -> BuiltPart:
    r = HOLLOW[p.designation]
    od, t = float(r["h"]), float(r["t"])
    face = bd.Face(bd.Wire.make_circle(od / 2)).cut(bd.Face(bd.Wire.make_circle(od / 2 - t))).faces()[0]
    part = _member("section.round_tube", p.designation, face, p.length, (0, 0), {}, p.material, "EN 10219-2",
                   {"od": od, "t": t})
    part.ports["tube_axis"] = port("tube_axis", (0, 0, 0), (0, 0, 1), label="tube axis (outside diameter)", kind="axis",
                                   od=od)
    return part


class FlatParams(_Length):
    width: float = Field(40.0, gt=0, le=500)
    thickness: float = Field(5.0, gt=0, le=100)


@generator("section.flat_bar", FlatParams, "Flat bar (EN 10058, any size)", "EN 10058")
def flat_bar(p) -> BuiltPart:
    face = bd.Face(bd.Wire.make_rect(p.width, p.thickness))
    sides = {"bottom": ((0, -p.thickness / 2), (0, -1, 0), "bottom face"),
             "top": ((0, p.thickness / 2), (0, 1, 0), "top face")}
    name = f"FL {p.width:g}x{p.thickness:g}"
    return _member("section.flat_bar", name, face, p.length, (0, 0), sides, p.material, "EN 10058",
                   {"width": p.width, "thickness": p.thickness})


class RoundBarParams(_Length):
    diameter: float = Field(20.0, gt=0, le=500)


@generator("section.round_bar", RoundBarParams, "Round bar (EN 10060, any size)", "EN 10060")
def round_bar(p) -> BuiltPart:
    face = bd.Face(bd.Wire.make_circle(p.diameter / 2))
    part = _member("section.round_bar", f"RD {p.diameter:g}", face, p.length, (0, 0), {}, p.material, "EN 10060",
                   {"diameter": p.diameter})
    part.ports["bar_axis"] = port("bar_axis", (0, 0, 0), (0, 0, 1), label="bar axis", kind="axis",
                                  diameter=p.diameter)
    return part
