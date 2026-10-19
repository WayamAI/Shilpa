"""Bicycle interface-envelope library (no open library covers this).

Each generator returns an *envelope*: the outer shape that matters for fits,
clearances and interference, with ports at the standardised interfaces. They
are not manufacturing models. Local +Z is the part axis; for lateral parts
(BB, hubs, cranks, bars) +Z is the rider's left, non-drive side, so drive-side
features sit at -Z.

Standards and sources for the numbers (values marked ``# approx`` are typical
of current products rather than fixed by a standard, and should be checked
against a specific product before they gate a design):

* BSA / English bottom bracket (ISO 6696 / JIS): shell widths 68 and 73 mm,
  thread 1.370" x 24 TPI (34.80 mm major diameter), left-hand thread on the
  drive side. Shell OD 40 mm and the external-cup OD/width are approx.
* JIS square-taper spindle: 12.65 mm square nominal at the arm seat (approx;
  the 2-degree taper is not modelled).
* Threadless headsets, S.H.I.S. notation (Cane Creek / industry): ZS44 = cup
  pressed into a 44 mm head-tube bore, EC34 = external cup in a 34 mm bore;
  1-1/8" steerer = 28.6 mm, crown race seat 30.0 mm. Insertion depths and
  stack heights are approx (vary by maker, 0.5-3 mm).
* Hubs: front 100 mm OLD (9 mm QR or 12 mm thru-axle), rear 135 mm QR (10 mm
  axle) and 142 mm (12 mm thru-axle). Flange diameters and offsets are approx
  (they vary by hub model).
* Rims: ISO 5775 / ETRTO bead-seat diameters 622 (700C/29"), 584 (650B/27.5"),
  559 (26"). Hook flange height 6 mm is approx.
* Tyres: ISO 5775 / ETRTO width-BSD designation (e.g. 28-622). Envelope is a
  torus with section height = width, which is approx (real casings are 5-10 %
  lower than wide), trimmed to clear the rim flanges.
* Seatposts 27.2 / 30.9 / 31.6 mm and bar clamp 31.8 mm (also 25.4, 35.0):
  de-facto industry sizes. 22.2 mm flat-bar grip diameter. Pedal thread
  9/16" x 20 TPI (ISO 4210), left-hand on the left crank.
* Chainrings: 1/2" (12.7 mm) pitch chain (ISO 606 08B-1 / ANSI 40 pitch):
  pitch diameter p / sin(180/N), outside diameter p (0.6 + cot(180/N)).
  Road chainline 43.5 mm and double-ring spacing 8 mm are approx.
"""

from __future__ import annotations

import math
from typing import Literal

import build123d as bd
from pydantic import Field, field_validator, model_validator

from . import generator
from ..contracts.ports import BuiltPart
from ._geom import CatalogParams, cone_ring, fuse, port, ring

BSA_THREAD = "1.370x24TPI"
BSA_MAJOR_D = 34.8
STEERER_D = 28.6  # 1-1/8"
CROWN_RACE_D = 30.0


def _part(name: str, solid, ports: list, **meta) -> BuiltPart:
    return BuiltPart(name=name, solid=solid, ports={p.name: p for p in ports}, source="catalog", meta=meta)


# ---------------------------------------------------------------- bottom bracket


class BBShellParams(CatalogParams):
    shell_width: Literal[68, 73] = 68
    od: float = Field(40.0, gt=BSA_MAJOR_D)  # approx
    bore: float = Field(BSA_MAJOR_D, gt=0)  # thread major diameter; tapped minor is ~33.6 (approx)


@generator("bike.bb_shell_bsa", BBShellParams, "BSA (English) threaded BB shell envelope, frame side", "BSA / ISO 6696",
           mass_basis="envelope")
def bb_shell_bsa(p: BBShellParams) -> BuiltPart:
    w = p.shell_width
    c = {"standard": "BSA", "shell_width": w, "thread": BSA_THREAD, "bore": p.bore}
    return _part(
        f"bb_shell_bsa_{w}", ring(p.bore / 2, p.od / 2, -w / 2, w / 2),
        [port("shell_axis", (0, 0, 0), (0, 0, 1), label="BB axis, z to non-drive side", **c),
         port("drive_face", (0, 0, -w / 2), (0, 0, -1), label="drive-side shell face", **c, side_thread="LH"),
         port("non_drive_face", (0, 0, w / 2), (0, 0, 1), label="non-drive shell face", **c, side_thread="RH")],
        standard="BSA", size=f"{w}mm", designation=f"BSA {w} x {BSA_THREAD}",
    )


