"""Pipes and flanges, OpenBuilds motion parts, sprockets and worm drives from bd_warehouse (Apache-2.0).

* ``pipe.straight``: ASME/ISO pipe by NPS, material and schedule (bd_warehouse's
  pipe table), a tube along +Z from z = 0 to ``length``. Ports ``end_a`` / ``end_b``
  and ``pipe_axis`` (outside diameter).
* ``flange.*``: ASME B16.5 weld-neck, slip-on, socket-weld, blind and lapped
  flanges, NPS 1/2 to 24, classes 150 and 300. The gasket face is at z = 0
  (normal -Z), the hub runs up +Z. ``gasket_face`` carries the class, NPS,
  facing and the bolt pattern (bolt circle, count, hole and bolt size from
  bd_warehouse's drilling tables), so two flanges mated face to face must
  agree on all of them; ``pipe_end`` is where the pipe is welded or seated.
* ``openbuilds.*``: C-beam rail, gantry plates, end mount, riser plate, spacer
  block, L-bracket, spacers, shims, flexible coupler, lock collar, NEMA
  17 / 23 stepper motors, 8 mm lead screw, anti-backlash nut block and the
  Xtreme V-wheel, in bd_warehouse's frames. Flat parts get ``bottom`` / ``top``
  face ports on their largest faces; round parts an axis port on their bore
  or shaft. The lock collar's set screw is a separate solid in bd_warehouse
  and is not modelled.
* ``drive.*``: roller-chain sprockets (ANSI 25-80), and a worm and worm wheel
  (bd_warehouse's ZI / ZA worm geometry). Sprocket and wheel get a plain bore;
  each carries the meshing data (chain size, or module / starts / diametral
  quotient / hand) on a ``mesh`` port so a mismatched pair fails the contract
  check, and the wheel's meta gives the standard centre distance.
"""

from __future__ import annotations

import csv
import math
import re
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import bd_warehouse
import bd_warehouse.flange as FL
import bd_warehouse.gear as G
import bd_warehouse.open_builds as OB
import build123d as bd
from bd_warehouse.sprocket import Sprocket
from pydantic import Field, create_model, model_validator

from . import generator
from ..contracts.errors import ErrorCode, ShilpaError
from ..contracts.ports import BuiltPart
from ._geom import CatalogParams, port

ROOT = Path(bd_warehouse.__file__).resolve().parent
INCH = 25.4


def _lit(values) -> Any:
    return Literal[tuple(values)]  # type: ignore[valid-type]


def _bad(name: str, message: str) -> ShilpaError:
    return ShilpaError(ErrorCode.INVALID_PARAMETER, f"{name}: {message}", feature_id=name)


def _single(obj, name: str) -> bd.Solid:
    solids = obj.solids()
    if len(solids) == 1:
        return solids[0]
    fused = bd.Solid.fuse(*solids).clean().solids()
    if len(fused) == 1:
        return fused[0]
    return max(fused, key=lambda s: s.volume)  # parts that do not touch (a loose set screw): keep the body


def _inch(text: str) -> float:
    return float(sum(Fraction(p) for p in str(text).split())) * INCH


def _point_on(face) -> bd.Vector:
    """A point inside a planar face (its centre when that lies on material, else a sampled one)."""
    c = face.center()
    if face.is_inside(c):
        return c
    for u in (0.5, 0.25, 0.75, 0.1, 0.9):
        for v in (0.5, 0.25, 0.75, 0.1, 0.9):
            p = face.position_at(u, v)
            if face.is_inside(p):
                return p
    return c


def _face_port(solid, name: str, normal: tuple[float, float, float], label: str, **contract):
    """A face port on the largest planar face whose outward normal is ``normal``."""
    n = bd.Vector(*normal)
    faces = [f for f in solid.faces().filter_by(bd.GeomType.PLANE) if f.normal_at().dot(n) > 0.999]
    if not faces:
        return None
    f = max(faces, key=lambda f: f.area)
    p = _point_on(f)
    x = (1, 0, 0) if abs(normal[0]) < 0.9 else (0, 1, 0)
    return port(name, (round(p.X, 4), round(p.Y, 4), round(p.Z, 4)), normal, x, label=label, kind="face", **contract)


