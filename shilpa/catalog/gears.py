"""Involute gears built with py_gearworks (Apache-2.0, GarryBGoode/py_gearworks).

Generators: ``gear.spur``, ``gear.helical``, ``gear.ring`` (internal spur),
``gear.bevel`` and ``gear.rack``. Teeth are true involutes (undercut modelled
for external gears), so meshing gears placed with ``mesh_layout`` interleave
without overlap and can be interference-checked as real solids.

Placement conventions:

* Round gears: axis along Z, centred so the faces sit at z = +-face_width/2,
  except the bevel gear, whose back face sits at z = 0 with teeth towards +Z.
* ``mesh`` (axis port on the gear axis, x along +X) carries only what two
  meshing gears must share: ``gear_set`` (parallel or bevel), module,
  pressure angle, helix angle, and for helical gears ``mesh_hand``, which
  must differ between the pair. A fixed, aligned mate from one gear's
  ``mesh`` to another's with ``xy`` and ``angle`` from ``mesh_layout`` places
  the pair in mesh, and the assembly contract check rejects a pair that
  cannot mesh.
* ``bore_axis`` runs down the bore (``bore_d``); ``face_a`` / ``face_b`` are
  the -Z / +Z faces. The ring gear has ``outer`` (its outside diameter)
  instead of a bore.
* Rack: teeth along +Y, tooth tips towards +X, pitch line at x = 0, length
  centred on y = 0, face width centred on z = 0; ``back`` is the -X mounting
  face and carries the rack's meshing data.

Everything else (teeth, pitch / tip / root diameters, face width) is in
``meta``, so two different gears can still mate face to face.
"""

from __future__ import annotations

import math
from typing import Literal

import build123d as bd
import numpy as np
import py_gearworks as gw
from pydantic import Field, model_validator

from . import generator
from ..contracts.errors import ErrorCode, ShilpaError
from ..contracts.ports import BuiltPart
from ._geom import CatalogParams, port

# ISO 54 first-choice modules (mm).
Module = Literal[0.5, 0.8, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]
PressureAngle = Literal[14.5, 20.0, 25.0]


class _GearParams(CatalogParams):
    teeth: int = Field(20, ge=10, le=300)
    module: Module = 2.0
    face_width: float = Field(10.0, gt=0, le=500)
    pressure_angle: PressureAngle = 20.0
    profile_shift: float = Field(0.0, ge=-0.5, le=1.0)

    @property
    def pitch_d(self) -> float:
        return self.module * self.teeth


class _BoredParams(_GearParams):
    bore_d: float | None = Field(None, gt=0)  # None picks about a quarter of the pitch diameter

    @property
    def root_d(self) -> float:
        return self.pitch_d - 2 * self.module * (1.2 - self.profile_shift)

    def bore(self) -> float:
        limit = self.root_d - 2 * self.module  # keep a web of at least one module under the teeth
        if self.bore_d is None:
            return float(max(1.0, min(round(self.pitch_d / 4), math.floor(limit))))
        return self.bore_d

    @model_validator(mode="after")
    def _bore_fits(self):
        limit = self.root_d - 2 * self.module
        if self.bore() > limit:
            raise ValueError(f"bore {self.bore():g} mm leaves less than one module of web under the teeth "
                             f"(max {limit:g} mm for root diameter {self.root_d:g} mm)")
        return self


class SpurParams(_BoredParams):
    pass


class HelicalParams(_BoredParams):
    helix_angle: float = Field(20.0, ge=5, le=45)  # degrees at the pitch cylinder
    hand: Literal["right", "left"] = "right"
    herringbone: bool = False


class RingParams(_GearParams):
    teeth: int = Field(60, ge=20, le=300)
    rim: float = Field(2.5, ge=1.0, le=10.0)  # outside radius beyond the pitch circle, in modules


class BevelParams(_BoredParams):
    mate_teeth: int = Field(20, ge=10, le=300)  # tooth count of the partner on a 90 deg shaft angle
    face_width: float = Field(8.0, gt=0, le=200)


class RackParams(CatalogParams):
    teeth: int = Field(20, ge=2, le=500)
    module: Module = 2.0
    face_width: float = Field(10.0, gt=0, le=500)
    pressure_angle: PressureAngle = 20.0
    backing: float = Field(8.0, gt=0, le=200)  # solid bar depth behind the tooth roots


# ---------------------------------------------------------------- py_gearworks objects


def _common(p: _GearParams) -> dict:
    return {"number_of_teeth": p.teeth, "module": p.module, "height": p.face_width,
            "pressure_angle": math.radians(p.pressure_angle), "profile_shift": p.profile_shift}