class BBParams(CatalogParams):
    shell_width: Literal[68, 73] = 68
    type: Literal["external_24", "square_taper"] = "external_24"
    cup_od: float = 41.0  # approx, Hollowtech-II style external cup
    cup_width: float = 10.5  # approx, cup stand-off outside the shell face
    spindle_length: float = 110.0  # square taper only, JIS designation length

    @model_validator(mode="after")
    def _spindle(self):
        if self.type == "square_taper" and self.spindle_length <= self.shell_width + 10:
            raise ValueError("square-taper spindle_length must exceed shell_width + 10")
        return self


@generator("bike.bb_bsa", BBParams, "BSA threaded bottom bracket: external-cup 24 mm or square-taper cartridge",
           "BSA / ISO 6696, JIS square taper", mass_basis="envelope")
def bb_bsa(p: BBParams) -> BuiltPart:
    w = p.shell_width
    shell = {"standard": "BSA", "shell_width": w, "thread": BSA_THREAD}
    if p.type == "external_24":
        spindle_d, out = 24.0, w / 2 + p.cup_width
        solid = fuse(ring(spindle_d / 2, BSA_MAJOR_D / 2, -w / 2, w / 2),
                     ring(spindle_d / 2, p.cup_od / 2, w / 2, out),
                     ring(spindle_d / 2, p.cup_od / 2, -out, -w / 2))
        spindle = {"spindle_d": spindle_d}
        designation = f"BSA {w} external, 24 mm spindle"
    else:
        body_d, lip_d, lip_t, sq = 33.0, 40.0, 3.0, 12.65  # approx
        out = p.spindle_length / 2
        tip = bd.Solid.make_box(sq, sq, out - w / 2 - lip_t, bd.Plane(origin=(-sq / 2, -sq / 2, w / 2 + lip_t)))
        tip2 = tip.mirror(bd.Plane.XY)
        solid = fuse(ring(0, body_d / 2, -w / 2, w / 2), ring(0, lip_d / 2, w / 2, w / 2 + lip_t),
                     ring(0, lip_d / 2, -w / 2 - lip_t, -w / 2), tip, tip2)
        spindle = {"spindle": "JIS square taper", "spindle_length": p.spindle_length}
        designation = f"BSA {w} x {p.spindle_length:g} JIS square taper"
    return _part(
        f"bb_bsa_{w}_{p.type}", solid,
        [port("spindle_axis", (0, 0, 0), (0, 0, 1), label="spindle axis, z to non-drive side", **spindle, **shell),
         port("drive_shell_seat", (0, 0, -w / 2), (0, 0, 1), label="drive cup seat on shell face", **shell, side_thread="LH"),
         port("non_drive_shell_seat", (0, 0, w / 2), (0, 0, -1), label="non-drive cup seat on shell face", **shell, side_thread="RH"),
         port("drive_crank_face", (0, 0, -out), (0, 0, -1), label="drive crank abutment", **spindle),
         port("non_drive_crank_face", (0, 0, out), (0, 0, 1), label="non-drive crank abutment", **spindle)],
        standard="BSA", size=f"{w}mm", designation=designation,
    )


# ---------------------------------------------------------------- headset / steerer

# S.H.I.S. cup: head-tube bore, insertion depth, external stack upper / lower, external OD (approx except bore).
SHIS = {
    "ZS44": {"bore": 44.0, "insert": 9.0, "upper_stack": 8.0, "lower_stack": 3.0, "ext_od": 46.0},
    "EC34": {"bore": 34.0, "insert": 8.0, "upper_stack": 14.0, "lower_stack": 11.5, "ext_od": 44.0},
}


class HeadsetCupParams(CatalogParams):
    position: Literal["upper", "lower"] = "upper"
    shis: Literal["ZS44", "EC34"] = "ZS44"


@generator("bike.headset_cup", HeadsetCupParams,
           "1-1/8\" threadless headset cup assembly (upper with top cover, or lower with crown race)",
           "S.H.I.S.", mass_basis="envelope")
