"""Single-stage spur reduction gearbox template ``gearbox.spur_single_v1``.

Same three deterministic steps as the bicycle:

1. ``skeleton_from_choices``: the duty (ratio, input torque and speed, bearing
   life, gear material) becomes a skeleton with provenance.
2. ``derive``: sizes everything not fixed by the user or the router, in order:

   * teeth: the smallest pinion (17 to 30 teeth, no undercut at 20 deg) whose
     ratio is within 1 % of the request, preferring a hunting-tooth pair
     (no common factor, so every pinion tooth meets every gear tooth);
   * module: the smallest ISO 54 module whose pinion passes Lewis bending at
     the standard face width b = 10 m, with the Barth velocity factor
     Kv = (6.1 + V) / 6.1 for cut teeth (V pitch-line speed, m/s)::

         sigma_b = Kv Ft / (b m Y)        Ft = 2000 T / (m z)    [N, mm, MPa]

   * shafts: solid round shafts in torsion, tau = 16 T / (pi d^3) <= 40 MPa
     (a low allowable that leaves room for the bending and keyway stresses not
     modelled here), rounded up to the next deep-groove bearing bore;
   * bearings: 60xx at that bore (the router moves to 62xx when life is short);
   * housing: two side plates as thick as the wider bearing plus 2 mm, four
     M6 standoffs above and below the gear envelope, eight ISO 4762 screws.

   Contact stress (Hertz, as in Shigley / AGMA without the rating factors) and
   bearing life (L10) are not sized for: they are checked, and the rollback
   router repairs them (wider face, then a bigger module; 62xx bearings, then a
   bigger shaft), which is what shows up as ``repaired`` in the report.
3. ``spec_from_skeleton``: product tree and the ``AssemblySpec``.

Layout (world = side plate A's frame): plate A in z [0, t] is grounded, plate
B sits a gap above it; the input shaft runs on x = -a/2 and sticks out below
plate A, the output shaft on x = +a/2 sticks out above plate B; both gears
are centred in the gap. The gear's rotation about its shaft comes from
``mesh_layout`` so the teeth interleave. Each shaft is a revolute joint in
its bearings (DOF 2: the mesh coupling is checked, not modelled as a joint).

Allowable stresses are textbook approximations including a safety margin:
steel = through-hardened about 200 HB (e.g. C45): bending 140 MPa, contact
520 MPa; hardened_steel = case-hardened about 58 HRC: bending 300 MPa,
contact 1100 MPa. They are design starting points, not a gear rating.
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ...catalog.bearings import DEEP_GROOVE
from ...contracts.assembly import AssemblySpec
from ...contracts.product import ProductNode, ProductSpec, Requirements, SkeletonParam

TEMPLATE_ID = "gearbox.spur_single_v1"
MODULES = (1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0)  # ISO 54 first choice from 1 mm
FACE_FACTOR = 10.0  # standard face width b = 10 m
MAX_FACE_FACTOR = 16.0  # widest face the router uses before going up a module
BORES = {10: ("6000", "6200"), 12: ("6001", "6201"), 15: ("6002", "6202"), 17: ("6003", "6203"),
         20: ("6004", "6204"), 25: ("6005", "6205"), 30: ("6006", "6206"), 35: ("6007", "6207"),
         40: ("6008", "6208")}
MATERIALS = {"steel": {"bending": 140.0, "contact": 520.0, "note": "through-hardened ~200 HB (e.g. C45)"},
             "hardened_steel": {"bending": 300.0, "contact": 1100.0, "note": "case-hardened ~58 HRC"}}
# Lewis form factor Y, 20 deg full-depth teeth (Shigley table 14-2).
LEWIS_Y = [(12, 0.245), (13, 0.261), (14, 0.277), (15, 0.290), (16, 0.296), (17, 0.303), (18, 0.309), (19, 0.314),
           (20, 0.322), (21, 0.328), (22, 0.331), (24, 0.337), (26, 0.346), (28, 0.353), (30, 0.359), (34, 0.371),
           (38, 0.384), (43, 0.397), (50, 0.409), (60, 0.422), (75, 0.435), (100, 0.447), (150, 0.460),
           (300, 0.472), (400, 0.480)]
CP_STEEL = 191.0  # elastic coefficient, sqrt(MPa), steel on steel
PRESSURE_ANGLE = 20.0
TAU_ALLOW = 40.0  # MPa, shaft torsion
RATIO_TOL = 0.01  # tooth-count search tolerance
AXIAL_CLEAR = 5.0  # mm, gear face to side-plate inner face
RADIAL_CLEAR = 6.0  # mm, gear tips to the standoffs
STANDOFF_D = 12.0
SCREW = "M6"
SCREW_THREAD = "M6x1"
SCREW_CLEARANCE = 6.6  # ISO 273 medium
SCREW_ENGAGE = 9.0  # 1.5 d thread engagement in the standoff
SCREW_LENGTHS = (8, 10, 12, 16, 20, 25, 30, 35, 40, 45, 50, 55, 60)
EDGE = 4.0  # mm of plate beyond the standoffs


# ---------------------------------------------------------------- gear and shaft maths


def lewis_y(z: int) -> float:
    if z <= LEWIS_Y[0][0]:
        return LEWIS_Y[0][1]
    for (z0, y0), (z1, y1) in zip(LEWIS_Y, LEWIS_Y[1:]):
        if z0 <= z <= z1:
            return y0 + (y1 - y0) * (z - z0) / (z1 - z0)
    return LEWIS_Y[-1][1]


def pitch_velocity(m: float, z: int, rpm: float) -> float:
    """Pitch-line speed, m/s."""
    return math.pi * m * z * rpm / 60000.0


def kv(v: float) -> float:
    return (6.1 + v) / 6.1


def tangential_force(torque_nm: float, m: float, z: int) -> float:
    return 2000.0 * torque_nm / (m * z)


def bending_stress(torque_nm: float, m: float, z: int, b: float, rpm: float) -> float:
    """Lewis bending stress at the root of the gear with ``z`` teeth turning at ``rpm`` under ``torque_nm``."""
    return kv(pitch_velocity(m, z, rpm)) * tangential_force(torque_nm, m, z) / (b * m * lewis_y(z))


def _geometry_factor(ratio: float) -> float:
    a = math.radians(PRESSURE_ANGLE)
    return math.cos(a) * math.sin(a) / 2.0 * ratio / (ratio + 1.0)


def contact_stress(torque_nm: float, m: float, z1: int, z2: int, b: float, rpm: float) -> float:
    """Hertz contact stress at the pinion pitch point (external pair)."""
    d1 = m * z1
    load = kv(pitch_velocity(m, z1, rpm)) * tangential_force(torque_nm, m, z1)
    return CP_STEEL * math.sqrt(load / (b * d1 * _geometry_factor(z2 / z1)))


def face_for_contact(torque_nm: float, m: float, z1: int, z2: int, rpm: float, allow: float) -> float:
    """Face width that brings the contact stress down to ``allow``."""
    d1 = m * z1
    load = kv(pitch_velocity(m, z1, rpm)) * tangential_force(torque_nm, m, z1)
    return load * CP_STEEL ** 2 / (allow ** 2 * d1 * _geometry_factor(z2 / z1))


def shaft_stress(torque_nm: float, d: float) -> float:
    return 16000.0 * torque_nm / (math.pi * d ** 3)


def shaft_for(torque_nm: float) -> int:
    need = (16000.0 * torque_nm / (math.pi * TAU_ALLOW)) ** (1 / 3)
    return next((d for d in BORES if d >= need), max(BORES))


def bearing(d: int, series: str) -> str:
    return BORES[d][0 if series == "60" else 1]


def bearing_life_h(designation: str, radial_n: float, rpm: float) -> float:
    """Basic rating life L10h of a deep-groove bearing under a pure radial load."""
    c = DEEP_GROOVE[designation][5] * 1000.0
    return (c / radial_n) ** 3 * 1e6 / (60.0 * rpm)


def bearing_load(torque_nm: float, m: float, z1: int) -> float:
    """Radial load on each bearing: the tooth force Ft / cos(alpha), shared by two bearings with the gear centred."""
    return tangential_force(torque_nm, m, z1) / math.cos(math.radians(PRESSURE_ANGLE)) / 2.0


def pick_teeth(ratio: float, z_min: int = 17) -> tuple[int, int]:
    """Smallest pinion within RATIO_TOL, preferring hunting-tooth pairs; else the closest pair."""
    best = None
    for hunting in (True, False):
        for z1 in range(max(17, z_min), 31):
            z2 = round(z1 * ratio)
            if abs(z2 / z1 - ratio) / ratio <= RATIO_TOL and (not hunting or math.gcd(z1, z2) == 1):
                return z1, z2
    for z1 in range(max(17, z_min), 31):
        z2 = round(z1 * ratio)
        err = abs(z2 / z1 - ratio)
        if best is None or err < best[0]:
            best = (err, z1, z2)
    return best[1], best[2]


def module_for(torque_nm: float, z1: int, rpm: float, allow: float) -> float:
    for m in MODULES:
        if bending_stress(torque_nm, m, z1, FACE_FACTOR * m, rpm) <= allow:
            return m
    return MODULES[-1]


def pinion_web_ok(m: float, z1: int, shaft_d: float) -> bool:
    """The pinion bore leaves at least one module of web under the tooth roots (the gear generator's rule)."""
    return shaft_d <= m * (z1 - 2.4) - 2 * m


# ---------------------------------------------------------------- choices and skeleton


class GearboxChoices(BaseModel):
    """What a planner may choose. Everything optional falls back to a default."""

    model_config = ConfigDict(extra="forbid")

    ratio: float = Field(3.0, ge=1.5, le=8.0)
    input_torque_nm: float = Field(10.0, gt=0, le=200)
    input_rpm: float = Field(1500.0, ge=50, le=6000)
    life_hours: float = Field(10000.0, ge=500, le=100000)
    gear_material: Literal["steel", "hardened_steel"] = "steel"
    overrides: dict[str, float] = Field(default_factory=dict)  # skeleton key -> value, provenance "user"
    text: str = ""
    notes: list[str] = Field(default_factory=list)
    llm_fields: list[str] = Field(default_factory=list)


CHOICE_KEYS = {"ratio": "ratio", "input_torque_nm": "input_torque", "input_rpm": "input_rpm",
               "life_hours": "life_hours", "gear_material": "gear_material"}
OVERRIDABLE = ("pinion_teeth", "module", "face_width", "shaft_d_in", "shaft_d_out")


def _p(value: Any, unit: str | None, source: str, note: str | None = None) -> SkeletonParam:
    return SkeletonParam(value=value, unit=unit, source=source, note=note)


def skeleton_from_choices(c: GearboxChoices) -> tuple[Requirements, dict[str, SkeletonParam]]:
    notes = list(c.notes)
    sk: dict[str, SkeletonParam] = {
        "ratio": _p(c.ratio, None, "user", "requested reduction, input : output"),
        "input_torque": _p(c.input_torque_nm, "N.m", "user"),
        "input_rpm": _p(c.input_rpm, "rpm", "user"),
        "life_hours": _p(c.life_hours, "h", "user", "L10 bearing life target"),
        "gear_material": _p(c.gear_material, None, "user", MATERIALS[c.gear_material]["note"]),
    }
    for key, unit in (("pinion_teeth", None), ("gear_teeth", None), ("module", "mm"), ("face_width", "mm"),
                      ("shaft_d_in", "mm"), ("shaft_d_out", "mm")):
        sk[key] = _p(None, unit, "derived")
    sk["bearing_series_in"] = _p("60", None, "default", "deep-groove 60xx; 62xx when life is short")
    sk["bearing_series_out"] = _p("60", None, "default", "deep-groove 60xx; 62xx when life is short")
    for key, unit in (("bearing_in", None), ("bearing_out", None), ("centre_distance", "mm"), ("plate_t", "mm"),
                      ("gap", "mm"), ("plate_w", "mm"), ("plate_h", "mm"), ("standoff_x", "mm"), ("standoff_y", "mm"),
                      ("screw_length", "mm"), ("stub_in", "mm"), ("stub_out", "mm")):
        sk[key] = _p(None, unit, "derived")
    for key, v in c.overrides.items():
        if key not in OVERRIDABLE:
            raise ValueError(f"unknown gearbox override {key!r}; known: {list(OVERRIDABLE)}")
        sk[key] = sk[key].model_copy(update={"value": v, "source": "user"})
    for f, key in CHOICE_KEYS.items():
        if f not in c.model_fields_set:
            sk[key] = sk[key].model_copy(update={"source": "default"})
        elif f in c.llm_fields:
            sk[key] = sk[key].model_copy(update={"source": "llm"})
    req = Requirements(text=c.text, product_class="gearbox", ratio=c.ratio, input_torque_nm=c.input_torque_nm,
                       input_rpm=c.input_rpm, life_hours=c.life_hours, materials=[c.gear_material],
                       standards={"gears": "ISO 53 / ISO 54", "bearings": "ISO 15", "screws": "ISO 4762"}, notes=notes)
    return req, derive(sk)


def derive(sk: dict[str, SkeletonParam]) -> dict[str, SkeletonParam]:
    """Recompute every ``derived`` value from the others (user / router / default values are kept)."""
    sk = {k: v.model_copy() for k, v in sk.items()}
    v = {k: p.value for k, p in sk.items()}

    def put(key: str, value, note: str):
        if sk[key].source == "derived":
            sk[key] = sk[key].model_copy(update={"value": value, "note": note})
        v[key] = sk[key].value

    T, rpm, ratio = v["input_torque"], v["input_rpm"], v["ratio"]
    allow = MATERIALS[v["gear_material"]]["bending"]
    put("shaft_d_in", shaft_for(T), f"torsion tau <= {TAU_ALLOW:g} MPa, up to the next bearing bore")
    z_min = 17
    for _ in range(40):  # grow the pinion until its bore fits the input shaft
        z1, z2 = pick_teeth(ratio, z_min)
        put("pinion_teeth", z1, f"smallest pinion within {RATIO_TOL:.0%} of the ratio (hunting tooth preferred)")
        put("gear_teeth", round(v["pinion_teeth"] * ratio), "pinion teeth x ratio")
        put("module", module_for(T, v["pinion_teeth"], rpm, allow),
            f"smallest ISO module passing Lewis bending at b = {FACE_FACTOR:g} m")
        if pinion_web_ok(v["module"], v["pinion_teeth"], v["shaft_d_in"]) or sk["pinion_teeth"].source != "derived":
            break
        z_min = v["pinion_teeth"] + 1
    m, z1, z2 = v["module"], int(v["pinion_teeth"]), int(v["gear_teeth"])
    put("face_width", FACE_FACTOR * m, f"{FACE_FACTOR:g} x module")
    put("shaft_d_out", shaft_for(T * z2 / z1), f"torsion at the output torque, tau <= {TAU_ALLOW:g} MPa")
    put("bearing_in", bearing(int(v["shaft_d_in"]), v["bearing_series_in"]), "deep-groove bearing at the shaft bore")
    put("bearing_out", bearing(int(v["shaft_d_out"]), v["bearing_series_out"]), "deep-groove bearing at the shaft bore")

    a = m * (z1 + z2) / 2
    put("centre_distance", a, "m (z1 + z2) / 2")
    b_in, b_out = DEEP_GROOVE[v["bearing_in"]], DEEP_GROOVE[v["bearing_out"]]
    put("plate_t", max(b_in[2], b_out[2]) + 2.0, "wider bearing + 2 mm")
    L = next((x for x in SCREW_LENGTHS if x >= v["plate_t"] + SCREW_ENGAGE), SCREW_LENGTHS[-1])
    put("screw_length", float(L), f"plate + {SCREW_ENGAGE:g} mm engagement, next stock length")
    hole_depth = L - v["plate_t"] + 1.0
    put("gap", max(v["face_width"] + 2 * AXIAL_CLEAR, 2 * hole_depth + 4.0),
        f"face width + {AXIAL_CLEAR:g} mm each side (or room for both standoff tappings)")
    r_max = m * (max(z1, z2) / 2 + 1)
    put("standoff_y", r_max + RADIAL_CLEAR + STANDOFF_D / 2, "standoffs clear of the larger gear's tips")
    w = max(a + 2 * r_max + 2 * RADIAL_CLEAR, a + max(b_in[1], b_out[1]) + 2 * (STANDOFF_D + EDGE))
    put("plate_w", round(w, 1), "both gears plus radial clearance")
    put("plate_h", round(2 * (v["standoff_y"] + STANDOFF_D / 2 + EDGE), 1), "standoffs plus edge margin")
    put("standoff_x", round(v["plate_w"] / 2 - STANDOFF_D / 2 - EDGE, 3), "near the plate ends")
    put("stub_in", 2.0 * v["shaft_d_in"], "coupling length 2 d")
    put("stub_out", 2.0 * v["shaft_d_out"], "coupling length 2 d")
    return sk


def derived_numbers(sk: dict[str, SkeletonParam]) -> dict[str, float]:
    v = {k: p.value for k, p in sk.items()}
    z1, z2, m = int(v["pinion_teeth"]), int(v["gear_teeth"]), v["module"]
    T, rpm = v["input_torque"], v["input_rpm"]
    return {"ratio_actual": round(z2 / z1, 4), "output_torque": round(T * z2 / z1, 2),
            "output_rpm": round(rpm * z1 / z2, 1), "centre_distance": v["centre_distance"],
            "pitch_velocity": round(pitch_velocity(m, z1, rpm), 3),
            "tangential_force": round(tangential_force(T, m, z1), 1),
            "housing_w": v["plate_w"], "housing_h": v["plate_h"], "housing_depth": 2 * v["plate_t"] + v["gap"]}


# ---------------------------------------------------------------- recipes


def _port(name, origin=(0, 0, 0), z=(0, 0, 1), x=(1, 0, 0), label="", **contract) -> dict:
    return {"name": name, "origin": list(origin), "z": list(z), "x": list(x), "label": label, "contract": contract}


def plate_recipe(v: dict, name: str = "side_plate") -> dict:
    a = v["centre_distance"]
    feats = [
        {"id": "profile", "op": "centered_rectangle", "plane": "XY", "width_ref": "w", "height_ref": "h"},
        {"id": "body", "op": "extrude", "profile_ref": "profile", "distance_ref": "t", "direction": "positive_z"},
        {"id": "bore_in", "op": "hole", "body_ref": "body", "diameter_ref": "d_in", "center_x_ref": "x_in",
         "center_y_ref": "zero"},
        {"id": "bore_out", "op": "hole", "body_ref": "bore_in", "diameter_ref": "d_out", "center_x_ref": "x_out",
         "center_y_ref": "zero"},
        {"id": "screw_holes", "op": "linear_hole_pattern", "body_ref": "bore_out", "diameter_ref": "d_screw",
         "count_x_ref": "two", "count_y_ref": "two", "pitch_x_ref": "px", "pitch_y_ref": "py"},
    ]
    params = {"w": v["plate_w"], "h": v["plate_h"], "t": v["plate_t"], "d_in": DEEP_GROOVE[v["bearing_in"]][1],
              "d_out": DEEP_GROOVE[v["bearing_out"]][1], "x_in": -a / 2, "x_out": a / 2, "zero": 0.0,
              "d_screw": SCREW_CLEARANCE, "two": {"value": 2, "kind": "count"}, "px": 2 * v["standoff_x"],
              "py": 2 * v["standoff_y"]}
    return {"name": name, "parameters": params, "features": feats}


def standoff_recipe(v: dict) -> dict:
    depth = v["screw_length"] - v["plate_t"] + 1.0
    feats = [
        {"id": "profile", "op": "circle", "plane": "XY", "diameter_ref": "d"},
        {"id": "body", "op": "extrude", "profile_ref": "profile", "distance_ref": "h", "direction": "positive_z"},
        {"id": "tap_top", "op": "hole", "body_ref": "body", "diameter_ref": "d_tap", "mode": "blind",
         "depth_ref": "depth", "face": "top"},
        {"id": "tap_bottom", "op": "hole", "body_ref": "tap_top", "diameter_ref": "d_tap", "mode": "blind",
         "depth_ref": "depth", "face": "bottom"},
    ]
    # Tapped M6 both ends; modelled at the nominal diameter so the screw shank (also nominal) does not overlap.
    return {"name": "standoff", "parameters": {"d": STANDOFF_D, "h": v["gap"], "d_tap": 6.0, "depth": depth},
            "features": feats}


def shaft_recipe(d: float, length: float, name: str) -> dict:
    return {"name": name, "parameters": {"d": d, "length": length}, "features": [
        {"id": "profile", "op": "circle", "plane": "XY", "diameter_ref": "d"},
        {"id": "body", "op": "extrude", "profile_ref": "profile", "distance_ref": "length", "direction": "positive_z"},
    ]}


# ---------------------------------------------------------------- assembly


COLORS = {"plate": "#8fa3b5", "standoff": "#b5b5b5", "screw": "#2b2b2b", "shaft": "#9aa3ad", "bearing": "#555a60",
          "pinion": "#c97c2e", "gear": "#3b7dd8"}


def _recipe_inst(iid, recipe, ports, **kw) -> dict:
    return {"id": iid, "source": "recipe", "ref": {"recipe": recipe, "ports": ports}, **kw}


def _cat_inst(iid, generator, params, **kw) -> dict:
    return {"id": iid, "source": "catalog", "ref": {"generator": generator, "params": params}, **kw}


def assembly_from_skeleton(sk: dict[str, SkeletonParam], name: str = "gearbox") -> AssemblySpec:
    from ...catalog.gears import mesh_layout_params

    v = {k: p.value for k, p in sk.items()}
    m, z1, z2 = v["module"], int(v["pinion_teeth"]), int(v["gear_teeth"])
    a, t, gap, fw = v["centre_distance"], v["plate_t"], v["gap"], v["face_width"]
    d_in, d_out = v["shaft_d_in"], v["shaft_d_out"]
    D_in, D_out = DEEP_GROOVE[v["bearing_in"]][1], DEEP_GROOVE[v["bearing_out"]][1]
    sx, sy = v["standoff_x"], v["standoff_y"]
    corners = [(sx, sy), (-sx, sy), (-sx, -sy), (sx, -sy)]
    material = "steel"
    pinion = {"teeth": z1, "module": m, "face_width": fw, "bore_d": d_in, "material": material}
    gear = {"teeth": z2, "module": m, "face_width": fw, "bore_d": d_out, "material": material}
    phase = mesh_layout_params("gear.spur", pinion, "gear.spur", gear, (1.0, 0.0))["rotation_deg"]

    def plate_ports(inner_z: float, inner_n: int) -> list[dict]:
        ports = [_port("bore_in", (-a / 2, 0, t / 2), label="input bearing housing", kind="axis", od=D_in,
                       fit="housing"),
                 _port("bore_out", (a / 2, 0, t / 2), label="output bearing housing", kind="axis", od=D_out,
                       fit="housing")]
        outer_z = t - inner_z
        for k, (x, y) in enumerate(corners):
            ports.append(_port(f"standoff_seat_{k}", (x, y, inner_z), (0, 0, inner_n), label="standoff seat",
                               kind="face", thread=SCREW_THREAD))
            ports.append(_port(f"screw_seat_{k}", (x, y, outer_z), (0, 0, -inner_n), label="screw head seat",
                               kind="face", thread=SCREW_THREAD))
        return ports

    stub_in, stub_out = v["stub_in"], v["stub_out"]
    len_in = stub_in + 2 * t + gap
    len_out = 2 * t + gap + stub_out

    def shaft_ports(z_a: float, z_b: float, d: float, coupling_z: float, coupling_n: int) -> list[dict]:
        return [_port("bearing_a", (0, 0, z_a), label="bearing seat in plate A", kind="axis", bore_d=d, fit="shaft"),
                _port("bearing_b", (0, 0, z_b), label="bearing seat in plate B", kind="axis", bore_d=d, fit="shaft"),
                _port("gear_seat", (0, 0, z_a + t / 2 + gap / 2), label="gear seat", kind="axis", bore_d=d,
                      fit="shaft"),
                _port("coupling", (0, 0, coupling_z), (0, 0, coupling_n), label="coupling end", kind="face",
                      shaft_d=d)]

    v_plate = dict(v)
    instances = [
        _recipe_inst("plate_a", plate_recipe(v_plate), plate_ports(t, 1), grounded=True, part_number="side_plate",
                     color=COLORS["plate"]),
        _recipe_inst("plate_b", plate_recipe(v_plate), plate_ports(0.0, -1), part_number="side_plate",
                     color=COLORS["plate"]),
        _recipe_inst("standoff_0", standoff_recipe(v), [
            _port("bottom", (0, 0, 0), (0, 0, -1), label="end face", kind="face", thread=SCREW_THREAD),
            _port("top", (0, 0, gap), (0, 0, 1), label="end face", kind="face", thread=SCREW_THREAD)],
            part_number="standoff", color=COLORS["standoff"]),
        *[{"id": f"standoff_{k}", "copy_of": "standoff_0", "color": COLORS["standoff"]} for k in (1, 2, 3)],
        _cat_inst("screw_a0", "iso4762_socket_head_cap_screw", {"size": SCREW, "length": v["screw_length"],
                                                                "material": "steel"},
                  part_number="screw", color=COLORS["screw"]),
        *[{"id": f"screw_{s}{k}", "copy_of": "screw_a0", "color": COLORS["screw"]}
          for s in "ab" for k in range(4) if (s, k) != ("a", 0)],
        _cat_inst("bearing_in_a", "deep_groove_ball_bearing", {"designation": v["bearing_in"], "seal": "2RS"},
                  part_number="bearing_in", color=COLORS["bearing"]),
        {"id": "bearing_in_b", "copy_of": "bearing_in_a", "color": COLORS["bearing"]},
        _cat_inst("bearing_out_a", "deep_groove_ball_bearing", {"designation": v["bearing_out"], "seal": "2RS"},
                  part_number="bearing_out", color=COLORS["bearing"]),
        {"id": "bearing_out_b", "copy_of": "bearing_out_a", "color": COLORS["bearing"]},
        _recipe_inst("shaft_in", shaft_recipe(d_in, len_in, "input_shaft"),
                     shaft_ports(stub_in + t / 2, stub_in + 1.5 * t + gap, d_in, 0.0, -1), color=COLORS["shaft"]),
        _recipe_inst("shaft_out", shaft_recipe(d_out, len_out, "output_shaft"),
                     shaft_ports(t / 2, 1.5 * t + gap, d_out, len_out, 1), color=COLORS["shaft"]),
        _cat_inst("pinion", "gear.spur", pinion, color=COLORS["pinion"]),
        _cat_inst("gear", "gear.spur", gear, color=COLORS["gear"]),
    ]
    mates = []
    for k in range(4):
        mates.append({"a": "plate_a.standoff_seat_%d" % k, "b": f"standoff_{k}.bottom", "type": "fixed",
                      "intent": "bolted"})
    mates.append({"a": "standoff_0.top", "b": "plate_b.standoff_seat_0", "type": "fixed", "intent": "bolted"})
    for s in "ab":
        for k in range(4):
            mates.append({"a": f"plate_{s}.screw_seat_{k}", "b": f"screw_{s}{k}.head_seat", "type": "fixed",
                          "intent": "bolted"})
    for s in "ab":
        mates.append({"a": f"plate_{s}.bore_in", "b": f"bearing_in_{s}.outer", "type": "fixed", "align": "aligned",
                      "intent": "press_fit"})
        mates.append({"a": f"plate_{s}.bore_out", "b": f"bearing_out_{s}.outer", "type": "fixed", "align": "aligned",
                      "intent": "press_fit"})
    mates += [
        {"id": "input", "a": "bearing_in_a.bore_axis", "b": "shaft_in.bearing_a", "type": "revolute",
         "align": "aligned", "intent": "clearance"},
        {"id": "output", "a": "bearing_out_a.bore_axis", "b": "shaft_out.bearing_a", "type": "revolute",
         "align": "aligned", "intent": "clearance"},
        {"a": "shaft_in.gear_seat", "b": "pinion.bore_axis", "type": "fixed", "align": "aligned", "intent": "press_fit"},
        # Turned about the output shaft so the gear's teeth sit in the pinion's gaps.
        {"a": "shaft_out.gear_seat", "b": "gear.bore_axis", "type": "fixed", "align": "aligned", "angle": phase,
         "intent": "press_fit"},
    ]
    clear = AXIAL_CLEAR - 1.0
    clearances = [{"a": g, "b": o, "min": clear} for g in ("pinion", "gear")
                  for o in ("plate_a", "plate_b", "standoff_0", "standoff_1", "standoff_2", "standoff_3")]
    clearances += [{"a": "pinion", "b": "shaft_out", "min": 0.5}, {"a": "gear", "b": "shaft_in", "min": 0.5}]
    return AssemblySpec.model_validate({
        "name": name, "instances": instances, "mates": mates,
        "dof": 2,  # input and output shafts; the gear mesh couples them (checked, not a joint)
        "clearances": clearances, "tolerances": {"interference_volume": 1.0, "contact_gap": 0.05, "sweep_steps": 9},
    })


def product_tree(asm: AssemblySpec) -> ProductNode:
    def part(pid, name, proc, inst, standard=None):
        return {"id": pid, "name": name, "kind": "part", "procurement": proc, "instances": inst, "standard": standard}

    def sub(sid, name, children):
        return {"id": sid, "name": name, "kind": "subsystem", "children": children}

    tree = {"id": "gearbox", "name": "Single-stage spur gearbox", "kind": "product", "children": [
        sub("housing", "Housing", [
            part("side_plates", "Side plate (machined, bearing bores)", "make", ["plate_a", "plate_b"]),
            part("standoffs", "Standoff, tapped M6 both ends", "make", [f"standoff_{k}" for k in range(4)]),
            part("screws", "Socket head cap screw", "standard", [f"screw_{s}{k}" for s in "ab" for k in range(4)],
                 "ISO 4762"),
        ]),
        sub("input", "Input shaft assembly", [
            part("input_shaft", "Input shaft", "make", ["shaft_in"]),
            part("pinion", "Pinion (spur)", "buy", ["pinion"], "ISO 53 / ISO 54"),
            part("input_bearings", "Input bearing", "standard", ["bearing_in_a", "bearing_in_b"], "ISO 15"),
        ]),
        sub("output", "Output shaft assembly", [
            part("output_shaft", "Output shaft", "make", ["shaft_out"]),
            part("gear", "Gear (spur)", "buy", ["gear"], "ISO 53 / ISO 54"),
            part("output_bearings", "Output bearing", "standard", ["bearing_out_a", "bearing_out_b"], "ISO 15"),
        ]),
    ]}
    return ProductNode.model_validate(tree)


TARGETS = {
    "ratio_tol_pct": 2.0,  # % between requested and built ratio
    "housing_clearance_min": AXIAL_CLEAR - 1.0,  # mm, gears to plates and standoffs
    "pitch_velocity_max": 20.0,  # m/s; above this cut spur gears need a finer quality grade (warning)
    "bore_web_min": 3.0,  # mm of side plate between the two bearing housings
}


def spec_from_skeleton(req: Requirements, sk: dict[str, SkeletonParam], name: str | None = None,
                       history: list | None = None) -> ProductSpec:
    sk = derive(sk)
    ratio = sk["ratio"].value
    name = name or f"gearbox_{ratio:g}to1_{sk['input_torque'].value:g}nm".replace(".", "p")
    asm = assembly_from_skeleton(sk, name)
    return ProductSpec(name=name, template=TEMPLATE_ID, requirements=req, skeleton=sk, tree=product_tree(asm),
                       assembly=asm, targets=dict(TARGETS), derived=derived_numbers(sk), history=list(history or []))


def gearbox_spec(choices: GearboxChoices | dict) -> ProductSpec:
    c = choices if isinstance(choices, GearboxChoices) else GearboxChoices.model_validate(choices)
    req, sk = skeleton_from_choices(c)
    return spec_from_skeleton(req, sk)
