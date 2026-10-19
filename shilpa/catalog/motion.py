"""Motion parts modelled from published dimensions (tables in ``shilpa/standards/data``, sources in sources.json).

* ``pulley.timing`` / ``pulley.idler``: GT2, HTD 3M and HTD 5M pulleys. OD =
  teeth x pitch / pi - 2 x PLD; the tooth form is simplified to a round groove
  of the profile's tooth height. Axis Z, hub at the bottom (z = 0); the belt
  plane is the ``mesh`` port, which carries the profile, pitch and belt width.
* ``belt.timing``: an open length of belt (teeth down, back at the top),
  along +X.
* ``linear.guide_rail`` / ``linear.guide_carriage``: MGN / HGR profile rails
  and blocks in one frame: the rail runs along +X from x = 0 with its bottom at
  z = 0, and a carriage is modelled where it sits on the rail, centred on
  x = 0. Both have a ``track`` port at rail-top height with z along the rail,
  so a slider mate from one to the other moves the block along the rail.
* ``linear.ball_screw`` / ``linear.ball_nut``: SFU screws (plain shaft at the
  nominal diameter, thread and machined ends not modelled) and flanged nuts.
* ``linear.bushing`` (LMxxUU, LMxxLUU, LMFxxUU) and ``linear.shaft`` (h6 rod).
* ``bearing.pillow_block``: UCP2xx envelope (base, housing and bore; the insert
  is part of the envelope), shaft along Y at the centre height.
* ``shaft.collar`` (DIN 705 A), ``pin.dowel`` (ISO 8734 / ISO 2338) and
  ``spring.compression`` (round wire, ends ground flat, rate from G d^4 / (8 D^3 n)).

Several tables are typical manufacturer values rather than a standard (see
sources.json): the parts are good for layout and clearance, and the
dimensions must be checked against the chosen supplier before ordering.
"""

from __future__ import annotations

import math
from typing import Any, Literal

import build123d as bd
from pydantic import Field, create_model, model_validator

from . import generator
from ..contracts.errors import ErrorCode, ShilpaError
from ..contracts.ports import BuiltPart
from ..standards import by, table
from ._geom import CatalogParams, port
from .mechanical import _face_port, _part

APPROX = "approximate catalogue dimensions: verify with the supplier"


def _lit(values) -> Any:
    return Literal[tuple(values)]  # type: ignore[valid-type]


def _bad(gen: str, message: str) -> ShilpaError:
    return ShilpaError(ErrorCode.INVALID_PARAMETER, f"{gen}: {message}", feature_id=gen)


def _one(shape) -> bd.Solid:
    solids = shape.solids()
    if len(solids) != 1:
        raise ShilpaError(ErrorCode.VALIDATION_FAILED, f"expected one solid, got {len(solids)}")
    return solids[0]


def _cyl(r: float, h: float, z0: float = 0.0, at=(0.0, 0.0)) -> bd.Solid:
    """Cylinder along +Z from z0, centred at ``at`` in XY."""
    return bd.Solid.make_cylinder(r, h, bd.Plane.XY.offset(z0).move(bd.Location((at[0], at[1], 0))))


# ---------------------------------------------------------------- timing pulleys and belts

BELTS = by("belt_profiles.csv", "profile")
PROFILE = Literal["GT2", "HTD3M", "HTD5M"]
DEFAULT_WIDTH = {"GT2": 6.0, "HTD3M": 9.0, "HTD5M": 15.0}
DEFAULT_BORE = {"GT2": 5.0, "HTD3M": 8.0, "HTD5M": 10.0}
HUB_L = {"GT2": 7.0, "HTD3M": 8.0, "HTD5M": 10.0}


def pulley_dims(profile: str, teeth: int) -> dict[str, float]:
    b = BELTS[profile]
    pitch_d = teeth * b["pitch"] / math.pi
    od = pitch_d - 2 * b["pld"]
    return {"pitch_d": pitch_d, "od": od, "root_d": od - 2 * b["groove_depth"],
            "flange_d": od + 2 * (b["groove_depth"] + 1.25)}