def headset_cup(p: HeadsetCupParams) -> BuiltPart:
    """Local frame: head-tube end face at z = 0, head tube on -Z, external stack on +Z."""
    d = SHIS[p.shis]
    upper = p.position == "upper"
    stack = d["upper_stack"] if upper else d["lower_stack"]
    inner = STEERER_D / 2 if upper else CROWN_RACE_D / 2
    code = f"{p.shis}/{STEERER_D if upper else CROWN_RACE_D:g}"
    solid = fuse(ring(inner, d["bore"] / 2, -d["insert"], 0), ring(inner, d["ext_od"] / 2, 0, stack))
    seat = {"headset": "1-1/8 threadless", "shis": code, "cup_bore": d["bore"]}
    ports = [port("head_tube_seat", (0, 0, 0), (0, 0, -1), label="seats on the head-tube end face", **seat),
             port("steerer_axis", (0, 0, 0), (0, 0, 1), label="steering axis, z away from the head tube", steerer_d=STEERER_D)]
    if upper:
        ports.append(port("stem_seat", (0, 0, stack), (0, 0, 1), label="top cover, stem or spacer sits here", steerer_d=STEERER_D))
    else:
        ports.append(port("crown_race_seat", (0, 0, stack), (0, 0, 1), label="crown race, fork crown sits here",
                          crown_race_d=CROWN_RACE_D, steerer_d=STEERER_D))
    return _part(f"headset_{p.position}_{p.shis.lower()}", solid, ports, standard="S.H.I.S.", size=code,
                 designation=f"{code} {p.position}", stack_height=stack, approx=["insert", "stack", "ext_od"])


class SteererParams(CatalogParams):
    length: float = Field(280.0, gt=0)
    wall: float = Field(1.8, gt=0, lt=STEERER_D / 2)


@generator("bike.steerer", SteererParams, "1-1/8\" straight threadless steerer tube", "1-1/8 threadless",
           mass_basis="geometry")
def steerer(p: SteererParams) -> BuiltPart:
    c = {"steerer_d": STEERER_D, "standard": "1-1/8 threadless"}
    return _part(
        "steerer_1_1_8", ring(STEERER_D / 2 - p.wall, STEERER_D / 2, 0, p.length),
        [port("crown_end", (0, 0, 0), (0, 0, -1), label="crown end", **c, crown_race_d=CROWN_RACE_D),
         port("top_end", (0, 0, p.length), (0, 0, 1), label="top end", **c),
         port("steerer_axis", (0, 0, 0), (0, 0, 1), label="steerer axis", **c)],
        standard="1-1/8 threadless", size=f"{STEERER_D}x{p.length:g}", designation=f"steerer 1-1/8 x {p.length:g}",
    )


# ---------------------------------------------------------------- hubs, rims, tyres

# axle code: (OLD, axle diameter, kind, default flange offsets left/right from centre, approx)
HUB_AXLES = {
    "100x9qr": (100.0, 9.0, "QR", (34.0, 34.0)),
    "12x100": (100.0, 12.0, "thru", (34.0, 34.0)),
    "135x10qr": (135.0, 10.0, "QR", (36.0, 20.0)),
    "12x142": (142.0, 12.0, "thru", (36.0, 20.0)),
}


class HubParams(CatalogParams):
    axle: Literal["100x9qr", "12x100", "135x10qr", "12x142"] = "12x142"
    flange_d: float = Field(45.0, gt=0)  # approx
    flange_offset_left: float | None = None
    flange_offset_right: float | None = None
    body_d: float = 28.0  # approx
    end_cap_d: float = 18.0  # approx


@generator("bike.hub", HubParams, "Bicycle hub envelope: 100x9 QR / 12x100 front, 135x10 QR / 12x142 rear",
           "OLD / axle standards", mass_basis="envelope")