def _part(gen: str, solid, ports: dict, meta: dict, name: str | None = None) -> BuiltPart:
    ports = {k: v for k, v in ports.items() if v is not None}
    nm = re.sub(r"[^a-z0-9]+", "_", (name or gen).lower()).strip("_")
    return BuiltPart(name=nm, solid=solid, ports=ports, source="catalog",
                     meta={"provenance": "bd_warehouse", **meta})


# ---------------------------------------------------------------- pipe


@lru_cache(maxsize=None)
def pipe_table() -> dict[tuple[str, str, str], tuple[float, float]]:
    """(nps, material, identifier) -> (outside diameter, wall), mm."""
    out = {}
    with open(ROOT / "pipe.csv", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            # bd_warehouse tables every pipe in inches (pipe.py scales by IN).
            out[(row["nps"].strip(), row["material"].strip(), row["identifier"].strip())] = (
                float(row["od"]) * INCH, float(row["thickness"]) * INCH)
    return out


def _nps_key(nps: str) -> tuple[float, str]:
    try:
        return float(sum(Fraction(p) for p in nps.split())), nps
    except (ValueError, ZeroDivisionError):
        return 1e9, nps


_PIPES = pipe_table()
_PIPE_NPS = sorted({k[0] for k in _PIPES}, key=_nps_key)
_PIPE_MAT = sorted({k[1] for k in _PIPES})
_PIPE_ID = sorted({k[2] for k in _PIPES})


def _pipe_check(self):
    if (self.nps, self.material, self.identifier) not in _PIPES:
        ids = sorted({k[2] for k in _PIPES if k[0] == self.nps and k[1] == self.material})
        raise ValueError(f"pipe.straight: no {self.material} NPS {self.nps} {self.identifier}; "
                         f"schedules for that size: {', '.join(ids) or 'none'}")
    return self


PipeParams = create_model(
    "PipeParams", __base__=CatalogParams,
    __validators__={"_combo": model_validator(mode="after")(_pipe_check)},
    nps=(_lit(_PIPE_NPS), "2"), material=(_lit(_PIPE_MAT), "steel"), identifier=(_lit(_PIPE_ID), "40"),
    length=(float, Field(500.0, ge=1, le=12000)),
)


def schedule_label(identifier: str) -> str:
    """``40`` -> ``SCH 40``, ``STD`` / ``XS`` stay, copper tube ``K`` / ``L`` / ``M`` -> ``type K``."""
    if identifier in ("K", "L", "M"):
        return f"type {identifier}"
    return identifier if identifier in ("STD", "XS", "XXS") else f"SCH {identifier}"


@generator("pipe.straight", PipeParams, "Straight pipe by NPS, material and schedule (ASME B36.10 / B36.19)",
           "ASME B36.10 / B36.19")
def pipe(p) -> BuiltPart:
    od, wall = _PIPES[(p.nps, p.material, p.identifier)]
    # A straight run is a tube from bd_warehouse's table. (bd_warehouse 0.4's Pipe class passes the table's
    # material names, e.g. "steel", to bd_materials, which no longer knows them, so it cannot be used here.)
    solid = bd.Solid.make_cylinder(od / 2, p.length).cut(bd.Solid.make_cylinder(od / 2 - wall, p.length)).solids()[0]
    c = {"nps": p.nps, "schedule": p.identifier, "od": round(od, 3), "wall": round(wall, 3)}
    ports = {
        "end_a": port("end_a", (0, 0, 0), (0, 0, -1), label="pipe end", kind="face", **c),
        "end_b": port("end_b", (0, 0, p.length), (0, 0, 1), label="pipe end", kind="face", **c),
        "pipe_axis": port("pipe_axis", (0, 0, 0), (0, 0, 1), label="pipe axis (outside diameter)", kind="axis", **c),
    }
    meta = {"standard": "ASME B36.10 / B36.19", "size": f"NPS {p.nps} {p.identifier}",
            "designation": f"NPS {p.nps} {schedule_label(p.identifier)} {p.material} x {p.length:g} mm", **c,
            "length": p.length,
            "id": round(od - 2 * wall, 3)}
    return _part("pipe.straight", solid, ports, meta, f"pipe_{p.nps}_{p.identifier}_{p.length:g}")


# ---------------------------------------------------------------- flanges

NPS = ["1/2", "3/4", "1", "1 1/4", "1 1/2", "2", "2 1/2", "3", "4", "5", "6", "8", "10", "12", "14", "16", "18",
       "20", "22", "24"]
# bd_warehouse 0.4 builds classes 150 and 300 only; class 150 starts at NPS 1, and the weld-neck and
# socket-weld tables stop at NPS 12 and 3 (test_catalog_mechanical checks this against bd_warehouse).
CLASSES = [150, 300]
MAX_NPS = {"flange.weld_neck": "12", "flange.socket_weld": "3"}


def flange_sizes(gen: str, flange_class: int) -> list[str]:
    sizes = NPS[: NPS.index(MAX_NPS[gen]) + 1] if gen in MAX_NPS else list(NPS)
    return [n for n in sizes if not (flange_class == 150 and n in ("1/2", "3/4"))]
FACES = ["Flat", "Raised", "Ring", "Tongue", "Groove", "Male", "Female"]


@lru_cache(maxsize=None)
def drilling(flange_class: int) -> dict[str, dict[str, str]]:
    with open(ROOT / "data_flange" / f"drilling_class_{flange_class}.csv", encoding="utf-8") as fh:
        return {row["NPS"].strip(): row for row in csv.DictReader(fh)}


FLANGES = [
    ("flange.weld_neck", FL.WeldNeckFlange, "Weld-neck flange", True),
    ("flange.slip_on", FL.SlipOnFlange, "Slip-on flange", True),
    ("flange.socket_weld", FL.SocketWeldFlange, "Socket-weld flange", True),
    ("flange.blind", FL.BlindFlange, "Blind flange", True),
    ("flange.lapped", FL.LappedFlange, "Lapped (lap-joint) flange", False),
]


def _make_flange(gen: str, cls, summary: str, has_face: bool):
    extra = {"face_type": (_lit(FACES), "Raised")} if has_face else {}

    def check(self):
        sizes = flange_sizes(gen, self.flange_class)
        if self.nps not in sizes:
            raise ValueError(f"{gen}: class {self.flange_class} covers NPS {sizes[0]} to {sizes[-1]}")
        return self

    params = create_model(f"{gen.replace('.', '_').title().replace('_', '')}Params", __base__=CatalogParams,
                          __validators__={"_size_in_class": model_validator(mode="after")(check)},
                          nps=(_lit(NPS), "2"), flange_class=(_lit(CLASSES), 150), material=(str | None, "steel"),
                          **extra)

    def build(p) -> BuiltPart:
        try:
            f = cls(p.nps, p.flange_class, p.face_type) if has_face else cls(p.nps, p.flange_class)
        except (ValueError, KeyError) as exc:
            raise _bad(gen, f"no ASME B16.5 class {p.flange_class} data for NPS {p.nps} ({exc})") from None
        solid = _single(f, gen)
        bb = solid.bounding_box()
        drill = drilling(p.flange_class).get(p.nps, {})
        pattern = {}
        if drill:
            pattern = {"bolt_circle": float(drill["W"]), "bolt_count": int(drill["n"]),
                       "bolt_hole_d": round(_inch(drill["d"]), 2), "bolt_size_in": drill["C"].strip()}
        face = getattr(p, "face_type", "Flat")
        c = {"standard": "ASME B16.5", "nps": p.nps, "flange_class": p.flange_class, "facing": face, **pattern}
        bore = float(f.id) if getattr(f, "id", None) else None
        ports = {
            "gasket_face": port("gasket_face", (0, 0, round(bb.min.Z, 4)), (0, 0, -1), kind="face",
                                label="gasket face centre; mates an equal flange face to face", **c),
            "pipe_end": port("pipe_end", (0, 0, round(bb.max.Z, 4)), (0, 0, 1), kind="face",
                             label="hub end, where the pipe is welded or passes through", nps=p.nps),
        }
        if bore and gen != "flange.blind":
            ports["bore_axis"] = port("bore_axis", (0, 0, 0), (0, 0, 1), kind="axis", label="flange bore",
                                      bore_d=round(bore, 3), nps=p.nps)
        meta = {"standard": "ASME B16.5", "size": f"NPS {p.nps} class {p.flange_class}",
                "designation": f"ASME B16.5 {summary.lower()} NPS {p.nps} class {p.flange_class}"
                               + (f" {face} face" if has_face else ""),
                "od": float(f.od), "thickness": round(bb.size.Z, 3), **pattern}
        return _part(gen, solid, ports, meta, f"{gen}_{p.nps}_{p.flange_class}")

    generator(gen, params, f"{summary} (ASME B16.5)", "ASME B16.5")(build)


for _g, _c, _s, _f in FLANGES:
    _make_flange(_g, _c, _s, _f)


# ---------------------------------------------------------------- OpenBuilds


def _flat(gen: str, obj, summary: str, meta: dict) -> BuiltPart:
    solid = _single(obj, gen)
    ports = {"bottom": _face_port(solid, "bottom", (0, 0, -1), "bottom face"),
             "top": _face_port(solid, "top", (0, 0, 1), "top face")}
    bb = solid.bounding_box()
    return _part(gen, solid, ports, {"standard": "OpenBuilds", "designation": summary,
                                     "size": f"{bb.size.X:.1f} x {bb.size.Y:.1f} x {bb.size.Z:.1f}", **meta})


def _round(gen: str, obj, summary: str, bore: float | None, meta: dict, axis_label: str = "bore axis",
           key: str = "bore_d") -> BuiltPart:
    solid = _single(obj, gen)
    bb = solid.bounding_box()
    ports = {"bottom": _face_port(solid, "bottom", (0, 0, -1), "end face"),
             "top": _face_port(solid, "top", (0, 0, 1), "end face")}
    axis_c = {key: bore} if bore else {}
    ports["axis"] = port("axis", (0, 0, round(bb.min.Z, 4)), (0, 0, 1), label=axis_label, kind="axis", **axis_c)
    return _part(gen, solid, ports, {"standard": "OpenBuilds", "designation": summary,
                                     "size": f"{bb.size.X:.1f} x {bb.size.Z:.1f}", **axis_c, **meta})


def _fixed(gen: str, cls, summary: str, material: str = "aluminium"):
    params = create_model(f"{gen.replace('.', '_').title().replace('_', '')}Params", __base__=CatalogParams,
                          material=(str | None, material))
    generator(gen, params, summary, "OpenBuilds")(lambda p: _flat(gen, cls(), summary, {}))


_fixed("openbuilds.cbeam_gantry_plate", OB.CBeamGantryPlate, "C-beam gantry plate")
_fixed("openbuilds.cbeam_gantry_plate_xl", OB.CBeamGantryPlateXLarge, "C-beam gantry plate, extra large")
_fixed("openbuilds.cbeam_end_mount", OB.CBeamEndMount, "C-beam end mount (motor and lead-screw plate)")
_fixed("openbuilds.cbeam_riser_plate", OB.CBeamRiserPlate, "C-beam riser plate")
_fixed("openbuilds.spacer_block", OB.SpacerBlock, "Spacer block")
_fixed("openbuilds.anti_backlash_nut_block", OB.AcmeAntiBacklashNutBlock8mm, "Anti-backlash nut block, 8 mm lead screw",
       "acetal")


class LBracketParams(CatalogParams):
    material: str | None = "aluminium"


@generator("openbuilds.l_bracket", LBracketParams, "90 deg L-bracket for 20-series extrusion", "OpenBuilds")
def l_bracket(p) -> BuiltPart:
    solid = _single(OB.LBracket(), "openbuilds.l_bracket")
    ports = {"leg_x": _face_port(solid, "leg_x", (-1, 0, 0), "outer face of the vertical leg"),
             "leg_z": _face_port(solid, "leg_z", (0, 0, -1), "outer face of the horizontal leg")}
    return _part("openbuilds.l_bracket", solid, ports, {"standard": "OpenBuilds", "designation": "L-bracket 20 mm",
                                                         "size": "20 x 20"})


class CBeamParams(CatalogParams):
    length: float = Field(500.0, ge=10, le=3000)
    material: str | None = "aluminium"


@generator("openbuilds.c_beam_rail", CBeamParams, "C-beam linear rail (OpenBuilds 40 x 80 profile)", "OpenBuilds")
def c_beam_rail(p) -> BuiltPart:
    solid = _single(OB.CBeamLinearRail(p.length), "openbuilds.c_beam_rail")
    bb = solid.bounding_box()
    ports = {
        "end_a": _face_port(solid, "end_a", (0, 0, -1), "cut end"),
        "end_b": _face_port(solid, "end_b", (0, 0, 1), "cut end"),
        "back": _face_port(solid, "back", (-1, 0, 0), "flat back face"),
    }
    return _part("openbuilds.c_beam_rail", solid, ports,
                 {"standard": "OpenBuilds", "designation": f"C-beam x {p.length:g} mm", "length": p.length,
                  "size": f"{bb.size.X:.0f} x {bb.size.Y:.0f} x {p.length:g}"}, f"c_beam_{p.length:g}")


class SpacerParams(CatalogParams):
    length: Literal["3mm", "1/8in", "6mm", "1/4in", "9mm", "10mm", "13.2mm", "20mm", "35mm", "1-1/2in", "40mm"] = "6mm"
    material: str | None = "aluminium"


@generator("openbuilds.aluminium_spacer", SpacerParams, "Aluminium spacer for M5 screws", "OpenBuilds")
def aluminium_spacer(p) -> BuiltPart:
    return _round("openbuilds.aluminium_spacer", OB.AluminumSpacer(p.length), f"Aluminium spacer {p.length}", 5.2,
                  {"length": p.length, "for": "M5"})


class EccParams(CatalogParams):
    cam_height: Literal["6mm", "1/4in"] = "6mm"
    material: str | None = "aluminium"


@generator("openbuilds.eccentric_spacer", EccParams, "Eccentric spacer (V-wheel preload)", "OpenBuilds")
def eccentric_spacer(p) -> BuiltPart:
    solid = _single(OB.EccentricSpacer(p.cam_height), "openbuilds.eccentric_spacer")
    ports = {"bottom": _face_port(solid, "bottom", (0, 0, -1), "hex flange underside"),
             "top": _face_port(solid, "top", (0, 0, 1), "cam end")}
    return _part("openbuilds.eccentric_spacer", solid, ports,
                 {"standard": "OpenBuilds", "designation": f"Eccentric spacer {p.cam_height}", "size": p.cam_height})


class ShimParams(CatalogParams):
    shim_type: Literal["MiniVWheel", "10x5x1", "12x8x1", "SlotWasher", "FlatWasher"] = "FlatWasher"
    material: str | None = "steel"


@generator("openbuilds.shim_washer", ShimParams, "Precision shim / washer", "OpenBuilds")
def shim_washer(p) -> BuiltPart:
    return _flat("openbuilds.shim_washer", OB.ShimWasher(p.shim_type), f"Shim {p.shim_type}", {})


class CouplerParams(CatalogParams):
    shaft_diameter: Literal["8mm", "1/4in"] = "8mm"
    material: str | None = "aluminium"


@generator("openbuilds.flexible_coupler", CouplerParams, "Flexible shaft coupler, 5 mm motor shaft to lead screw",
           "OpenBuilds")
def flexible_coupler(p) -> BuiltPart:
    d = 8.0 if p.shaft_diameter == "8mm" else 6.35
    return _round("openbuilds.flexible_coupler", OB.FlexibleCoupler(p.shaft_diameter),
                  f"Flexible coupler 5 mm to {p.shaft_diameter}", None, {"motor_shaft_d": 5.0, "screw_shaft_d": d},
                  axis_label="coupler axis")


class CollarParams(CatalogParams):
    inside_diameter: Literal["5mm", "8mm", "1/4in"] = "8mm"
    material: str | None = "aluminium"


@generator("openbuilds.lock_collar", CollarParams, "Lock collar (set screw not modelled)", "OpenBuilds")
def lock_collar(p) -> BuiltPart:
    d = {"5mm": 5.0, "8mm": 8.0, "1/4in": 6.35}[p.inside_diameter]
    return _round("openbuilds.lock_collar", OB.LockCollar(p.inside_diameter), f"Lock collar {p.inside_diameter}", d,
                  {"set_screw": "M4 (not modelled)"})


class StepperParams(CatalogParams):
    motor_type: Literal["Nema17", "Nema23", "Nema23HighTorque"] = "Nema17"
    material: str | None = None


NEMA = {"Nema17": (42.3, 31.0, "M3", 5.0, 22.0), "Nema23": (56.4, 47.14, "M5", 6.35, 38.1),
        "Nema23HighTorque": (56.4, 47.14, "M5", 6.35, 38.1)}  # frame, bolt square, bolt, shaft, pilot (NEMA ICS 16)


@generator("openbuilds.stepper_motor", StepperParams, "NEMA 17 / 23 stepper motor (envelope)", "NEMA ICS 16")
def stepper_motor(p) -> BuiltPart:
    frame, bolts, bolt, shaft, pilot = NEMA[p.motor_type]
    solid = _single(OB.StepperMotor(p.motor_type), "openbuilds.stepper_motor")
    bb = solid.bounding_box()
    c = {"frame_nominal": frame, "bolt_square": bolts, "bolt": bolt, "pilot_d": pilot}
    ports = {
        "mount_face": _face_port(solid, "mount_face", (0, 0, 1), "mounting face (shaft side)", **c),
        "shaft_axis": port("shaft_axis", (0, 0, 0), (0, 0, 1), label="output shaft", kind="axis", shaft_d=shaft),
    }
    return _part("openbuilds.stepper_motor", solid, ports,
                 {"standard": "NEMA ICS 16", "designation": p.motor_type.replace("Nema", "NEMA "),
                  "size": f"{frame} mm frame x {bb.size.Z:.0f}", **c, "shaft_d": shaft}, p.motor_type)


class LeadScrewParams(CatalogParams):
    length: float = Field(300.0, ge=20, le=2000)
    material: str | None = "stainless"


@generator("openbuilds.lead_screw", LeadScrewParams, "Metric lead screw Tr8x8 (thread not modelled)", "DIN 103")
def lead_screw(p) -> BuiltPart:
    return _round("openbuilds.lead_screw", OB.MetricLeadScrew(p.length, simple=True), f"Tr8x8 x {p.length:g} mm",
                  None, {"thread": "Tr8x8", "length": p.length, "lead": 8.0}, axis_label="screw axis")


class WheelParams(CatalogParams):
    material: str | None = "polyurethane"


@generator("openbuilds.xtreme_v_wheel", WheelParams, "Xtreme solid V-wheel (takes two 625 bearings)", "OpenBuilds")
def xtreme_v_wheel(p) -> BuiltPart:
    solid = _single(OB.XtremeSolidVWheel(), "openbuilds.xtreme_v_wheel")
    ports = {"bore_axis": port("bore_axis", (0, 0, 0), (0, 0, 1), label="bearing bore", kind="axis", bore_d=16.0,
                               fit="bearing"),
             "face_a": _face_port(solid, "face_a", (0, 0, -1), "side face"),
             "face_b": _face_port(solid, "face_b", (0, 0, 1), "side face")}
    return _part("openbuilds.xtreme_v_wheel", solid, ports,
                 {"standard": "OpenBuilds", "designation": "Xtreme solid V-wheel", "size": "24 x 10.2",
                  "bearings": "2x 625"})


# ---------------------------------------------------------------- drives

# ANSI B29.1 roller chain: number -> (pitch, roller diameter, sprocket tooth width), mm
CHAINS = {"25": (6.35, 3.30, 2.8), "35": (9.525, 5.08, 4.3), "40": (12.7, 7.92, 7.2), "41": (12.7, 7.77, 5.8),
          "50": (15.875, 10.16, 8.7), "60": (19.05, 11.91, 11.7), "80": (25.4, 15.88, 14.6)}


class SprocketParams(CatalogParams):
    chain: Literal["25", "35", "40", "41", "50", "60", "80"] = "40"
    teeth: int = Field(20, ge=9, le=120)
    bore_d: float | None = Field(None, gt=0, description="bore, mm; empty picks about a third of the root diameter")
    material: str | None = "steel"


@generator("drive.sprocket", SprocketParams, "Roller-chain sprocket, ANSI 25-80 (plate, no hub)", "ANSI B29.1")
def sprocket(p) -> BuiltPart:
    pitch, roller, width = CHAINS[p.chain]
    pd = pitch / math.sin(math.pi / p.teeth)
    root = pd - roller
    bore = p.bore_d if p.bore_d is not None else max(3.0, round(root / 3))
    if bore > root - 2 * roller:
        raise _bad("drive.sprocket", f"bore {bore:g} mm leaves no web under a {root:.1f} mm root diameter")
    s = Sprocket(p.teeth, chain_pitch=pitch, roller_diameter=roller, thickness=width, bore_diameter=bore)
    solid = _single(s, "drive.sprocket")
    c = {"chain": f"ANSI {p.chain}", "chain_pitch": pitch, "roller_d": roller}
    ports = {
        "mesh": port("mesh", (0, 0, 0), (0, 0, 1), label="sprocket axis; chain plane at z = 0", kind="axis",
                     gear_set="chain", **c),
        "bore_axis": port("bore_axis", (0, 0, 0), (0, 0, 1), label="bore, fits a shaft", kind="axis", bore_d=bore,
                          fit="shaft"),
        "face_a": port("face_a", (0, 0, -width / 2), (0, 0, -1), label="side face", kind="face"),
        "face_b": port("face_b", (0, 0, width / 2), (0, 0, 1), label="side face", kind="face"),
    }
    return _part("drive.sprocket", solid, ports,
                 {"standard": "ANSI B29.1", "designation": f"ANSI {p.chain} sprocket {p.teeth}T",
                  "size": f"{p.teeth}T", **c, "teeth": p.teeth, "pitch_d": round(pd, 3), "bore_d": bore},
                 f"sprocket_{p.chain}_{p.teeth}")


class WormParams(CatalogParams):
    module: Literal[0.5, 0.8, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0] = 2.0
    starts: int = Field(1, ge=1, le=4)
    diametral_quotient: float = Field(10.0, ge=6, le=20, description="q = pitch diameter / module")
    length: float = Field(40.0, gt=0, le=500)
    hand: Literal["right", "left"] = "right"
    material: str | None = "steel"


def _worm_mesh(p) -> dict:
    return {"kind": "axis", "gear_set": "worm", "module": p.module, "starts": p.starts,
            "diametral_quotient": p.diametral_quotient, "pressure_angle": 20.0, "hand": p.hand}


@generator("drive.worm", WormParams, "Worm (ZI flank), mates a worm wheel", "ISO 54 / DIN 3975")
def worm(p) -> BuiltPart:
    w = G.Worm(p.module, p.starts, p.diametral_quotient, p.length, hand=p.hand)
    solid = _single(w, "drive.worm")
    ports = {"mesh": port("mesh", (0, 0, 0), (0, 0, 1), label="worm axis", **_worm_mesh(p)),
             "end_a": port("end_a", (0, 0, -p.length / 2), (0, 0, -1), label="worm end", kind="point"),
             "end_b": port("end_b", (0, 0, p.length / 2), (0, 0, 1), label="worm end", kind="point")}
    return _part("drive.worm", solid, ports,
                 {"standard": "DIN 3975", "designation": f"worm m{p.module:g} {p.starts}-start q{p.diametral_quotient:g}"
                  f" {p.hand}", "size": f"m{p.module:g} x {p.length:g}", "pitch_d": round(2 * w.pitch_radius, 3),
                  "tip_d": round(2 * w.addendum_radius, 3), "lead_angle": round(w.lead_angle, 3)},
                 f"worm_m{p.module:g}_{p.starts}")


class WormWheelParams(CatalogParams):
    module: Literal[0.5, 0.8, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0] = 2.0
    teeth: int = Field(30, ge=17, le=120)
    face_width: float = Field(15.0, gt=0, le=200)
    starts: int = Field(1, ge=1, le=4)
    diametral_quotient: float = Field(10.0, ge=6, le=20)
    hand: Literal["right", "left"] = "right"
    bore_d: float | None = Field(None, gt=0, description="bore, mm; empty picks about a third of the root diameter")
    material: str | None = "bronze"


@generator("drive.worm_wheel", WormWheelParams, "Worm wheel, mates a worm (ratio = teeth / starts)",
           "ISO 54 / DIN 3975")
def worm_wheel(p) -> BuiltPart:
    w = G.WormWheel(p.module, p.teeth, p.face_width, starts=p.starts, diametral_quotient=p.diametral_quotient,
                    hand=p.hand)
    solid = _single(w, "drive.worm_wheel")
    root = 2 * w.root_radius
    bore = p.bore_d if p.bore_d is not None else max(3.0, round(root / 3))
    if bore > root - 2 * p.module:
        raise _bad("drive.worm_wheel", f"bore {bore:g} mm leaves no web under a {root:.1f} mm root diameter")
    h = p.face_width
    solid = solid.cut(bd.Solid.make_cylinder(bore / 2, h + 2, bd.Plane.XY.offset(-h / 2 - 1))).solids()[0]
    ports = {"mesh": port("mesh", (0, 0, 0), (0, 0, 1), label="wheel axis", **_worm_mesh(p)),
             "bore_axis": port("bore_axis", (0, 0, 0), (0, 0, 1), label="bore, fits a shaft", kind="axis", bore_d=bore,
                               fit="shaft"),
             "face_a": port("face_a", (0, 0, -h / 2), (0, 0, -1), label="side face", kind="face"),
             "face_b": port("face_b", (0, 0, h / 2), (0, 0, 1), label="side face", kind="face")}
    centre = round(p.module * (p.diametral_quotient + p.teeth) / 2, 3)
    return _part("drive.worm_wheel", solid, ports,
                 {"standard": "DIN 3975", "designation": f"worm wheel m{p.module:g} z{p.teeth} ({p.starts}-start, "
                  f"ratio {p.teeth / p.starts:g}:1)", "size": f"m{p.module:g} z{p.teeth}", "teeth": p.teeth,
                  "ratio": p.teeth / p.starts, "pitch_d": round(2 * w.pitch_radius, 3), "bore_d": bore,
                  "centre_distance": centre}, f"worm_wheel_m{p.module:g}_z{p.teeth}")