def _helix_rad(p: HelicalParams) -> float:
    return math.radians(p.helix_angle) * (1 if p.hand == "right" else -1)


def gw_gear(generator_name: str, params: dict):
    """The py_gearworks object for a gear generator and its (validated) params."""
    if generator_name == "gear.spur":
        return gw.SpurGear(**_common(SpurParams.model_validate(params)), z_anchor=0.5)
    if generator_name == "gear.helical":
        p = HelicalParams.model_validate(params)
        return gw.HelicalGear(**_common(p), helix_angle=_helix_rad(p), herringbone=p.herringbone, z_anchor=0.5)
    if generator_name == "gear.ring":
        p = RingParams.model_validate(params)
        return gw.SpurRingGear(**_common(p), outside_ring_coefficient=p.rim, z_anchor=0.5)
    raise ShilpaError(ErrorCode.UNSUPPORTED_OPERATION, f"{generator_name} is not a parallel-axis round gear")


def _solid(part) -> bd.Solid:
    solids = part.solids()
    if len(solids) != 1:
        raise ShilpaError(ErrorCode.VALIDATION_FAILED, f"gear produced {len(solids)} solids")
    return solids[0]


def _data(p: _GearParams, g, **extra) -> dict:
    """Everything about one gear, for ``meta``."""
    return {"module": p.module, "teeth": p.teeth, "pressure_angle": p.pressure_angle, "profile_shift": p.profile_shift,
            "pitch_d": round(2 * g.pitch_radius, 4), "tip_d": round(2 * g.addendum_radius, 4),
            "root_d": round(2 * g.dedendum_radius, 4), "face_width": p.face_width, **extra}


def _mesh(p, gear_set: str = "parallel", helix_angle: float = 0.0, hand: str | None = None) -> dict:
    """What a meshing partner must share (``mesh_hand`` must differ)."""
    c = {"kind": "axis", "gear_set": gear_set, "module": p.module, "pressure_angle": p.pressure_angle,
         "helix_angle": helix_angle}
    if hand:
        c["mesh_hand"] = hand
    return c


def _bored(solid: bd.Solid, bore: float, z0: float, z1: float) -> bd.Solid:
    cut = bd.Solid.make_cylinder(bore / 2, z1 - z0 + 2, bd.Plane.XY.offset(z0 - 1))
    return solid.cut(cut).solids()[0]


def _round_gear(name: str, p: _BoredParams, g, standard: str, mesh: dict, **extra) -> BuiltPart:
    bore = p.bore()
    h = p.face_width / 2
    solid = _bored(_solid(g.build_part()), bore, -h, h)
    c = _data(p, g, **extra)
    ports = {
        "mesh": port("mesh", (0, 0, 0), (0, 0, 1), (1, 0, 0), label="gear axis, meshes with a partner gear", **mesh),
        "bore_axis": port("bore_axis", (0, 0, 0), (0, 0, 1), label="bore, fits a shaft", bore_d=bore, fit="shaft"),
        "face_a": port("face_a", (0, 0, -h), (0, 0, -1), label="side face"),
        "face_b": port("face_b", (0, 0, h), (0, 0, 1), label="side face"),
    }
    meta = {"standard": standard, "size": f"m{p.module:g} z{p.teeth}", "designation": name, "bore_d": bore,
            "provenance": "py_gearworks", **c}
    return BuiltPart(name=name.replace(" ", "_").replace(".", "_"), solid=solid, ports=ports, source="catalog",
                     meta=meta)


@generator("gear.spur", SpurParams, "Involute spur gear with a plain bore", "ISO 53 / ISO 54")
def spur_gear(p: SpurParams) -> BuiltPart:
    g = gw_gear("gear.spur", p.model_dump())
    return _round_gear(f"spur m{p.module:g} z{p.teeth}", p, g, "ISO 53 / ISO 54", _mesh(p),
                       helix_angle=0.0, hand="none")


@generator("gear.helical", HelicalParams, "Involute helical (or herringbone) gear with a plain bore",
           "ISO 53 / ISO 54")
def helical_gear(p: HelicalParams) -> BuiltPart:
    g = gw_gear("gear.helical", p.model_dump())
    kind = "herringbone" if p.herringbone else "helical"
    return _round_gear(f"{kind} m{p.module:g} z{p.teeth} {p.hand[0].upper()}H", p, g, "ISO 53 / ISO 54",
                       _mesh(p, helix_angle=p.helix_angle, hand=p.hand),
                       helix_angle=p.helix_angle, hand=p.hand, herringbone=p.herringbone)