class PulleyParams(CatalogParams):
    profile: PROFILE = "GT2"
    teeth: int = Field(20, ge=10, le=150)
    belt_width: float | None = Field(None, gt=0, le=100, description="mm; empty uses the profile's common width")
    bore_d: float | None = Field(None, gt=0, description="mm; empty uses the profile's common bore")
    material: str | None = "aluminium"


def _pulley(gen: str, p, hub: bool, toothed: bool = True) -> BuiltPart:
    b = BELTS[p.profile]
    dims = pulley_dims(p.profile, p.teeth)
    width = p.belt_width or DEFAULT_WIDTH[p.profile]
    bore = p.bore_d or DEFAULT_BORE[p.profile]
    if bore > dims["root_d"] - 2:
        raise _bad(gen, f"bore {bore:g} mm leaves no wall under a {dims['root_d']:.1f} mm root diameter")
    flange_t, tooth_w = 1.0, width + 1.0
    hub_l = HUB_L[p.profile] if hub else 0.0
    hub_d = min(dims["flange_d"], max(bore + 8, 16.0))
    z = 0.0
    parts = []
    if hub:
        parts.append(_cyl(hub_d / 2, hub_l, z))
        z += hub_l
    parts.append(_cyl(dims["flange_d"] / 2, flange_t, z))
    z += flange_t
    teeth = _cyl(dims["od"] / 2, tooth_w, z)
    if toothed:
        rc = dims["od"] / 2 - b["groove_depth"] + b["groove_radius"]
        grooves = [_cyl(b["groove_radius"], tooth_w, z, at=(rc * math.cos(2 * math.pi * k / p.teeth),
                                                            rc * math.sin(2 * math.pi * k / p.teeth)))
                   for k in range(p.teeth)]
        teeth = _one(teeth.cut(*grooves))
    belt_z = z + tooth_w / 2
    parts.append(teeth)
    z += tooth_w
    parts.append(_cyl(dims["flange_d"] / 2, flange_t, z))
    z += flange_t
    solid = _one(bd.Solid.fuse(*parts).clean())
    solid = _one(solid.cut(_cyl(bore / 2, z + 2, -1)))
    c = {"belt": p.profile, "pitch": b["pitch"], "belt_width": width}
    ports = {
        "mesh": port("mesh", (0, 0, belt_z), (0, 0, 1), label="belt plane on the pulley axis", kind="axis",
                     gear_set="belt", **c),
        "bore_axis": port("bore_axis", (0, 0, 0), (0, 0, 1), label="bore, fits a shaft", kind="axis", bore_d=bore,
                          fit="shaft"),
        "bottom": port("bottom", (0, 0, 0), (0, 0, -1), label="hub end" if hub else "flange face", kind="face"),
        "top": port("top", (0, 0, z), (0, 0, 1), label="flange face", kind="face"),
    }
    kind = "idler" if gen == "pulley.idler" else "pulley"
    meta = {"standard": "ISO 13050" if p.profile.startswith("HTD") else "GT2 (Gates)",
            "designation": f"{p.profile} {p.teeth}T {kind}, bore {bore:g}, {width:g} mm belt" + ("" if toothed else
                                                                                               ", smooth"),
            "size": f"{p.teeth}T", "teeth": p.teeth, **{k: round(v, 3) for k, v in dims.items()}, "bore_d": bore,
            "belt_z": round(belt_z, 3), "note": "tooth form simplified to a round groove", "provenance": APPROX}
    return _part(gen, solid, ports, meta, f"{p.profile}_{p.teeth}t_{kind}")


@generator("pulley.timing", PulleyParams, "Timing pulley with hub and flanges (GT2, HTD 3M, HTD 5M)",
           "ISO 13050 / GT2")
def timing_pulley(p) -> BuiltPart:
    return _pulley("pulley.timing", p, hub=True)


class IdlerParams(PulleyParams):
    teeth: int = Field(20, ge=10, le=60)
    toothed: bool = True
    bore_d: float | None = Field(None, gt=0, description="bearing bore, mm; empty uses 5 mm")


