"""Diamond-frame bicycle template ``bicycle.diamond_v1`` (roadmap: the bicycle decomposition).

Three steps, each deterministic:

1. ``skeleton_from_choices``: typed choices (what a planner may pick: use case,
   size or rider height, wheel size, tyre width, standards, overrides) become a
   flat skeleton of named values, each with provenance. Size comes from the
   sizing table below; derived values are computed in ``derive``.
2. ``derive``: closes the skeleton. The fork's axle-to-crown length is set from
   the largest tyre the frame is designed for, and the head-tube length is then
   solved so the front axle sits exactly at the rear axle height (equal wheels on
   level ground: the "front axle level error" of a free-standing ``FrameGeometry``
   is zero by construction)::

       F.z = stack - (HTL + lower_stack + a2c) sin HA + offset cos HA = bb_drop
       HTL = (stack - bb_drop + offset cos HA) / sin HA - a2c - lower_stack

   Saddle height follows the LeMond rule (0.883 x inseam, BB centre to saddle
   top) and fixes the seatpost insertion.
3. ``spec_from_skeleton``: the skeleton becomes a ``ProductSpec`` with a product
   tree and the ``AssemblySpec``: frame (weldment, grounded), fork (weldment,
   revolute steering about the head-tube axis with +-lock limits), headset
   cups, stem and bar on the fork's steerer, front and rear wheels (hub + rim +
   tyre, each a rigid group revolving about its axle), BSA bottom bracket and
   crankset (revolute about the spindle), seatpost (slider with the
   minimum-insertion limit, set at the fitted height) and saddle.

Sizing table (approx; typical of 2020s endurance-road geometry, gravel adds
stack, slackens the head angle and lengthens the stays). Rider height ranges
are inclusive at the bottom. Values are frame-design starting points, not a
bike fit:

=====  ==========  =====  =====  =====  =====  ===  ===  ====  =====  ====  ===
size   rider cm    stack  reach  HA     SA     ST   CS   drop  crank  stem  bar
=====  ==========  =====  =====  =====  =====  ===  ===  ====  =====  ====  ===
XS     150-160     515    365    70.5   75.0   460  410  74    165    70    620
S      160-169     535    372    71.25  74.0   490  410  74    170    80    640
M      169-177     556    380    72.0   73.5   520  410  72    172.5  90    660
L      177-185     578    387    72.5   73.0   545  410  72    172.5  100   680
XL     185-193     600    393    73.0   72.75  570  412  70    175    110   700
XXL    193-205     624    400    73.0   72.5   595  415  70    175    120   720
=====  ==========  =====  =====  =====  =====  ===  ===  ====  =====  ====  ===

Gravel deltas: stack +20, reach -5, HA -1.5 deg, CS +15, drop +3. Fork offset is
50 mm for XS/S and 47/45 mm above (gravel 50 throughout). ST is centre-to-top.
Inseam, when not given, is estimated as 0.47 x height (approx).
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ...contracts.assembly import AssemblySpec
from ...contracts.product import ProductNode, ProductSpec, Requirements, SkeletonParam

TEMPLATE_ID = "bicycle.diamond_v1"
SIZES = ("XS", "S", "M", "L", "XL", "XXL")

# size: (rider_min_cm, rider_max_cm, stack, reach, HA, SA, ST, CS, drop, crank, stem, bar)
SIZE_TABLE: dict[str, tuple[float, ...]] = {
    "XS": (150, 160, 515, 365, 70.5, 75.0, 460, 410, 74, 165.0, 70, 620),
    "S": (160, 169, 535, 372, 71.25, 74.0, 490, 410, 74, 170.0, 80, 640),
    "M": (169, 177, 556, 380, 72.0, 73.5, 520, 410, 72, 172.5, 90, 660),
    "L": (177, 185, 578, 387, 72.5, 73.0, 545, 410, 72, 172.5, 100, 680),
    "XL": (185, 193, 600, 393, 73.0, 72.75, 570, 412, 70, 175.0, 110, 700),
    "XXL": (193, 205, 624, 400, 73.0, 72.5, 595, 415, 70, 175.0, 120, 720),
}
GRAVEL_DELTA = {"stack": 20.0, "reach": -5.0, "head_angle": -1.5, "chainstay_length": 15.0, "bb_drop": 3.0}
ROAD_FORK_OFFSET = {"XS": 50.0, "S": 50.0, "M": 47.0, "L": 45.0, "XL": 45.0, "XXL": 45.0}
# Compact top-tube slope (deg) by size, more on small frames for standover; gravel +2.
TT_SLOPE = {"XS": 14.0, "S": 12.0, "M": 10.0, "L": 8.0, "XL": 6.0, "XXL": 5.0}
WHEEL_BSD = {"700c": 622, "650b": 584}
# Default tyre and the largest tyre the frame is designed to clear, per use case and wheel.
TYRES = {("road", "700c"): (28.0, 32.0), ("road", "650b"): (38.0, 42.0),
         ("gravel", "700c"): (40.0, 45.0), ("gravel", "650b"): (47.0, 50.0)}
# Rear cassette centre-line from the hub centre (approx; varies by hub and cassette).
REAR_CHAINLINE = {"12x142": 45.0, "135x10qr": 45.0}
INSEAM_RATIO = 0.47  # approx inseam / height
LEMOND = 0.883  # saddle height (BB centre to saddle top) / inseam
CROWN_HEIGHT = 25.0  # ForkGeometry default crown height (mm)
SEATPOST_LENGTHS = (300.0, 350.0, 400.0, 450.0)
SADDLE_TOP_ABOVE_CLAMP = 30.0 + 45.0 / 2  # saddle rail_drop + half its envelope height (catalog defaults)
MIN_HEAD_TUBE = 90.0


class BicycleChoices(BaseModel):
    """What a planner may choose. Everything optional falls back to the sizing table or a default."""

    model_config = ConfigDict(extra="forbid")

    use_case: Literal["road", "gravel"] = "road"
    frame_size: Literal["XS", "S", "M", "L", "XL", "XXL"] | None = None
    rider_height_cm: float | None = Field(default=None, gt=100, lt=230)
    rider_inseam_cm: float | None = Field(default=None, gt=50, lt=120)
    wheel_size: Literal["700c", "650b"] = "700c"
    tyre_width_mm: float | None = Field(default=None, ge=20, le=60)
    bb_standard: Literal["BSA68", "BSA73"] = "BSA68"
    rear_axle: Literal["12x142", "135x10qr"] = "12x142"
    front_axle: Literal["12x100", "100x9qr"] = "12x100"
    crank_length_mm: float | None = Field(default=None, ge=150, le=185)
    chainrings: list[int] | None = None
    material: str = "chromoly"
    overrides: dict[str, float] = Field(default_factory=dict)  # skeleton key -> value, provenance "user"
    text: str = ""
    notes: list[str] = Field(default_factory=list)
    llm_fields: list[str] = Field(default_factory=list)  # choices a planner filled in (provenance "llm", not "user")


# Choice field -> skeleton key it sets (for provenance).
CHOICE_KEYS = {"use_case": "use_case", "frame_size": "size", "rider_height_cm": "rider_height", "rider_inseam_cm": "rider_inseam",
               "wheel_size": "wheel_bsd", "tyre_width_mm": "tyre_width", "bb_standard": "bb_shell_width",
               "rear_axle": "rear_axle", "front_axle": "front_axle", "crank_length_mm": "crank_length", "chainrings": "chainrings"}


def size_for_height(height_cm: float) -> tuple[str, str | None]:
    """Sizing-table lookup; the note says when the rider is outside the table."""
    if height_cm < SIZE_TABLE["XS"][0]:
        return "XS", f"rider {height_cm:g} cm is below the sizing table (from {SIZE_TABLE['XS'][0]:g} cm); using XS"
    for size in SIZES:
        lo, hi = SIZE_TABLE[size][:2]
        if lo <= height_cm < hi:
            return size, None
    return "XXL", (None if height_cm <= SIZE_TABLE["XXL"][1] else
                   f"rider {height_cm:g} cm is above the sizing table (to {SIZE_TABLE['XXL'][1]:g} cm); using XXL")


def _p(value: Any, unit: str | None, source: str, note: str | None = None) -> SkeletonParam:
    return SkeletonParam(value=value, unit=unit, source=source, note=note)


def skeleton_from_choices(c: BicycleChoices) -> tuple[Requirements, dict[str, SkeletonParam]]:
    notes = list(c.notes)
    if c.frame_size:
        size, size_src = c.frame_size, "user"
        if c.rider_height_cm:
            by_h, _ = size_for_height(c.rider_height_cm)
            if by_h != size:
                notes.append(f"size {size} was asked for; the sizing table suggests {by_h} for {c.rider_height_cm:g} cm")
    elif c.rider_height_cm:
        size, note = size_for_height(c.rider_height_cm)
        size_src = "table"
        if note:
            notes.append(note)
    else:
        size, size_src = "M", "default"
        notes.append("no size or rider height given; assumed M")
    row = dict(zip(("rmin", "rmax", "stack", "reach", "head_angle", "seat_angle", "seat_tube_length", "chainstay_length",
                    "bb_drop", "crank_length", "stem_length", "bar_width"), SIZE_TABLE[size]))
    height = c.rider_height_cm or (row["rmin"] + row["rmax"]) / 2
    height_src = "user" if c.rider_height_cm else "table"
    gravel = c.use_case == "gravel"
    default_tyre, max_tyre = TYRES[(c.use_case, c.wheel_size)]
    tyre = c.tyre_width_mm or default_tyre

    sk: dict[str, SkeletonParam] = {
        "use_case": _p(c.use_case, None, "user"),
        "size": _p(size, None, size_src),
        "rider_height": _p(round(height, 1), "cm", height_src),
        "rider_inseam": (_p(c.rider_inseam_cm, "cm", "user") if c.rider_inseam_cm else
                         _p(round(INSEAM_RATIO * height, 1), "cm", "derived", f"{INSEAM_RATIO} x rider height (approx)")),
        "wheel_bsd": _p(WHEEL_BSD[c.wheel_size], "mm", "user", f"{c.wheel_size} (ISO 5775)"),
        "tyre_width": _p(tyre, "mm", "user" if c.tyre_width_mm else "default"),
        "max_tyre_width": _p(max(max_tyre, 0.0), "mm", "default", "largest tyre the frame and fork are designed to clear"),
        "material": _p(c.material, None, "default"),
    }
    for key in ("stack", "reach", "head_angle", "seat_angle", "chainstay_length", "bb_drop"):
        v = row[key] + (GRAVEL_DELTA.get(key, 0.0) if gravel else 0.0)
        sk[key] = _p(v, "deg" if key.endswith("angle") else "mm", "table", f"size {size} {c.use_case}")
    sk["seat_tube_nominal"] = _p(row["seat_tube_length"], "mm", "table", f"size {size}, centre to top")
    sk["seat_tube_length"] = _p(None, "mm", "derived")
    sk["tt_slope"] = _p(TT_SLOPE[size] + (2.0 if gravel else 0.0), "deg", "table", "compact top tube drops toward the seat tube")
    sk["fork_offset"] = _p(50.0 if gravel else ROAD_FORK_OFFSET[size], "mm", "table")
    sk["crown_clearance"] = _p(8.0, "mm", "default", "design gap above the largest tyre under the fork crown")
    sk["fork_a2c"] = _p(None, "mm", "derived")
    sk["head_tube_length"] = _p(None, "mm", "derived")
    sk["lower_stack"] = _p(3.0, "mm", "default", "ZS44 lower cup + crown race")
    sk["upper_stack"] = _p(8.0, "mm", "default", "ZS44 upper cup + top cover")
    sk["spacer_stack"] = _p(0.0, "mm", "default")
    sk["fork_blade_spread"] = _p(None, "mm", "derived")
    sk["chainstay_od"] = _p(19.0, "mm", "default")
    sk["cs_bend"] = _p(None, "mm", "derived")
    sk["ss_bend"] = _p(None, "mm", "derived")
    sk["bb_shell_width"] = _p(int(c.bb_standard[3:]), "mm", "user", c.bb_standard)
    sk["rear_axle"] = _p(c.rear_axle, None, "user")
    sk["front_axle"] = _p(c.front_axle, None, "user")
    sk["crank_length"] = _p(c.crank_length_mm or row["crank_length"], "mm", "user" if c.crank_length_mm else "table")
    rings = c.chainrings or ([40] if gravel else [50, 34])
    sk["chainrings"] = _p(sorted(rings), None, "user" if c.chainrings else "default")
    sk["chainline"] = _p(45.0 if len(rings) == 1 else 43.5, "mm", "default", "front ring-pack centre (approx)")
    sk["rear_chainline"] = _p(REAR_CHAINLINE[c.rear_axle], "mm", "default", "cassette centre (approx)")
    sk["q_factor"] = _p(150.0 if gravel else 146.0, "mm", "default")
    sk["stem_length"] = _p(row["stem_length"], "mm", "table")
    sk["stem_angle"] = _p(-6.0, "deg", "default")
    sk["bar_width"] = _p(row["bar_width"], "mm", "table", "flat bar (the catalog has no drop bar yet)")
    sk["seatpost_d"] = _p(27.2, "mm", "default")
    sk["seatpost_length"] = _p(None, "mm", "derived")
    sk["seatpost_min_insertion"] = _p(80.0, "mm", "default", "maker's mark (approx)")
    sk["saddle_height"] = _p(None, "mm", "derived")
    sk["steer_lock"] = _p(45.0, "deg", "default", "steering stop each way")
    for key, v in c.overrides.items():
        if key not in sk:
            raise ValueError(f"unknown skeleton override {key!r}; known: {sorted(sk)}")
        sk[key] = sk[key].model_copy(update={"value": v, "source": "user"})
    for f, key in CHOICE_KEYS.items():  # choices left at their default are not the user's
        if f not in c.model_fields_set and sk[key].source == "user":
            sk[key] = sk[key].model_copy(update={"source": "default"})
    for f in c.llm_fields:
        key = CHOICE_KEYS.get(f)
        if key in sk and sk[key].source == "user":
            sk[key] = sk[key].model_copy(update={"source": "llm"})

    standards = {"bb": c.bb_standard, "headset": "ZS44", "front_axle": c.front_axle, "rear_axle": c.rear_axle,
                 "seatpost": "27.2", "bar_clamp": "31.8", "wheel": f"ISO 5775 {WHEEL_BSD[c.wheel_size]}"}
    req = Requirements(text=c.text, use_case=c.use_case, rider_height_cm=c.rider_height_cm, rider_inseam_cm=c.rider_inseam_cm,
                       frame_size=c.frame_size, wheel_size=c.wheel_size, tyre_width_mm=c.tyre_width_mm,
                       materials=[c.material], standards=standards, notes=notes)
    return req, derive(sk)


def derive(sk: dict[str, SkeletonParam]) -> dict[str, SkeletonParam]:
    """Recompute every ``derived`` value from the others (user / router / table values are kept)."""
    sk = {k: v.model_copy() for k, v in sk.items()}
    v = {k: p.value for k, p in sk.items()}

    def put(key: str, value, note: str):
        if sk[key].source == "derived":
            value = [round(x, 3) for x in value] if isinstance(value, list) else round(value, 3)
            sk[key] = sk[key].model_copy(update={"value": value, "note": note})
        v[key] = sk[key].value

    wheel_r_max = v["wheel_bsd"] / 2 + v["max_tyre_width"]
    put("fork_a2c", wheel_r_max + CROWN_HEIGHT + v["crown_clearance"],
        "BSD/2 + max tyre + crown height + crown clearance")
    put("fork_blade_spread", max(48.0, v["max_tyre_width"] / 2 + 14.0 + 9.0),
        "blade centre from the fork plane at the crown: half the max tyre + blade radius + 9 mm")
    put("cs_bend", _chainstay_bends(v), "[back, out] of the chainstay bend: inboard of the inner chainring, "
        "then straight out past the tyre")
    ha = math.radians(v["head_angle"])
    put("head_tube_length",
        (v["stack"] - v["bb_drop"] + v["fork_offset"] * math.cos(ha)) / math.sin(ha) - v["fork_a2c"] - v["lower_stack"],
        "solved so the front axle sits at rear-axle height")
    put("seat_tube_length", max(v["seat_tube_nominal"], _top_tube_junction(v) + SEAT_CLUSTER_EXT),
        f"table value, or the top-tube junction + {SEAT_CLUSTER_EXT:g} mm if that is higher")
    put("ss_bend", _seatstay_bend(sk, v), "[along, out]: seat-stay bend this far up from the dropout, spread past "
        "the largest tyre (empty when straight stays already clear it)")
    inseam = v["rider_inseam"] * 10
    put("saddle_height", LEMOND * inseam, f"LeMond {LEMOND} x inseam, BB centre to saddle top")
    clamp = _clamp_distance(v["saddle_height"], v["seat_angle"])
    exposed = clamp - v["seat_tube_length"]  # post length above the seat-tube top
    need = exposed + v["seatpost_min_insertion"] + 20.0
    length = next((L for L in SEATPOST_LENGTHS if L >= need), SEATPOST_LENGTHS[-1])
    put("seatpost_length", length, f"shortest stock post giving min insertion + 20 mm (needs {need:.0f})")
    return sk


RING_SPACING = 8.0  # catalog crankset default (approx)
CS_RING_GAP = 3.5  # mm, design gap chainstay to inner chainring face (measured gaps come out ~1 mm less)
CS_RECT = (12.0, 22.0, 1.0)  # ovalised chainstay through the ring and tyre zone: lateral width, height, wall (approx)
TT_OFFSET = 25.0  # top-tube axis below the head-tube top (clears the upper headset cup)
STAY_END_OUTSET = 2.0
REAR_DROPOUT_T = 16.0


def _chainstay_bends(v: dict[str, Any]) -> list[float]:
    """Chainstay bend nodes ``[back1, out1, back2, out2]`` from the chainrings and the wheel.

    The stay is an ovalised section (``CS_RECT``) from the BB through the chainring and tyre zone. It must
    stay inboard of the inner ring's face while it is inside the ring's radius, so bend 1 sits just behind
    that radius, as far out as the ring allows. From there it runs straight to the dropout; bend 2 is a
    section change only (on the same line), where the stay leaves the tyre (rim bead radius) and becomes
    the round tapered stay. Whether the tyre clears is measured, not assumed: a short chainstay with a wide
    tyre fails the clearance check, which the router repairs by lengthening the stays.
    """
    from ...catalog.bicycle import outside_diameter
    from ...weldment.bike_frame import REAR_AXLES

    rings = sorted(v["chainrings"])
    inner_z = v["chainline"] - (len(rings) - 1) / 2 * RING_SPACING
    back1 = outside_diameter(rings[0]) / 2 + 2.0 + CS_RECT[0] / 2
    out1 = inner_z - 1.0 - CS_RING_GAP - CS_RECT[0] / 2
    rear_x = math.sqrt(v["chainstay_length"] ** 2 - v["bb_drop"] ** 2)
    y_end = REAR_AXLES[v["rear_axle"]][0] / 2 + REAR_DROPOUT_T / 2 + STAY_END_OUTSET
    back2 = max(rear_x - v["wheel_bsd"] / 2 + 10.0, back1 + 30.0)
    out2 = out1 + (back2 - back1) * (y_end - out1) / (rear_x - back1)
    return [back1, out1, back2, out2]


SS_OD = 16.0  # FrameGeometry.ss default outside diameter


def _seatstay_bend(sk: dict[str, SkeletonParam], v: dict[str, Any]) -> list[float]:
    """Seat stays converge on the seat tube, so with wide tyres they cross the tyre too far in. A bend just
    above the tyre (``wheel radius + 15`` mm up the stay from the dropout) pushes them out to the target
    clearance; below it they open further toward the dropout."""
    from ...weldment.bike_frame import FrameGeometry, frame_nodes

    geo = frame_geometry({**sk, "ss_bend": sk["ss_bend"].model_copy(update={"value": []})})
    nodes, _ = frame_nodes(FrameGeometry.model_validate(geo))
    top, end = nodes["ss_top_l"], nodes["stay_end_l"]
    length = math.dist(top, end)
    along = v["wheel_bsd"] / 2 + v["max_tyre_width"] + 15.0
    straight = end[1] + along / length * (top[1] - end[1])
    out = v["max_tyre_width"] / 2 + TARGETS["tyre_clearance_min"] + SS_OD / 2 + 1.0
    return [along, out] if out > straight else []


SEAT_CLUSTER_EXT = 25.0  # mm of seat tube above the top-tube axis


def _top_tube_junction(v: dict[str, Any]) -> float:
    """Distance up the seat tube where the top-tube axis meets it (as ``frame_nodes`` computes it)."""
    ha, sa, beta = (math.radians(v[k]) for k in ("head_angle", "seat_angle", "tt_slope"))
    u = (-math.cos(ha), math.sin(ha))
    s = (-math.cos(sa), math.sin(sa))
    tt_off = TT_OFFSET
    f = (v["reach"] - tt_off * u[0], v["stack"] - tt_off * u[1])
    d = (-math.cos(beta), -math.sin(beta))
    det = s[0] * (-d[1]) - s[1] * (-d[0])
    return (f[0] * (-d[1]) - f[1] * (-d[0])) / det


def _clamp_distance(saddle_height: float, seat_angle: float) -> float:
    """Distance along the seat tube from the BB to the saddle clamp for a saddle top ``saddle_height`` from the BB.

    The saddle top sits ``SADDLE_TOP_ABOVE_CLAMP`` vertically above the clamp: solve
    ``|D s + (0, 0, h)| = H`` for D with s the seat-tube unit vector.
    """
    s_z = math.sin(math.radians(seat_angle))
    h = SADDLE_TOP_ABOVE_CLAMP
    return -h * s_z + math.sqrt((h * s_z) ** 2 - h * h + saddle_height**2)


# ---------------------------------------------------------------- geometry numbers


def frame_geometry(sk: dict[str, SkeletonParam]) -> dict[str, Any]:
    """``FrameGeometry`` parameters for this skeleton."""
    v = {k: p.value for k, p in sk.items()}
    return {
        "stack": v["stack"], "reach": v["reach"], "head_angle": v["head_angle"], "seat_angle": v["seat_angle"],
        "head_tube_length": v["head_tube_length"], "chainstay_length": v["chainstay_length"], "bb_drop": v["bb_drop"],
        "seat_tube_length": v["seat_tube_length"], "fork_a2c": v["fork_a2c"], "fork_offset": v["fork_offset"], "tt_slope": v["tt_slope"],
        "lower_stack": v["lower_stack"], "wheel_bsd": float(v["wheel_bsd"]), "tyre_width": v["tyre_width"],
        "bb_shell_width": int(v["bb_shell_width"]), "rear_axle": v["rear_axle"], "seatpost_d": v["seatpost_d"],
        "material": v["material"], "cs": (v["chainstay_od"], 0.8), "cs_rect": CS_RECT,
        "cs_bend": [tuple(v["cs_bend"][k:k + 2]) for k in range(0, len(v["cs_bend"]), 2)],
        "ss_bend": tuple(v["ss_bend"]) if v.get("ss_bend") else None,
        "st": (28.6, 0.69),  # 27.22 mm bore: a 0.01 mm slip fit on a 27.2 post
        # Envelope details that keep catalog parts clear of the welded frame: the down tube meets the
        # head tube high enough not to foul the lower cup and crown, the BB shell is as fat as the
        # external cups, and the stays meet a wider dropout boss outboard of the hub end caps.
        "dt_offset": 40.0, "tt_offset": TT_OFFSET, "bb_shell_od": 42.0, "dropout_thickness": REAR_DROPOUT_T,
        "stay_end_outset": STAY_END_OUTSET,
    }


def derived_numbers(sk: dict[str, SkeletonParam]) -> dict[str, float]:
    from ...weldment.bike_frame import FrameGeometry, frame_nodes

    v = {k: p.value for k, p in sk.items()}
    nodes, d = frame_nodes(FrameGeometry.model_validate(frame_geometry(sk)))
    wheel_r = v["wheel_bsd"] / 2 + v["tyre_width"]
    out = {k: round(float(x), 3) for k, x in d.items()}
    out["bb_height"] = round(wheel_r - v["bb_drop"], 3)
    out["ground_z"] = round(v["bb_drop"] - wheel_r, 3)
    out["steering_axis_x"] = round(nodes["ht_top"][0], 3)
    return out


# ---------------------------------------------------------------- assembly and product tree


def _port(name, origin=(0, 0, 0), z=(0, 0, 1), x=(1, 0, 0), label="", **contract) -> dict:
    return {"name": name, "origin": list(origin), "z": list(z), "x": list(x), "label": label, "contract": contract}


def _inst(iid, source, generator, params=None, ports=(), **kw) -> dict:
    return {"id": iid, "source": source, "ref": {"generator": generator, "params": params or {}, "ports": list(ports)}, **kw}


COLORS = {"frame": "#1f5fa8", "fork": "#1f5fa8", "headset": "#3a3a3a", "stem": "#2b2b2b", "handlebar": "#2b2b2b",
          "hub": "#b8b8b8", "rim": "#454545", "tyre": "#1a1a1a", "bb": "#7a7a7a", "crankset": "#9a9a9a",
          "seatpost": "#2b2b2b", "saddle": "#5a3b24"}


def assembly_from_skeleton(sk: dict[str, SkeletonParam], name: str = "bicycle") -> AssemblySpec:
    v = {k: p.value for k, p in sk.items()}
    sa = math.radians(v["seat_angle"])
    steer_top = v["lower_stack"] + v["head_tube_length"] + v["upper_stack"] + v["spacer_stack"]
    stem_stack = 40.0
    tyre = {"bsd": int(v["wheel_bsd"]), "width": v["tyre_width"], "rim_flange_height": 6.0}
    rim_inner = 19.0 if v["tyre_width"] < 32 else 23.0 if v["tyre_width"] < 45 else 25.0
    fork_params = {"a2c": v["fork_a2c"], "offset": v["fork_offset"], "steerer_length": steer_top + stem_stack - 3.0,
                   "axle": v["front_axle"], "blade_spread": v["fork_blade_spread"], "material": v["material"],
                   "dropout_thickness": 16.0, "blade_end_outset": 2.0}
    insertion = v["seatpost_length"] - (_clamp_distance(v["saddle_height"], v["seat_angle"]) - v["seat_tube_length"])
    L_post = v["seatpost_length"]
    shell_w = int(v["bb_shell_width"])
    rings = list(v["chainrings"])
    instances = [
        _inst("frame", "weldment", "bike.frame", frame_geometry(sk), grounded=True, color=COLORS["frame"]),
        _inst("fork", "weldment", "bike.fork", fork_params, color=COLORS["fork"], ports=[
            # Steering frame: x maps onto the head tube's lateral port axis, so steering angle 0 points the fork ahead.
            _port("steering", (0, 0, 0), (0, 0, 1), (0, 1, 0), "crown-race seat, steering axis", crown_race_d=30.0),
            _port("stem_seat", (0, 0, steer_top), (0, 0, 1), (1, 0, 0), "stem clamp underside on the steerer",
                  steerer_d=28.6)]),
        _inst("headset_upper", "catalog", "bike.headset_cup", {"position": "upper", "shis": "ZS44"},
              color=COLORS["headset"], part_number="headset_upper_zs44"),
        _inst("headset_lower", "catalog", "bike.headset_cup", {"position": "lower", "shis": "ZS44"},
              color=COLORS["headset"], part_number="headset_lower_zs44"),
        _inst("stem", "catalog", "bike.stem", {"length": v["stem_length"], "angle": v["stem_angle"]}, color=COLORS["stem"]),
        _inst("handlebar", "catalog", "bike.handlebar", {"width": v["bar_width"]}, color=COLORS["handlebar"]),
        _inst("front_hub", "catalog", "bike.hub", {"axle": v["front_axle"]}, color=COLORS["hub"]),
        _inst("front_rim", "catalog", "bike.rim", {"bsd": int(v["wheel_bsd"]), "inner_width": rim_inner},
              color=COLORS["rim"], part_number="rim"),
        _inst("front_tyre", "catalog", "bike.tyre", tyre, color=COLORS["tyre"], part_number="tyre"),
        _inst("rear_hub", "catalog", "bike.hub", {"axle": v["rear_axle"]}, color=COLORS["hub"], ports=[
            _port("cassette", (0, 0, -v["rear_chainline"]), (0, 0, -1), (1, 0, 0), "cassette centre plane",
                  chainline=v["rear_chainline"])]),
        {"id": "rear_rim", "copy_of": "front_rim", "color": COLORS["rim"]},
        {"id": "rear_tyre", "copy_of": "front_tyre", "color": COLORS["tyre"]},
        _inst("bb", "catalog", "bike.bb_bsa", {"shell_width": shell_w, "type": "external_24"}, color=COLORS["bb"]),
        _inst("crankset", "catalog", "bike.crankset", {"crank_length": v["crank_length"], "teeth": rings,
                                                       "chainline": v["chainline"], "q_factor": v["q_factor"]},
              color=COLORS["crankset"]),
        _inst("seatpost", "catalog", "bike.seatpost", {"diameter": v["seatpost_d"], "length": L_post,
                                                       "min_insertion": v["seatpost_min_insertion"]},
              color=COLORS["seatpost"], ports=[
                  _port("seat_tube_axis", (0, 0, 0), (0, 0, 1), (0, 1, 0), "post axis; x lateral", seatpost_d=v["seatpost_d"]),
                  # Clamp frame turned so the saddle sits level with its nose forward (the post leans at the seat angle).
                  _port("saddle_clamp", (0, 0, L_post), (math.cos(sa), 0, math.sin(sa)), (math.sin(sa), 0, -math.cos(sa)),
                        "saddle rail clamp, levelled", rails="7mm round")]),
        _inst("saddle", "catalog", "bike.saddle", {}, color=COLORS["saddle"]),
    ]
    lock = v["steer_lock"]
    # Slider range: from the minimum-insertion mark down 40 mm below the fitted height, but never so deep
    # that the post end nears the BB shell (approx) or the clamp head enters the seat tube.
    deepest = min(v["seat_tube_length"] - 90.0, L_post - 30.0, insertion + 40.0)
    mates = [
        {"a": "frame.head_tube_top", "b": "headset_upper.head_tube_seat", "type": "fixed", "intent": "press_fit"},
        {"a": "frame.head_tube_bottom", "b": "headset_lower.head_tube_seat", "type": "fixed", "intent": "press_fit"},
        {"id": "steering", "a": "frame.head_tube_bottom", "b": "fork.steering", "type": "revolute", "align": "opposed",
         "offset": v["lower_stack"], "limits": [-lock, lock], "intent": "clearance"},
        {"a": "fork.stem_seat", "b": "stem.steerer_clamp", "type": "fixed", "intent": "bolted"},
        {"a": "stem.bar_clamp", "b": "handlebar.stem_clamp", "type": "fixed", "align": "aligned", "intent": "bolted"},
        {"id": "front_wheel", "a": "fork.front_axle", "b": "front_hub.axle", "type": "revolute", "intent": "clearance"},
        # Spokes are not modelled: the rim rides on the hub axis without touching it.
        {"a": "front_hub.axle", "b": "front_rim.hub_axis", "type": "fixed", "align": "aligned", "intent": "clearance"},
        {"a": "front_rim.bead_seat", "b": "front_tyre.rim_seat", "type": "fixed", "align": "aligned", "intent": "contact"},
        {"id": "rear_wheel", "a": "frame.rear_dropout", "b": "rear_hub.axle", "type": "revolute", "intent": "clearance"},
        {"a": "rear_hub.axle", "b": "rear_rim.hub_axis", "type": "fixed", "align": "aligned", "intent": "clearance"},
        {"a": "rear_rim.bead_seat", "b": "rear_tyre.rim_seat", "type": "fixed", "align": "aligned", "intent": "contact"},
        {"a": "frame.bb_shell", "b": "bb.spindle_axis", "type": "fixed", "intent": "bolted"},
        {"id": "cranks", "a": "bb.spindle_axis", "b": "crankset.spindle", "type": "revolute", "limits": [0, 360],
         "intent": "clearance"},
        {"id": "seatpost", "a": "frame.seat_tube_top", "b": "seatpost.seat_tube_axis", "type": "slider",
         "offset": -round(insertion, 3), "limits": [-max(deepest, v["seatpost_min_insertion"]), -v["seatpost_min_insertion"]], "intent": "clearance"},
        {"a": "seatpost.saddle_clamp", "b": "saddle.rail_clamp", "type": "fixed", "intent": "clearance"},
    ]
    return AssemblySpec.model_validate({
        "name": name, "instances": instances, "mates": mates,
        "dof": 5,  # steering, two wheels, cranks, seatpost height (clamped in use, adjustable by design)
        "clearances": [], "tolerances": {"interference_volume": 1.0, "contact_gap": 0.05, "sweep_steps": 9},
    })


def product_tree(asm: AssemblySpec) -> ProductNode:
    def part(pid, name, proc, inst, standard=None):
        return {"id": pid, "name": name, "kind": "part", "procurement": proc, "instances": inst, "standard": standard}

    def sub(sid, name, children):
        return {"id": sid, "name": name, "kind": "subsystem", "children": children}

    tree = {"id": "bicycle", "name": "Bicycle", "kind": "product", "children": [
        sub("frameset", "Frameset", [
            part("frame", "Frame (TIG-welded tube weldment)", "make", ["frame"]),
            part("fork", "Rigid fork (tube weldment)", "make", ["fork"]),
            part("headset", "Headset ZS44/28.6 - ZS44/30", "standard", ["headset_upper", "headset_lower"], "S.H.I.S."),
        ]),
        sub("wheels", "Wheelset", [
            sub("front_wheel", "Front wheel", [
                part("front_hub", "Front hub", "buy", ["front_hub"], "hub OLD"),
                part("front_rim", "Front rim", "standard", ["front_rim"], "ISO 5775"),
                part("front_tyre", "Front tyre", "standard", ["front_tyre"], "ISO 5775 / ETRTO")]),
            sub("rear_wheel", "Rear wheel", [
                part("rear_hub", "Rear hub", "buy", ["rear_hub"], "hub OLD"),
                part("rear_rim", "Rear rim", "standard", ["rear_rim"], "ISO 5775"),
                part("rear_tyre", "Rear tyre", "standard", ["rear_tyre"], "ISO 5775 / ETRTO")]),
        ]),
        sub("drivetrain", "Drivetrain", [
            part("bottom_bracket", "Bottom bracket", "standard", ["bb"], "BSA / ISO 6696"),
            part("crankset", "Crankset", "buy", ["crankset"], "ISO 606 / ISO 4210"),
        ]),
        sub("cockpit", "Cockpit", [
            part("stem", "Stem", "buy", ["stem"], "1-1/8 threadless"),
            part("handlebar", "Handlebar", "buy", ["handlebar"], "bar clamp 31.8"),
        ]),
        sub("contact", "Seating", [
            part("seatpost", "Seatpost", "buy", ["seatpost"], "seatpost 27.2"),
            part("saddle", "Saddle (freeform envelope)", "buy", ["saddle"]),
        ]),
    ]}
    return ProductNode.model_validate(tree)


# Instances that must honour each governing standard (used by ``check_product``).
ROLE_OF = {"bb": ["bb", "frame"], "front_axle": ["front_hub", "fork"], "rear_axle": ["rear_hub", "frame"],
           "seatpost": ["seatpost", "frame"], "bar_clamp": ["handlebar"], "headset": ["headset_upper", "headset_lower"]}

TARGETS = {
    "tyre_clearance_min": 5.0,  # mm, tyre to frame / fork (industry practice 4-6 mm)
    "crank_clearance_min": 2.0,  # mm, crankset to frame over a full turn
    "steer_clearance_min": 0.0,  # mm, steering assembly to frame over the lock range (no contact)
    "toe_reach": 95.0,  # mm, shoe toe ahead of the pedal axle (approx, EU 43 road shoe)
    "toe_overlap_min": 0.0,  # mm; less is a warning, as on many small real bikes
    "standover_min": 20.0,  # mm of crotch clearance over the top tube
    "chainline_tol": 2.5,  # mm, front ring-pack centre vs cassette centre
    "ground_tol": 0.5,  # mm, both tyres touch the ground plane
    "pedal_ground_min": 60.0,  # mm, crank tip above the ground with the crank down
    "min_lock": 30.0,  # deg, the steering stop must allow at least this much each way
}


def spec_from_skeleton(req: Requirements, sk: dict[str, SkeletonParam], name: str | None = None,
                       history: list | None = None) -> ProductSpec:
    sk = derive(sk)
    name = name or f"bicycle_{sk['use_case'].value}_{sk['size'].value.lower()}_{int(sk['wheel_bsd'].value)}"
    asm = assembly_from_skeleton(sk, name)
    return ProductSpec(name=name, template=TEMPLATE_ID, requirements=req, skeleton=sk, tree=product_tree(asm), assembly=asm,
                       targets=dict(TARGETS), derived=derived_numbers(sk), history=list(history or []))


def bicycle_spec(choices: BicycleChoices | dict) -> ProductSpec:
    c = choices if isinstance(choices, BicycleChoices) else BicycleChoices.model_validate(choices)
    req, sk = skeleton_from_choices(c)
    return spec_from_skeleton(req, sk)