@generator("gear.ring", RingParams, "Internal (ring) spur gear for planetary sets", "ISO 53 / ISO 54")
def ring_gear(p: RingParams) -> BuiltPart:
    g = gw_gear("gear.ring", p.model_dump())
    solid = _solid(g.build_part())
    h = p.face_width / 2
    od = round(solid.bounding_box().size.X, 4)
    c = _data(p, g, helix_angle=0.0, hand="none", internal=True)
    ports = {
        "mesh": port("mesh", (0, 0, 0), (0, 0, 1), (1, 0, 0), label="gear axis, meshes with a pinion inside",
                     **_mesh(p)),
        "outer": port("outer", (0, 0, 0), (0, 0, 1), label="outside diameter, fits a housing", od=od, fit="housing"),
        "face_a": port("face_a", (0, 0, -h), (0, 0, -1), label="side face"),
        "face_b": port("face_b", (0, 0, h), (0, 0, 1), label="side face"),
    }
    meta = {"standard": "ISO 53 / ISO 54", "size": f"m{p.module:g} z{p.teeth} internal",
            "designation": f"ring m{p.module:g} z{p.teeth}", "od": od, "provenance": "py_gearworks", **c}
    return BuiltPart(name=f"ring_m{p.module:g}_z{p.teeth}".replace(".", "_"), solid=solid, ports=ports,
                     source="catalog", meta=meta)


@generator("gear.bevel", BevelParams, "Straight bevel gear for a 90 deg shaft angle", "ISO 23509")
def bevel_gear(p: BevelParams) -> BuiltPart:
    cone = math.atan2(p.teeth, p.mate_teeth)  # pitch cone half-angle for a 90 deg pair
    g = gw.BevelGear(**_common(p), cone_angle=2 * cone)
    solid = _solid(g.build_part())
    planes = [f for f in solid.faces().filter_by(bd.GeomType.PLANE) if abs(f.normal_at().Z) > 0.999]
    z_back = min(f.center().Z for f in planes if f.normal_at().Z < 0)
    z_front = max(f.center().Z for f in planes if f.normal_at().Z > 0)
    solid = solid.moved(bd.Location((0, 0, -z_back)))
    top = z_front - z_back
    bore = p.bore()
    solid = _bored(solid, bore, 0, top)
    apex_z = round(float(g.center_spherical[2]) - z_back, 4) if hasattr(g, "center_spherical") else None
    c = _data(p, g, helix_angle=0.0, hand="none", mate_teeth=p.mate_teeth,
              pitch_cone_angle=round(math.degrees(cone), 4), shaft_angle=90.0, apex_z=apex_z)
    ports = {
        "mesh": port("mesh", (0, 0, 0), (0, 0, 1), (1, 0, 0), label="gear axis, meshes with its bevel partner",
                     **_mesh(p, gear_set="bevel"), shaft_angle=90.0),
        "bore_axis": port("bore_axis", (0, 0, 0), (0, 0, 1), label="bore, fits a shaft", bore_d=bore, fit="shaft"),
        "back_face": port("back_face", (0, 0, 0), (0, 0, -1), label="back face, locates on a shoulder"),
        "front_face": port("front_face", (0, 0, top), (0, 0, 1), label="front face"),
    }
    meta = {"standard": "ISO 23509", "size": f"m{p.module:g} z{p.teeth}/{p.mate_teeth}",
            "designation": f"bevel m{p.module:g} z{p.teeth} (mates z{p.mate_teeth})", "bore_d": bore,
            "provenance": "py_gearworks", **c}
    return BuiltPart(name=f"bevel_m{p.module:g}_z{p.teeth}".replace(".", "_"), solid=solid, ports=ports,
                     source="catalog", meta=meta)