def hub(p: HubParams) -> BuiltPart:
    old, axle_d, kind, (fl, fr) = HUB_AXLES[p.axle]
    fl = p.flange_offset_left if p.flange_offset_left is not None else fl
    fr = p.flange_offset_right if p.flange_offset_right is not None else fr
    rear = old > 100
    ri, cap, ft = axle_d / 2, 6.0, 3.0
    parts = [ring(ri, p.body_d / 2, -(old / 2 - cap), old / 2 - cap),
             ring(ri, p.end_cap_d / 2, old / 2 - cap, old / 2), ring(ri, p.end_cap_d / 2, -old / 2, -(old / 2 - cap)),
             ring(ri, p.flange_d / 2, fl - ft / 2, fl + ft / 2), ring(ri, p.flange_d / 2, -fr - ft / 2, -fr + ft / 2)]
    if rear:  # freehub body envelope on the drive side (approx HG-style 34.5 mm)
        parts.append(ring(ri, 34.5 / 2, -(old / 2 - cap), -fr - ft / 2))
    c = {"axle": p.axle, "old": old, "axle_d": axle_d, "axle_type": kind}
    return _part(
        f"hub_{p.axle}", fuse(*parts),
        [port("axle", (0, 0, 0), (0, 0, 1), label="axle axis, z to non-drive side", **c),
         port("dropout_left", (0, 0, old / 2), (0, 0, 1), label="non-drive locknut face", **c),
         port("dropout_right", (0, 0, -old / 2), (0, 0, -1), label="drive locknut face", **c),
         port("flange_left", (0, 0, fl), (0, 0, 1), label="non-drive spoke flange", flange_d=p.flange_d, offset=fl),
         port("flange_right", (0, 0, -fr), (0, 0, -1), label="drive spoke flange", flange_d=p.flange_d, offset=fr)],
        standard="hub OLD", size=p.axle, designation=f"{'rear' if rear else 'front'} hub {p.axle}",
        flange_spacing=fl + fr, approx=["flange_d", "flange_offsets", "body_d"],
    )


BSD_NAMES = {622: "700C / 29in", 584: "650B / 27.5in", 559: "26in", 571: "650C", 590: "650A / 26x1-3/8", 630: "27in"}


class RimParams(CatalogParams):
    bsd: int = Field(622, gt=200, lt=800)
    inner_width: float = Field(19.0, gt=10, lt=60)
    depth: float = Field(22.0, gt=5)
    flange_thickness: float = Field(2.5, gt=0)
    flange_height: float = Field(6.0, gt=0)  # approx

    @field_validator("bsd")
    @classmethod
    def _known(cls, v):
        if v not in BSD_NAMES:
            raise ValueError(f"bsd {v} is not a common ISO 5775 size; use one of {sorted(BSD_NAMES)}")
        return v


@generator("bike.rim", RimParams, "Clincher rim envelope keyed to ISO 5775 bead-seat diameter", "ISO 5775",
           mass_basis="envelope")
def rim(p: RimParams) -> BuiltPart:
    r, iw = p.bsd / 2, p.inner_width
    ow = iw + 2 * p.flange_thickness
    solid = fuse(ring(r - p.depth, r, -ow / 2, ow / 2),
                 ring(r, r + p.flange_height, iw / 2, ow / 2), ring(r, r + p.flange_height, -ow / 2, -iw / 2))
    c = {"standard": "ISO 5775", "bsd": p.bsd, "inner_width": iw}
    return _part(
        f"rim_{p.bsd}x{iw:g}", solid,
        [port("hub_axis", (0, 0, 0), (0, 0, 1), label="wheel axis", **c),
         port("bead_seat", (0, 0, 0), (0, 0, 1), label="tyre bead seat (centre, wheel axis)", **c, flange_height=p.flange_height)],
        standard="ISO 5775", size=f"{iw:g}-{p.bsd}", designation=f"ISO 5775 {iw:g}C-{p.bsd} ({BSD_NAMES[p.bsd]})",
        outer_width=ow,
    )


class TyreParams(CatalogParams):
    bsd: int = Field(622, gt=200, lt=800)
    width: float = Field(28.0, ge=16, le=80)  # ETRTO nominal section width
    rim_flange_height: float = Field(6.0, ge=0)


@generator("bike.tyre", TyreParams, "Tyre envelope: torus of ETRTO width on an ISO 5775 BSD, trimmed clear of the rim",
           "ISO 5775 / ETRTO", mass_basis="envelope")
def tyre(p: TyreParams) -> BuiltPart:
    w, r = p.width, p.bsd / 2
    torus = bd.Solid.make_torus(r + w / 2, w / 2)
    clear = bd.Solid.make_cylinder(r + p.rim_flange_height, w + 2, bd.Plane.XY.offset(-(w + 2) / 2))
    solid = torus.cut(clear).solid()
    etrto = f"{w:g}-{p.bsd}"
    return _part(
        f"tyre_{w:g}_{p.bsd}", solid,
        [port("rim_seat", (0, 0, 0), (0, 0, 1), label="wheel axis; seats on a rim with the same BSD",
              etrto=etrto, bsd=p.bsd, width=w)],
        standard="ISO 5775 / ETRTO", size=etrto, designation=f"ETRTO {etrto}",
        outer_diameter=p.bsd + 2 * w, approx=["section height = width"],
    )