@generator("pulley.idler", IdlerParams, "Flanged belt idler, toothed or smooth (bearing bore)", "ISO 13050 / GT2")
def idler(p) -> BuiltPart:
    if p.bore_d is None:
        p = p.model_copy(update={"bore_d": 5.0 if p.profile != "HTD5M" else 8.0})
    return _pulley("pulley.idler", p, hub=False, toothed=p.toothed)


class BeltParams(CatalogParams):
    profile: PROFILE = "GT2"
    width: float | None = Field(None, gt=0, le=100, description="mm; empty uses the profile's common width")
    length: float = Field(200.0, gt=0, le=3000, description="open length, mm")
    material: str | None = "polyurethane"


@generator("belt.timing", BeltParams, "Timing belt, open length (GT2, HTD 3M, HTD 5M)", "ISO 13050 / GT2")
def timing_belt(p) -> BuiltPart:
    b = BELTS[p.profile]
    width = p.width or DEFAULT_WIDTH[p.profile]
    n = max(1, int(p.length // b["pitch"]))
    length = n * b["pitch"]
    back = b["belt_thickness"] - b["tooth_height"]
    tw = b["pitch"] / 2
    pts = [(0.0, 0.0)]
    for k in range(n):  # one tooth per pitch, centred in it, hanging below the back (z < 0)
        x0 = k * b["pitch"] + (b["pitch"] - tw) / 2
        pts += [(x0, 0.0), (x0, -b["tooth_height"]), (x0 + tw, -b["tooth_height"]), (x0 + tw, 0.0)]
    pts += [(length, 0.0), (length, back), (0.0, back)]
    outline = bd.Wire.make_polygon([bd.Vector(x, 0, zz) for x, zz in pts], close=True)
    solid = _one(bd.Solid.extrude(bd.Face(outline), bd.Vector(0, width, 0)).moved(bd.Location((0, -width / 2, 0))))
    c = {"belt": p.profile, "pitch": b["pitch"], "belt_width": width}
    ports = {
        "end_a": port("end_a", (0, 0, back / 2), (-1, 0, 0), label="belt end", kind="face", **c),
        "end_b": port("end_b", (length, 0, back / 2), (1, 0, 0), label="belt end", kind="face", **c),
        "back": port("back", (length / 2, 0, back), (0, 0, 1), label="belt back", kind="face", **c),
    }
    meta = {"standard": "ISO 13050" if p.profile.startswith("HTD") else "GT2 (Gates)",
            "designation": f"{p.profile} belt {width:g} mm x {length:g} mm ({n} teeth)", "size": f"{width:g} x {length:g}",
            "teeth": n, "length": length, "provenance": APPROX}
    return _part("belt.timing", solid, ports, meta, f"{p.profile}_belt_{width:g}x{length:g}")


# ---------------------------------------------------------------- profile rail guides

GUIDES = by("linear_guides.csv", "size")


class RailParams(CatalogParams):
    size: _lit(list(GUIDES)) = "MGN12"
    length: float = Field(300.0, ge=20, le=4000)
    material: str | None = "steel"


@generator("linear.guide_rail", RailParams, "Profile rail for MGN / HGR guides, with mounting holes",
           "HIWIN-compatible MGN / HG")
def guide_rail(p) -> BuiltPart:
    g = GUIDES[p.size]
    w, h, pitch = float(g["rail_w"]), float(g["rail_h"]), float(g["hole_pitch"])
    solid = bd.Solid.make_box(p.length, w, h, bd.Plane.XY.move(bd.Location((0, -w / 2, 0))))
    n = max(1, int((p.length - g["hole_d"] * 2) // pitch) + 1)
    e = (p.length - (n - 1) * pitch) / 2
    holes = [_cyl(g["hole_d"] / 2, h + 2, -1, at=(e + k * pitch, 0)) for k in range(n)]
    solid = _one(solid.cut(*holes))
    c = {"guide": p.size}
    ports = {
        "track": port("track", (0, 0, h), (1, 0, 0), (0, 0, 1), kind="point", label="rail top at the start, along the rail",
                      **c),
        "bottom": port("bottom", (p.length / 2, w / 4, 0), (0, 0, -1), kind="face", label="mounting face",
                       rail_bolt=g["rail_bolt"], hole_pitch=pitch),
        "end_a": port("end_a", (0, 0, h / 2), (-1, 0, 0), (0, 0, 1), kind="face", label="rail end"),
        "end_b": port("end_b", (p.length, 0, h / 2), (1, 0, 0), (0, 0, 1), kind="face", label="rail end"),
    }
    meta = {"standard": "HIWIN-compatible", "designation": f"{p.size} rail x {p.length:g} mm", "size": p.size,
            "rail_w": w, "rail_h": h, "hole_pitch": pitch, "holes": n, "end_distance": round(e, 2),
            "rail_bolt": g["rail_bolt"], "provenance": APPROX}
    return _part("linear.guide_rail", solid, ports, meta, f"{p.size}_rail_{p.length:g}")


def _carriage_check(self):
    if self.block == "H" and GUIDES[self.size]["block_l_h"] is None:
        raise ValueError(f"linear.guide_carriage: {self.size} has no long (H) block in the table")
    return self


CarriageParams = create_model(
    "CarriageParams", __base__=CatalogParams,
    __validators__={"_has_block": model_validator(mode="after")(_carriage_check)},
    size=(_lit(list(GUIDES)), "MGN12"), block=(Literal["C", "H"], "C"), material=(str | None, "steel"),
)


@generator("linear.guide_carriage", CarriageParams, "Guide block (carriage) for MGN / HGR rails, as seated on its rail",
           "HIWIN-compatible MGN / HG")
def guide_carriage(p) -> BuiltPart:
    from ..contracts.iso_holes import TABLE as HOLES

    g = GUIDES[p.size]
    length = float(g["block_l_h"] if p.block == "H" else g["block_l_c"])
    bw, top, z0 = float(g["block_w"]), float(g["assembly_h"]), float(g["block_clearance"])
    rw, rh = float(g["rail_w"]), float(g["rail_h"])
    block = bd.Solid.make_box(length, bw, top - z0, bd.Plane.XY.move(bd.Location((-length / 2, -bw / 2, z0))))
    channel = bd.Solid.make_box(length + 2, rw, rh - z0, bd.Plane.XY.move(bd.Location((-length / 2 - 1, -rw / 2, z0))))
    solid = _one(block.cut(channel))
    mount_c = float(g["mount_c_h"] if p.block == "H" else g["mount_c_c"])
    mb = float(g["mount_b"])
    tap = HOLES[g["block_bolt"]].tap_drill if g["block_bolt"] in HOLES else float(g["block_bolt"][1:]) * 0.8
    depth = min(top - rh - 0.5, 1.5 * float(g["block_bolt"][1:]))
    holes = [_cyl(tap / 2, depth + 1, top - depth, at=(sx * mount_c / 2, sy * mb / 2)) for sx in (-1, 1) for sy in (-1, 1)]
    solid = _one(solid.cut(*holes))
    c = {"guide": p.size}
    ports = {
        "track": port("track", (0, 0, rh), (1, 0, 0), (0, 0, 1), kind="point",
                      label="channel roof on the rail top, along the rail", **c),
        "top": port("top", (0, 0, top), (0, 0, 1), kind="face", label="mounting face",
                    mount_b=mb, mount_c=mount_c, block_bolt=g["block_bolt"]),
    }
    meta = {"standard": "HIWIN-compatible", "designation": f"{p.size}{p.block} block", "size": f"{p.size}{p.block}",
            "block_w": bw, "block_l": length, "assembly_h": top, "mount_b": mb, "mount_c": mount_c,
            "block_bolt": g["block_bolt"], "provenance": APPROX}
    return _part("linear.guide_carriage", solid, ports, meta, f"{p.size}{p.block}_block")


# ---------------------------------------------------------------- ball screws

SCREWS = by("sfu_ball_screws.csv", "designation")


def _screw_contract(s) -> dict:
    return {"ball_screw": s["designation"], "screw_d": float(s["d"]), "lead": float(s["lead"])}


class BallScrewParams(CatalogParams):
    designation: _lit(list(SCREWS)) = "SFU1605"
    length: float = Field(500.0, ge=50, le=4000)
    material: str | None = "steel"


@generator("linear.ball_screw", BallScrewParams, "SFU rolled ball screw shaft (thread and machined ends not modelled)",
           "SFU (DIN 69051 form)")
def ball_screw(p) -> BuiltPart:
    s = SCREWS[p.designation]
    solid = _cyl(s["d"] / 2, p.length)
    ports = {
        "screw_axis": port("screw_axis", (0, 0, 0), (0, 0, 1), kind="axis", label="screw axis", **_screw_contract(s)),
        "end_a": port("end_a", (0, 0, 0), (0, 0, -1), kind="face", label="shaft end"),
        "end_b": port("end_b", (0, 0, p.length), (0, 0, 1), kind="face", label="shaft end"),
    }
    meta = {"standard": "SFU", "designation": f"{p.designation} x {p.length:g} mm", "size": p.designation,
            **_screw_contract(s), "length": p.length, "provenance": APPROX}
    return _part("linear.ball_screw", solid, ports, meta, f"{p.designation}_{p.length:g}")


class BallNutParams(CatalogParams):
    designation: _lit(list(SCREWS)) = "SFU1605"
    material: str | None = "steel"


@generator("linear.ball_nut", BallNutParams, "SFU flanged ball nut (round flange)", "SFU (DIN 69051 form)")
def ball_nut(p) -> BuiltPart:
    s = SCREWS[p.designation]
    ft, nl = float(s["flange_t"]), float(s["nut_l"])
    body = bd.Solid.fuse(_cyl(s["flange_d"] / 2, ft), _cyl(s["nut_d"] / 2, nl - ft, ft)).clean()
    pcd = float(s["bolt_pcd"])
    holes = [_cyl(s["bolt_hole_d"] / 2, ft + 2, -1, at=(pcd / 2 * math.cos(2 * math.pi * k / s["bolt_count"]),
                                                         pcd / 2 * math.sin(2 * math.pi * k / s["bolt_count"])))
             for k in range(int(s["bolt_count"]))]
    solid = _one(body.cut(_cyl(s["d"] / 2, nl + 2, -1), *holes))
    ports = {
        "screw_axis": port("screw_axis", (0, 0, 0), (0, 0, 1), kind="axis", label="nut axis, on the screw",
                           **_screw_contract(s)),
        "flange_face": port("flange_face", (0, 0, 0), (0, 0, -1), kind="face", label="flange face",
                            bolt_pcd=pcd, bolt_count=int(s["bolt_count"]), bolt_hole_d=float(s["bolt_hole_d"])),
        "nut_end": port("nut_end", (0, 0, nl), (0, 0, 1), kind="face", label="nut end"),
    }
    meta = {"standard": "SFU", "designation": f"{p.designation} flanged nut", "size": p.designation,
            **_screw_contract(s), "flange_d": float(s["flange_d"]), "nut_l": nl, "bolt_pcd": pcd,
            "provenance": APPROX}
    return _part("linear.ball_nut", solid, ports, meta, f"{p.designation}_nut")


# ---------------------------------------------------------------- bushings and shafts

BUSHINGS = by("linear_bushings.csv", "designation")


class BushingParams(CatalogParams):
    designation: _lit(list(BUSHINGS)) = "LM8UU"
    material: str | None = "steel"


@generator("linear.bushing", BushingParams, "Linear ball bushing LMxxUU, long LMxxLUU or flanged LMFxxUU",
           "JIS B 1564 series")
def bushing(p) -> BuiltPart:
    b = BUSHINGS[p.designation]
    d, D, L = float(b["d"]), float(b["D"]), float(b["L"])
    parts = [_cyl(D / 2, L)]
    if b["flange_d"]:
        parts.append(_cyl(b["flange_d"] / 2, b["flange_t"]))
    body = bd.Solid.fuse(*parts).clean() if len(parts) > 1 else parts[0]
    cuts = [_cyl(d / 2, L + 2, -1)]
    if b["flange_d"]:
        cuts += [_cyl(b["bolt_hole_d"] / 2, b["flange_t"] + 2, -1, at=(b["bolt_pcd"] / 2 * math.cos(math.pi / 4 + k * math.pi / 2),
                                                                         b["bolt_pcd"] / 2 * math.sin(math.pi / 4 + k * math.pi / 2)))
                 for k in range(4)]
    solid = _one(body.cut(*cuts))
    ports = {
        "bore_axis": port("bore_axis", (0, 0, 0), (0, 0, 1), kind="axis", label="runs on a shaft", bore_d=d,
                          fit="shaft"),
        "outer": port("outer", (0, 0, 0), (0, 0, 1), kind="axis", label="outside diameter, fits a housing", od=D,
                      fit="housing"),
        "end_a": port("end_a", (0, 0, 0), (0, 0, -1), kind="face", label="end face" + (" (flange)" if b["flange_d"]
                                                                                         else "")),
        "end_b": port("end_b", (0, 0, L), (0, 0, 1), kind="face", label="end face"),
    }
    meta = {"standard": "JIS B 1564", "designation": p.designation, "size": f"{d:g} x {D:g} x {L:g}", "d": d, "D": D,
            "L": L, "provenance": APPROX if b["flange_d"] else "common LM-series catalogue values"}
    return _part("linear.bushing", solid, ports, meta, p.designation)


class ShaftParams(CatalogParams):
    diameter: Literal[3, 4, 5, 6, 8, 10, 12, 16, 20, 25, 30] = 8
    length: float = Field(300.0, gt=0, le=4000)
    material: str | None = "steel"


@generator("linear.shaft", ShaftParams, "Linear shaft (hardened chrome rod, tolerance h6)", "ISO 286 h6")
def linear_shaft(p) -> BuiltPart:
    d = float(p.diameter)
    solid = _cyl(d / 2, p.length)
    ports = {
        "shaft_axis": port("shaft_axis", (0, 0, 0), (0, 0, 1), kind="axis", label="shaft axis", bore_d=d, fit="shaft"),
        "end_a": port("end_a", (0, 0, 0), (0, 0, -1), kind="face", label="shaft end"),
        "end_b": port("end_b", (0, 0, p.length), (0, 0, 1), kind="face", label="shaft end"),
    }
    return _part("linear.shaft", solid, ports, {"standard": "ISO 286 h6", "designation": f"shaft {d:g} h6 x {p.length:g}",
                                                "size": f"{d:g} x {p.length:g}", "d": d, "length": p.length},
                 f"shaft_{p.diameter}_{p.length:g}")


# ---------------------------------------------------------------- pillow blocks, collars, pins, springs

PILLOWS = by("ucp_pillow_blocks.csv", "designation")


class PillowParams(CatalogParams):
    designation: _lit(list(PILLOWS)) = "UCP204"
    material: str | None = "iron"


@generator("bearing.pillow_block", PillowParams, "Pillow block unit UCP2xx (envelope), shaft along Y", "ISO 3228")
def pillow_block(p) -> BuiltPart:
    u = PILLOWS[p.designation]
    d, H, L, J, A = (float(u[k]) for k in ("d", "centre_h", "length", "bolt_spacing", "base_w"))
    t, H2, S, hole = float(u["base_t"]), float(u["overall_h"]), float(u["insert_w"]), float(u["bolt_hole_d"])
    R = H2 - H
    housing_w = min(A, S)
    base = bd.Solid.make_box(L, A, t, bd.Plane.XY.move(bd.Location((-L / 2, -A / 2, 0))))
    web = bd.Solid.make_box(2 * R * 0.8, housing_w, H - t, bd.Plane.XY.move(bd.Location((-R * 0.8, -housing_w / 2, t))))
    def along_y(r: float, w: float) -> bd.Solid:  # cylinder on the shaft axis (Y, at the centre height)
        return bd.Solid.make_cylinder(r, w, bd.Plane(origin=(0, -w / 2, H), x_dir=(1, 0, 0), z_dir=(0, 1, 0)))

    drum = along_y(R, housing_w)
    insert = along_y(min(R * 0.85, d / 2 + 8), S)
    body = bd.Solid.fuse(base, web, drum, insert).clean()
    bore = along_y(d / 2, max(A, S) + 2)
    holes = [_cyl(hole / 2, t + 2, -1, at=(sx * J / 2, 0)) for sx in (-1, 1)]
    solid = _one(body.cut(bore, *holes))
    ports = {
        "base": port("base", (0, 0, 0), (0, 0, -1), kind="face", label="base, bolts to the frame", bolt_spacing=J,
                     bolt=u["bolt"]),
        "bore_axis": port("bore_axis", (0, 0, H), (0, 1, 0), (1, 0, 0), kind="axis", label="shaft axis at the centre height",
                          bore_d=d, fit="shaft"),
    }
    meta = {"standard": "ISO 3228", "designation": p.designation, "size": f"d{d:g} H{H:g}", "d": d, "centre_h": H,
            "bolt_spacing": J, "bolt": u["bolt"], "provenance": APPROX}
    return _part("bearing.pillow_block", solid, ports, meta, p.designation)


COLLARS = by("din705_collars.csv", "d")


class CollarParams(CatalogParams):
    d: _lit(list(COLLARS)) = 8
    material: str | None = "steel"


@generator("shaft.collar", CollarParams, "Set collar with set screw (DIN 705 A)", "DIN 705")
def collar(p) -> BuiltPart:
    from ..contracts.iso_holes import TABLE as HOLES

    c = COLLARS[p.d]
    D, b, d = float(c["D"]), float(c["b"]), float(p.d)
    tap = HOLES[c["set_screw"]].tap_drill if c["set_screw"] in HOLES else 0.8 * float(c["set_screw"][1:])
    # Radial set-screw tapping from the bore out through +X, at mid-width.
    screw = bd.Solid.make_cylinder(tap / 2, D, bd.Plane(origin=(0, 0, b / 2), x_dir=(0, 1, 0), z_dir=(1, 0, 0)))
    solid = _one(_cyl(D / 2, b).cut(_cyl(d / 2, b + 2, -1), screw))
    ports = {"bore_axis": port("bore_axis", (0, 0, 0), (0, 0, 1), kind="axis", label="bore, on the shaft", bore_d=d,
                               fit="shaft"),
             "face_a": port("face_a", (0, 0, 0), (0, 0, -1), kind="face", label="side face"),
             "face_b": port("face_b", (0, 0, b), (0, 0, 1), kind="face", label="side face")}
    return _part("shaft.collar", solid, ports, {"standard": "DIN 705", "designation": f"DIN 705 A {p.d}",
                                                "size": f"{p.d} x {D:g} x {b:g}", "d": d, "D": D, "b": b,
                                                "set_screw": c["set_screw"], "provenance": APPROX}, f"collar_{p.d}")


DOWELS = by("iso8734_dowels.csv", "d")
DOWEL_LENGTHS = (3, 4, 5, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32, 35, 40, 45, 50, 55, 60, 70, 80, 90, 100)


def _dowel_check(self):
    row = DOWELS[self.d]
    ok = [L for L in DOWEL_LENGTHS if row["length_min"] <= L <= row["length_max"]]
    if self.length not in ok:
        raise ValueError(f"pin.dowel: {self.d:g} mm pins come in {', '.join(f'{L:g}' for L in ok)} mm")
    return self


DowelParams = create_model(
    "DowelParams", __base__=CatalogParams,
    __validators__={"_length": model_validator(mode="after")(_dowel_check)},
    standard=(Literal["ISO 8734", "ISO 2338"], "ISO 8734"), d=(_lit(list(DOWELS)), 6), length=(float, 20.0),
    material=(str | None, "steel"),
)


@generator("pin.dowel", DowelParams, "Parallel dowel pin, hardened (ISO 8734) or unhardened (ISO 2338), m6",
           "ISO 8734 / ISO 2338")
def dowel(p) -> BuiltPart:
    d = float(p.d)
    solid = _cyl(d / 2, p.length)
    c = min(0.15 * d, 0.8)
    solid = solid.chamfer(c, None, list(solid.edges().filter_by(bd.GeomType.CIRCLE))).solid()
    ports = {"pin_axis": port("pin_axis", (0, 0, 0), (0, 0, 1), kind="axis", label="pin axis", pin_d=d),
             "end_a": port("end_a", (0, 0, 0), (0, 0, -1), kind="face", label="pin end"),
             "end_b": port("end_b", (0, 0, p.length), (0, 0, 1), kind="face", label="pin end")}
    return _part("pin.dowel", solid, ports, {"standard": p.standard, "designation": f"{p.standard} {d:g} m6 x {p.length:g}",
                                             "size": f"{d:g} x {p.length:g}", "d": d, "length": p.length,
                                             "tolerance": "m6", "hardened": p.standard == "ISO 8734"},
                 f"dowel_{d:g}x{p.length:g}")


SPRING_G = {"spring_steel": 79300.0, "stainless": 69000.0}  # shear modulus, MPa


class SpringParams(CatalogParams):
    wire_d: float = Field(1.0, gt=0.1, le=10)
    mean_d: float = Field(10.0, gt=0, le=200, description="mean coil diameter, mm")
    free_length: float = Field(30.0, gt=0, le=500)
    coils: float = Field(8.0, ge=3, le=60, description="total coils; two are inactive (ends closed and ground)")
    spring_material: Literal["spring_steel", "stainless"] = "spring_steel"
    material: str | None = "steel"

    @model_validator(mode="after")
    def _geometry(self):
        if self.mean_d / self.wire_d < 3:
            raise ValueError("spring.compression: spring index D/d below 3 cannot be coiled")
        if self.free_length <= self.coils * self.wire_d:
            raise ValueError("spring.compression: free length must exceed the solid height (coils x wire)")
        return self


@generator("spring.compression", SpringParams, "Helical compression spring, round wire, ends ground (rate computed)",
           "EN 13906-1")
def compression_spring(p) -> BuiltPart:
    pitch = (p.free_length - p.wire_d) / p.coils
    extra = 2 * pitch  # coil past both ends, then grind flat at z = 0 and z = free length
    helix = bd.Edge.make_helix(pitch, p.free_length + extra, p.mean_d / 2, center=(0, 0, -pitch))
    start = helix.location_at(0)
    profile = bd.Face(bd.Wire.make_circle(p.wire_d / 2, bd.Plane(start.position, z_dir=helix.tangent_at(0))))
    coil = bd.Solid.sweep(profile, bd.Wire([helix]), is_frenet=True)
    cut_box = bd.Solid.make_box(p.mean_d * 2, p.mean_d * 2, p.free_length,
                                bd.Plane.XY.move(bd.Location((-p.mean_d, -p.mean_d, 0))))
    solid = _one(coil.intersect(cut_box))
    active = p.coils - 2
    k = SPRING_G[p.spring_material] * p.wire_d ** 4 / (8 * p.mean_d ** 3 * active)
    solid_h = p.coils * p.wire_d
    c = {"outer_d": round(p.mean_d + p.wire_d, 3), "inner_d": round(p.mean_d - p.wire_d, 3)}
    ports = {"end_a": _face_port(solid, "end_a", (0, 0, -1), "ground end", **c),
             "end_b": _face_port(solid, "end_b", (0, 0, 1), "ground end", **c)}
    meta = {"standard": "EN 13906-1", "designation": f"compression spring {p.wire_d:g} x {p.mean_d:g} x {p.free_length:g}",
            "size": f"d{p.wire_d:g} D{p.mean_d:g} L0 {p.free_length:g}", **c, "rate_N_per_mm": round(k, 4),
            "active_coils": active, "solid_height": round(solid_h, 3),
            "max_deflection": round(p.free_length - solid_h, 3), "spring_index": round(p.mean_d / p.wire_d, 3),
            "note": "uniform pitch, ground flat; closed end coils not modelled"}
    return _part("spring.compression", solid, ports, meta, f"spring_{p.wire_d:g}x{p.mean_d:g}x{p.free_length:g}")