@generator("gear.rack", RackParams, "Straight involute rack with a backing bar", "ISO 53 / ISO 54")
def rack(p: RackParams) -> BuiltPart:
    r = gw.InvoluteRack(number_of_teeth=p.teeth, module=p.module, height=p.face_width,
                        pressure_angle=math.radians(p.pressure_angle))
    teeth = _solid(r.build_part())
    bb = teeth.bounding_box()
    root_x = bb.min.X
    bar = bd.Solid.make_box(p.backing + 0.2 * p.module, bb.size.Y, bb.size.Z,
                            bd.Plane.XY.offset(bb.min.Z).move(bd.Location((root_x - p.backing, bb.min.Y, 0))))
    solid = teeth.fuse(bar).clean().solids()
    if len(solids := solid) != 1:
        raise ShilpaError(ErrorCode.VALIDATION_FAILED, f"rack produced {len(solids)} solids")
    solid = solids[0].moved(bd.Location((0, -(bb.min.Y + bb.max.Y) / 2, -(bb.min.Z + bb.max.Z) / 2)))
    length = round(bb.size.Y, 4)
    back_x = root_x - p.backing
    c = {"module": p.module, "teeth": p.teeth, "pressure_angle": p.pressure_angle, "pitch_line_x": 0.0,
         "tip_x": round(bb.max.X, 4), "root_x": round(root_x, 4), "length": length, "face_width": p.face_width,
         "linear_pitch": round(math.pi * p.module, 4)}
    mesh = {k: v for k, v in _mesh(p).items() if k != "kind"}
    ports = {
        "back": port("back", (back_x, 0, 0), (-1, 0, 0), (0, 1, 0), label="back mounting face, pitch line at x = 0",
                     pitch_line_offset=round(-back_x, 4), **mesh),
        "end_a": port("end_a", (back_x / 2, -length / 2, 0), (0, -1, 0), label="end face", kind="face"),
        "end_b": port("end_b", (back_x / 2, length / 2, 0), (0, 1, 0), label="end face", kind="face"),
    }
    meta = {"standard": "ISO 53 / ISO 54", "size": f"m{p.module:g} x {length:g}",
            "designation": f"rack m{p.module:g} {p.teeth}T", "provenance": "py_gearworks", **c}
    return BuiltPart(name=f"rack_m{p.module:g}_{p.teeth}t".replace(".", "_"), solid=solid, ports=ports,
                     source="catalog", meta=meta)


# ---------------------------------------------------------------- meshing


def center_distance(module: float, teeth_a: int, teeth_b: int, internal: bool = False) -> float:
    """Standard (unshifted) centre distance of a parallel-axis pair; ``internal`` for a gear inside a ring."""
    return module * (abs(teeth_b - teeth_a) if internal else teeth_a + teeth_b) / 2


def mesh_layout(a: BuiltPart, b: BuiltPart, direction: tuple[float, float] = (1.0, 0.0)) -> dict:
    """Where to put gear ``b`` so it meshes with ``a`` (both catalog gears, ``a`` at the origin, unrotated).

    Returns ``offset`` (b's centre in a's frame), ``rotation_deg`` (b about its own +Z) and ``center_distance``.
    Supports spur/helical pairs and a spur gear inside a ring gear. Raises ``INVALID_PARAMETER`` for pairs
    that cannot mesh (module, pressure angle or helix hand mismatch).
    """
    return mesh_layout_params(a.meta.get("generator"), a.meta.get("params", {}), b.meta.get("generator"),
                              b.meta.get("params", {}), direction)


PARAMS = {"gear.spur": SpurParams, "gear.helical": HelicalParams, "gear.ring": RingParams}


def mesh_layout_params(ga: str, pa: dict, gb: str, pb: dict, direction: tuple[float, float] = (1.0, 0.0)) -> dict:
    """``mesh_layout`` from generator names and params alone (no solids built); params get their defaults."""
    if ga not in PARAMS or gb not in PARAMS:
        raise ShilpaError(ErrorCode.UNSUPPORTED_OPERATION, f"mesh_layout needs two round gears, got {ga} and {gb}")
    pa, pb = PARAMS[ga].model_validate(pa).model_dump(), PARAMS[gb].model_validate(pb).model_dump()
    for key in ("module", "pressure_angle"):
        if pa[key] != pb[key]:
            raise ShilpaError(ErrorCode.INVALID_PARAMETER, f"gears cannot mesh: {key} {pa[key]} vs {pb[key]}")
    if (ga == "gear.helical") != (gb == "gear.helical"):
        raise ShilpaError(ErrorCode.INVALID_PARAMETER, "a helical gear only meshes with another helical gear")
    if ga == gb == "gear.helical":
        if pa["helix_angle"] != pb["helix_angle"] or pa["hand"] == pb["hand"]:
            raise ShilpaError(ErrorCode.INVALID_PARAMETER,
                              "helical pair needs equal helix angles and opposite hands")
    if ga == gb == "gear.ring":
        raise ShilpaError(ErrorCode.INVALID_PARAMETER, "two ring gears cannot mesh")
    obj_a, obj_b = gw_gear(ga, pa), gw_gear(gb, pb)
    d = np.array([direction[0], direction[1], 0.0], dtype=float)
    obj_b.mesh_to(obj_a, target_dir=d / np.linalg.norm(d))
    cx, cy = float(obj_b.center[0]), float(obj_b.center[1])
    return {"offset": (round(cx, 6), round(cy, 6), 0.0), "rotation_deg": math.degrees(float(obj_b.angle)),
            "center_distance": round(math.hypot(cx, cy), 6)}