# ---------------------------------------------------------------- contact points


class SeatpostParams(CatalogParams):
    diameter: Literal[27.2, 30.9, 31.6] = 27.2
    length: float = Field(350.0, gt=100)
    wall: float = Field(1.8, gt=0)
    min_insertion: float = Field(80.0, gt=0)  # approx; per maker, often 2.5x diameter or marked on the post


@generator("bike.seatpost", SeatpostParams, "Round seatpost envelope with a single-bolt head", "seatpost diameter",
           mass_basis="envelope")
def seatpost(p: SeatpostParams) -> BuiltPart:
    d, L = p.diameter, p.length
    head = bd.Solid.make_box(50, 24, 20, bd.Plane(origin=(-25, -12, L - 20)))
    solid = fuse(ring(d / 2 - p.wall, d / 2, 0, L - 15), head)
    return _part(
        f"seatpost_{d:g}x{L:g}", solid,
        [port("post_axis", (0, 0, 0), (0, 0, 1), label="post axis from the bottom end", seatpost_d=d),
         port("min_insertion", (0, 0, p.min_insertion), (0, 0, 1), label="minimum insertion mark",
              seatpost_d=d, min_insertion=p.min_insertion),
         port("saddle_clamp", (0, 0, L), (0, 0, 1), x=(1, 0, 0), label="saddle rail clamp centre", rails="7mm round")],
        standard="seatpost", size=f"{d:g}", designation=f"seatpost {d:g} x {L:g}",
    )


class HandlebarParams(CatalogParams):
    clamp_d: Literal[25.4, 31.8, 35.0] = 31.8
    width: float = Field(680.0, gt=200)
    grip_d: float = 22.2
    clamp_zone: float = Field(60.0, gt=0)
    taper_length: float = Field(60.0, gt=0)
    wall: float = Field(1.8, gt=0)

    @model_validator(mode="after")
    def _fits(self):
        if self.clamp_zone + 2 * self.taper_length >= self.width - 2 * 100:
            raise ValueError("handlebar too narrow for its clamp zone, tapers and 100 mm grips")
        return self


@generator("bike.handlebar", HandlebarParams, "Flat handlebar envelope with a 31.8 (or 25.4/35) clamp section",
           "bar clamp diameter", mass_basis="geometry")
def handlebar(p: HandlebarParams) -> BuiltPart:
    rc, rg, t, cz, tl = p.clamp_d / 2, p.grip_d / 2, p.wall, p.clamp_zone / 2, p.taper_length
    solid = fuse(ring(rc - t, rc, -cz, cz),
                 cone_ring(rc, rg, t, cz, cz + tl), cone_ring(rg, rc, t, -cz - tl, -cz),
                 ring(rg - t, rg, cz + tl, p.width / 2), ring(rg - t, rg, -p.width / 2, -cz - tl))
    return _part(
        f"handlebar_{p.clamp_d:g}x{p.width:g}", solid,
        [port("stem_clamp", (0, 0, 0), (0, 0, 1), label="clamp section centre, bar axis to the left",
              clamp_d=p.clamp_d, clamp_zone=p.clamp_zone),
         port("grip_left", (0, 0, p.width / 2), (0, 0, 1), label="left bar end", grip_d=p.grip_d),
         port("grip_right", (0, 0, -p.width / 2), (0, 0, -1), label="right bar end", grip_d=p.grip_d)],
        standard="bar clamp", size=f"{p.clamp_d:g}", designation=f"flat bar {p.clamp_d:g} x {p.width:g}",
    )


class StemParams(CatalogParams):
    length: float = Field(90.0, gt=20)  # steerer axis to bar centre
    angle: float = Field(-6.0, ge=-45, le=45)  # from square to the steerer, positive rises
    clamp_d: Literal[25.4, 31.8, 35.0] = 31.8
    stack: float = Field(40.0, gt=10)  # steerer clamp height
    bar_clamp_width: float = Field(40.0, gt=10)


@generator("bike.stem", StemParams, "Threadless stem envelope for a 1-1/8\" steerer", "1-1/8 threadless / bar clamp",
           mass_basis="envelope")
def stem(p: StemParams) -> BuiltPart:
    """Local frame: steerer axis +Z, clamp bottom at z = 0, stem pointing +X, +Y left."""
    a = math.radians(p.angle)
    e = (math.cos(a), 0.0, math.sin(a))
    base = (0.0, 0.0, p.stack / 2)
    bar = (base[0] + p.length * e[0], 0.0, base[2] + p.length * e[2])
    rs = STEERER_D / 2
    body = bd.Solid.make_cylinder(rs + 5, p.stack)
    ext = bd.Solid.make_cylinder(13.0, p.length, bd.Plane(origin=base, x_dir=(0, 1, 0), z_dir=e))
    yplane = bd.Plane(origin=(bar[0], -p.bar_clamp_width / 2, bar[2]), x_dir=(1, 0, 0), z_dir=(0, 1, 0))
    clamp = bd.Solid.make_cylinder(p.clamp_d / 2 + 4, p.bar_clamp_width, yplane)
    solid = fuse(body, ext, clamp)
    solid = solid.cut(bd.Solid.make_cylinder(rs, p.stack), bd.Solid.make_cylinder(p.clamp_d / 2, p.bar_clamp_width, yplane))
    return _part(
        f"stem_{p.length:g}_{p.angle:g}", fuse(solid),
        [port("steerer_clamp", (0, 0, 0), (0, 0, -1), x=(1, 0, 0), label="clamp underside, sits on headset/spacers",
              steerer_d=STEERER_D, stack=p.stack),
         port("steerer_axis", (0, 0, 0), (0, 0, 1), x=(1, 0, 0), label="steerer axis", steerer_d=STEERER_D),
         port("top", (0, 0, p.stack), (0, 0, 1), x=(1, 0, 0), label="clamp top, spacer/top cap", steerer_d=STEERER_D),
         port("bar_clamp", bar, (0, 1, 0), x=e, label="bar clamp centre, bar axis to the left",
              clamp_d=p.clamp_d, clamp_width=p.bar_clamp_width)],
        standard="1-1/8 threadless", size=f"{p.length:g}mm {p.angle:g}deg",
        designation=f"stem {p.length:g} x {p.angle:g} deg, {p.clamp_d:g} clamp",
    )


# ---------------------------------------------------------------- drivetrain


CHAIN_PITCH = 12.7


def pitch_diameter(teeth: int, pitch: float = CHAIN_PITCH) -> float:
    return pitch / math.sin(math.pi / teeth)


def outside_diameter(teeth: int, pitch: float = CHAIN_PITCH) -> float:
    return pitch * (0.6 + 1 / math.tan(math.pi / teeth))


class CranksetParams(CatalogParams):
    crank_length: float = Field(172.5, ge=150, le=185)
    teeth: list[int] = Field(default_factory=lambda: [50, 34], min_length=1, max_length=3, validate_default=True)
    spindle_d: float = 24.0
    q_factor: float = Field(146.0, gt=100)  # approx, road
    chainline: float = Field(43.5, gt=0)  # approx, road double (centre of the ring pack)
    ring_spacing: float = Field(8.0, gt=0)  # approx
    arm_thickness: float = 14.0
    arm_width: float = 20.0
    spider_bore: float = Field(46.0, gt=0)  # clear bore of the spider around the BB cup (approx)

    @field_validator("teeth")
    @classmethod
    def _teeth(cls, v):
        if any(t < 20 or t > 60 for t in v):
            raise ValueError("chainring teeth must be within 20-60")
        return sorted(v)

    @model_validator(mode="after")
    def _clear(self):
        outer = self.chainline + (len(self.teeth) - 1) / 2 * self.ring_spacing + 1
        if outer >= self.q_factor / 2 - self.arm_thickness:
            raise ValueError("outer chainring would hit the drive crank arm; raise q_factor or lower chainline")
        return self


@generator("bike.crankset", CranksetParams, "Crankset envelope: arms, spindle and chainrings by tooth count",
           "ISO 606 chain pitch / ISO 4210 pedal thread", mass_basis="envelope")
def crankset(p: CranksetParams) -> BuiltPart:
    """Drive arm points +X at -Z (right side); left arm points -X at +Z."""
    L, q, t = p.crank_length, p.q_factor / 2, p.arm_thickness
    n = len(p.teeth)
    zs = [-(p.chainline + (k - (n - 1) / 2) * p.ring_spacing) for k in range(n)]
    pds = [pitch_diameter(z) for z in p.teeth]
    r_spider = pitch_diameter(p.teeth[0]) / 2 - 6
    rings = [ring(r_spider - 3, outside_diameter(tn) / 2, z - 1, z + 1) for tn, z in zip(p.teeth, zs)]
    # The spider is a hollow cup from the ring pack out to the drive arm, open in the middle so the
    # bottom-bracket cup (external cups stand ~45 mm off the frame centre) fits inside it.
    spider = ring(min(p.spider_bore / 2, r_spider - 4), r_spider, min(-q + t, min(zs) - 1), max(zs) + 1)
    spindle = ring(0, p.spindle_d / 2, -q + t / 2, q - t / 2)
    hw = p.arm_width / 2

    def arm(sign: float) -> bd.Solid:
        x0, x1 = (-15.0, L + 12.0) if sign > 0 else (-(L + 12.0), 15.0)
        z0 = -q if sign > 0 else q - t
        return bd.Solid.make_box(x1 - x0, 2 * hw, t, bd.Plane(origin=(x0, -hw, z0)))

    solid = fuse(spindle, spider, *rings, arm(1), arm(-1))
    ports = [port("spindle", (0, 0, 0), (0, 0, 1), label="spindle axis, z to non-drive side", spindle_d=p.spindle_d),
             port("pedal_left", (-L, 0, q), (0, 0, 1), label="left pedal thread", pedal_thread="9/16x20TPI LH"),
             port("pedal_right", (L, 0, -q), (0, 0, -1), label="right pedal thread", pedal_thread="9/16x20TPI RH")]
    for k, (tn, z, pd) in enumerate(zip(p.teeth, zs, pds), 1):
        ports.append(port(f"chainring_{k}", (0, 0, z), (0, 0, -1), label=f"{tn}T chainring plane",
                          teeth=tn, pitch_d=round(pd, 3), chainline=round(-z, 3), chain_pitch=CHAIN_PITCH))
    rings_txt = "/".join(str(tn) for tn in reversed(p.teeth))
    return _part(
        f"crankset_{L:g}_{rings_txt.replace('/', '_')}", solid, ports,
        standard="ISO 606 / ISO 4210", size=f"{L:g}mm {rings_txt}T", designation=f"crankset {L:g} mm, {rings_txt}T",
        crank_length=L, pitch_diameters=[round(d, 3) for d in pds], q_factor=p.q_factor,
    )


class SaddleParams(CatalogParams):
    length: float = Field(270.0, gt=150)
    width: float = Field(140.0, gt=80)
    height: float = Field(45.0, gt=10)  # shell + padding envelope thickness
    rail_drop: float = Field(30.0, gt=0)  # rail clamp point below the shell centre


@generator("bike.saddle", SaddleParams, "Saddle as a lofted envelope (freeform approximation)", "none",
           mass_basis="envelope")
def saddle(p: SaddleParams) -> BuiltPart:
    """Nose toward +X. Ellipse sections lofted along X; rails are not modelled."""
    # (x fraction of length, half-width fraction, half-height fraction, centre z mm)
    stations = [(-0.5, 0.75, 0.5, 6.0), (-0.35, 1.0, 1.0, 3.0), (-0.1, 0.8, 0.9, 0.0),
                (0.15, 0.42, 0.75, 0.0), (0.4, 0.24, 0.6, 1.0), (0.5, 0.18, 0.5, 2.0)]
    wires = []
    for fx, fw, fh, zc in stations:
        pl = bd.Plane(origin=(fx * p.length, 0, zc), x_dir=(0, 1, 0), z_dir=(1, 0, 0))
        wires.append(bd.Wire([bd.Edge.make_ellipse(fw * p.width / 2, fh * p.height / 2, pl)]))
    solid = bd.Solid.make_loft(wires)
    return _part(
        "saddle_envelope", solid,
        [port("rail_clamp", (0, 0, -p.rail_drop), (0, 0, -1), x=(1, 0, 0), label="rail clamp centre, z toward the post",
              rails="7mm round", clamp_zone_mm=[-35, 35])],
        standard="none", size=f"{p.length:g}x{p.width:g}", designation=f"saddle envelope {p.length:g} x {p.width:g}",
        freeform_approx=True,
    )
