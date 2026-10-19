"""Diamond bicycle frame and fork as weldments (roadmap: bicycle decomposition).

Frame coordinates: origin at the bottom-bracket centre, +X forward, +Z up, +Y to
the rider's left (right-handed), so the drive side is -Y. All angles in degrees
from horizontal.

Skeleton formulas (``frame_nodes``):

* Steering axis, unit vector pointing up the head tube:
  ``u = (-cos HA, 0, sin HA)``. Its forward perpendicular in the XZ plane is
  ``n = (sin HA, 0, cos HA)``.
* Head-tube top ``T = (reach, 0, stack)`` (stack and reach are, by definition,
  the vertical and horizontal distances from the BB centre to the top centre of
  the head tube). Head-tube bottom ``B = T - HTL * u``.
* Crown-race seat ``C = B - lower_stack * u``. Front axle
  ``F = C - a2c * u + offset * n``; ``a2c`` here is the axle-to-crown length
  measured parallel to the steering axis (some makers quote the straight-line
  distance, which differs by ``a2c - sqrt(a2c^2 + offset^2)``, about 3 mm).
* Rear axle ``R = (-sqrt(cs^2 - drop^2), 0, drop)``: chainstay length is the
  straight BB-to-axle distance and BB drop is how far the BB sits below the
  rear axle.
* Seat-tube direction ``s = (-cos SA, 0, sin SA)``; seat-tube top
  ``S = st_length * s`` (centre-to-top).
* Top tube: front node ``T - tt_offset * u``; rear node where a line from there,
  sloping down toward the rear at ``tt_slope``, meets the seat-tube axis.
* Down tube front node ``B + dt_offset * u``, with ``dt_offset`` raised when
  needed to ``(r_dt + R_ht cos theta) / sin theta + 3 mm`` (``theta`` the
  down-tube-to-steering-axis angle) so the down tube's lower contour meets
  the head tube above its bottom face and the lower cup seat stays a full
  annulus (``dt_offset_min``).
* Derived: wheelbase ``F.x - R.x``; front centre ``|F - BB|`` in XZ; trail
  ``(wheel_radius * cos HA - offset) / sin HA`` measured on level ground at the
  front axle height; ``front_axle_level_error = F.z - R.z`` (zero when the
  fork length and BB drop agree with equal wheels).

Joint layout: every coped end node sits on the axis of the tube it joins
(seat stays and chainstays are spread laterally by less than the joined radius
minus their own), so the weldment builder's coping always closes. Rear
dropouts are modelled as thru-axle bosses (short sleeves) just outside the hub's
over-locknut width, not as plates.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..contracts.errors import ErrorCode, ShilpaError
from .build import WeldmentResult, build_weldment
from .spec import WeldmentSpec

Vec3 = tuple[float, float, float]

# Head-tube cup bores by S.H.I.S. code (mm). ZS44 = zero-stack cup pressed into a 44 mm bore.
SHIS_BORE = {"ZS44": 44.0, "EC34": 34.0}
# Rear axle standards: over-locknut / dropout spacing and axle diameter (mm).
REAR_AXLES = {"12x142": (142.0, 12.0), "135x10qr": (135.0, 10.0)}
FRONT_AXLES = {"12x100": (100.0, 12.0), "100x9qr": (100.0, 9.0)}


class FrameGeometry(BaseModel):
    """Size-template parameters for a diamond frame (defaults: a ~54 cm steel road/gravel frame)."""

    model_config = ConfigDict(extra="forbid")

    stack: float = Field(560.0, gt=0)
    reach: float = Field(380.0, gt=0)
    head_angle: float = Field(71.5, gt=45, lt=90)
    seat_angle: float = Field(73.5, gt=45, lt=90)
    head_tube_length: float = Field(140.0, gt=0)
    chainstay_length: float = Field(425.0, gt=0)
    bb_drop: float = Field(70.0, ge=0)
    seat_tube_length: float = Field(530.0, gt=0)  # BB centre to seat-tube top
    tt_slope: float = Field(6.0, ge=-10, le=25)  # top tube drops this much toward the rear
    tt_offset: float = Field(20.0, ge=0)  # top-tube axis below head-tube top, along the steering axis
    # Down-tube axis above head-tube bottom; raised to ``dt_offset_min`` (tube OD, head-tube OD and the
    # down-tube angle) when smaller, so the down tube never breaks through the lower cup seat face.
    dt_offset: float = Field(25.0, ge=0)
    ss_offset: float = Field(18.0, ge=0)  # seat-stay node below the top-tube node, along the seat tube
    # Fork / front end (used for front axle, wheelbase and trail)
    fork_a2c: float = Field(395.0, gt=0)
    fork_offset: float = Field(50.0, ge=0)
    lower_stack: float = Field(3.0, ge=0)  # lower cup + crown race stack height below the head tube
    wheel_bsd: float = Field(622.0, gt=0)
    tyre_width: float = Field(32.0, gt=0)
    # Interfaces
    bb_shell_width: Literal[68, 73] = 68
    rear_axle: Literal["12x142", "135x10qr"] = "12x142"
    seatpost_d: float = 27.2
    headset: Literal["ZS44"] = "ZS44"
    # Tubes (OD, wall); stays taper from od to *_end_od at the dropout
    material: str = "chromoly"
    tt: tuple[float, float] = (28.6, 0.9)
    dt: tuple[float, float] = (31.8, 0.9)
    st: tuple[float, float] = (28.6, 0.7)  # 28.6 - 2*0.7 = 27.2 mm seatpost bore
    ss: tuple[float, float] = (16.0, 0.8)
    ss_end_od: float = 12.0
    cs: tuple[float, float] = (22.0, 0.8)
    cs_end_od: float = 12.0
    # Bent chainstays (chainring and tyre clearance): each ``(back, out)`` adds a bend node ``back`` mm
    # behind the BB centre and ``out`` mm from the frame plane (height on the straight BB-to-dropout
    # line), splitting each chainstay into straight members. Empty keeps straight stays.
    cs_bend: list[tuple[float, float]] = Field(default_factory=list, max_length=4)
    # Ovalised chainstay section (lateral width, vertical height, wall) for the pieces ahead of the last
    # bend, where the stay squeezes between chainring and tyre. None keeps them round ``cs``.
    cs_rect: tuple[float, float, float] | None = None
    # Bent seat stays (tyre clearance under the seat cluster): ``(along, out)`` puts a bend node ``along``
    # mm from the dropout end on the straight stay line, ``out`` mm from the frame plane. None keeps them straight.
    ss_bend: tuple[float, float] | None = None
    head_tube_od: float = 50.0
    bb_shell_od: float = 40.0
    bb_shell_bore: float = 34.8  # BSA 1.370" thread major diameter (approximate bore)
    dropout_od: float = 30.0
    dropout_thickness: float = 12.0
    # Stays end this far outboard of the dropout-boss centre, so they meet the boss outside the hub's
    # end caps instead of converging on the axle line (0 keeps the original layout).
    stay_end_outset: float = Field(0.0, ge=0)

    @model_validator(mode="after")
    def _sane(self):
        if self.bb_drop >= self.chainstay_length:
            raise ValueError("bb_drop must be smaller than chainstay_length")
        if self.st[0] - 2 * self.st[1] < self.seatpost_d - 1e-6:
            raise ValueError(f"seat tube bore {self.st[0] - 2 * self.st[1]:g} is smaller than seatpost {self.seatpost_d:g}")
        return self


def _add(a: Vec3, b: Vec3, k: float = 1.0) -> Vec3:
    return (a[0] + k * b[0], a[1] + k * b[1], a[2] + k * b[2])


def frame_nodes(g: FrameGeometry) -> tuple[dict[str, Vec3], dict[str, float]]:
    """Skeleton nodes and derived geometry numbers for ``g`` (see module docstring)."""
    ha, sa = math.radians(g.head_angle), math.radians(g.seat_angle)
    u = (-math.cos(ha), 0.0, math.sin(ha))
    n = (math.sin(ha), 0.0, math.cos(ha))
    s = (-math.cos(sa), 0.0, math.sin(sa))

    bb = (0.0, 0.0, 0.0)
    ht_top = (g.reach, 0.0, g.stack)
    ht_bottom = _add(ht_top, u, -g.head_tube_length)
    crown = _add(ht_bottom, u, -g.lower_stack)
    front_axle = _add(_add(crown, u, -g.fork_a2c), n, g.fork_offset)
    rear_axle = (-math.sqrt(g.chainstay_length**2 - g.bb_drop**2), 0.0, g.bb_drop)
    st_top = _add(bb, s, g.seat_tube_length)

    tt_front = _add(ht_top, u, -g.tt_offset)
    beta = math.radians(g.tt_slope)
    d = (-math.cos(beta), 0.0, -math.sin(beta))
    # Solve lam * s = tt_front + t * d in X and Z (Cramer's rule).
    det = s[0] * (-d[2]) - s[2] * (-d[0])
    lam = (tt_front[0] * (-d[2]) - tt_front[2] * (-d[0])) / det
    tt_rear = _add(bb, s, lam)
    if lam + g.tt[0] / 2 > g.seat_tube_length:
        raise ShilpaError(ErrorCode.PRECONDITION_FAILED,
                          f"top tube meets the seat tube {lam:.1f} mm up; seat_tube_length {g.seat_tube_length:g} is too short",
                          field="seat_tube_length")
    dt_off = dt_offset_effective(g, ht_bottom, u)
    dt_front = _add(ht_bottom, u, dt_off)
    ss_top = _add(bb, s, lam - g.ss_offset)

    old, _ = REAR_AXLES[g.rear_axle]
    y_do = old / 2 + g.dropout_thickness / 2  # dropout boss centre, just outside the hub
    ss_spread = max(0.0, g.st[0] / 2 - g.ss[0] / 2 - 0.5)
    cs_width = g.cs_rect[0] if g.cs_rect and g.cs_bend else g.cs[0]
    cs_spread = g.bb_shell_width / 2 - cs_width / 2 - 3.0

    nodes = {
        "bb": bb,
        "ht_top": ht_top,
        "ht_bottom": ht_bottom,
        "crown_race": crown,
        "front_axle": front_axle,
        "rear_axle": rear_axle,
        "st_top": st_top,
        "tt_front": tt_front,
        "tt_rear": tt_rear,
        "dt_front": dt_front,
        "ss_top_l": (ss_top[0], ss_spread, ss_top[2]),
        "ss_top_r": (ss_top[0], -ss_spread, ss_top[2]),
        "cs_bb_l": (0.0, cs_spread, 0.0),
        "cs_bb_r": (0.0, -cs_spread, 0.0),
        "dropout_l": (rear_axle[0], y_do, rear_axle[2]),
        "dropout_r": (rear_axle[0], -y_do, rear_axle[2]),
    }
    if g.stay_end_outset > 0:
        for side, sign in (("l", 1.0), ("r", -1.0)):
            nodes[f"stay_end_{side}"] = (rear_axle[0], sign * (y_do + g.stay_end_outset), rear_axle[2])
    for side, sign in (("l", 1.0), ("r", -1.0)):
        a, b = nodes[f"cs_bb_{side}"], nodes[_stay_end(g, side)]
        prev = a
        n = len(g.cs_bend)
        for k, (back, out) in enumerate(g.cs_bend):
            bend = (-back, sign * out, a[2] + back / -b[0] * (b[2] - a[2]))
            nodes[f"cs_bend{k}_{side}"] = bend
            # A piece followed by a round one runs a little past the bend so the round end disc lands inside
            # it (a closed mitre rather than two discs touching along a line). Two box sections meet square:
            # an overrun would slice a sliver off the next box.
            ext = 0.0 if g.cs_rect and k < n - 1 else g.cs[0] / 2
            d = (bend[0] - prev[0], bend[1] - prev[1], bend[2] - prev[2])
            nodes[f"cs_bend{k}_{side}_x"] = _add(bend, d, ext / math.sqrt(sum(c * c for c in d)))
            prev = bend
    if g.ss_bend is not None:
        along, out = g.ss_bend
        for side, sign in (("l", 1.0), ("r", -1.0)):
            top, end = nodes[f"ss_top_{side}"], nodes[_stay_end(g, side)]
            d = (top[0] - end[0], top[1] - end[1], top[2] - end[2])
            t = along / math.sqrt(sum(c * c for c in d))
            bend = (end[0] + t * d[0], sign * out, end[2] + t * d[2])
            # The two pieces meet square at the bend: an overrun stub here (as on the chainstays) makes
            # OCCT's fuse of the whole frame fail for these shallow kinks.
            nodes[f"ss_bend_{side}"] = bend
    wheel_r = g.wheel_bsd / 2 + g.tyre_width
    derived = {
        "wheelbase": front_axle[0] - rear_axle[0],
        "front_center": math.hypot(front_axle[0], front_axle[2]),
        "trail": (wheel_r * math.cos(ha) - g.fork_offset) / math.sin(ha),
        "front_axle_level_error": front_axle[2] - rear_axle[2],
        "top_tube_on_seat_tube": lam,
        "effective_top_tube": g.reach + g.stack / math.tan(sa),  # horizontal, at head-tube top height
        "wheel_radius": wheel_r,
        "dt_offset": dt_off,
    }
    return nodes, derived


DT_BOTTOM_MARGIN = 3.0  # mm of intact head-tube wall (weld toe) between the down tube and the bottom face


def dt_offset_min(g: FrameGeometry, theta: float) -> float:
    """Smallest down-tube offset (along the steering axis, above the head-tube bottom) that keeps the
    down tube clear of the head-tube bottom face.

    In the frame plane the down tube's lower contour runs parallel to its axis at ``r = dt_od / 2`` and
    meets the head tube's outer surface (``R = head_tube_od / 2`` from the steering axis) a distance
    ``(r + R cos theta) / sin theta`` below the down-tube node, where ``theta`` is the angle between the
    down tube (pointing up to the head tube) and the steering axis. Nearer the bore the contour is higher,
    and off the frame plane the tube surface is higher still, so this point is the lowest one.
    """
    r, R = g.dt[0] / 2, g.head_tube_od / 2
    return (r + R * math.cos(theta)) / math.sin(theta) + DT_BOTTOM_MARGIN


def dt_offset_effective(g: FrameGeometry, ht_bottom: Vec3, u: Vec3) -> float:
    """``g.dt_offset``, raised to ``dt_offset_min`` when the down tube would break through the head-tube
    bottom face (splitting the lower cup's seat annulus). The angle depends on the node, so iterate."""
    off = g.dt_offset
    for _ in range(4):
        front = _add(ht_bottom, u, off)
        length = math.sqrt(sum(c * c for c in front))
        theta = math.acos(max(-1.0, min(1.0, sum(a * b for a, b in zip(front, u)) / length)))
        need = dt_offset_min(g, theta)
        if off >= need - 1e-9:
            return off
        off = need
    return off


def _stay_end(g: FrameGeometry, side: str) -> str:
    return f"stay_end_{side}" if g.stay_end_outset > 0 else f"dropout_{side}"


def _seatstays(g: FrameGeometry, tube) -> list[dict]:
    m = g.material
    if g.ss_bend is None:
        return [{"id": f"seatstay_{s}", "start_node": f"ss_top_{s}", "end_node": _stay_end(g, s), "profile": tube(g.ss, g.ss_end_od),
                 "priority": 0, "material": m} for s in ("l", "r")]
    out = []
    for s in ("l", "r"):
        out.append({"id": f"seatstay_{s}", "start_node": f"ss_top_{s}", "end_node": f"ss_bend_{s}", "profile": tube(g.ss),
                    "priority": 0, "material": m})
        out.append({"id": f"seatstay_{s}_2", "start_node": f"ss_bend_{s}", "end_node": _stay_end(g, s),
                    "profile": tube(g.ss, g.ss_end_od), "priority": 0, "material": m})
    return out


def _chainstays(g: FrameGeometry, tube) -> list[dict]:
    m = g.material
    out = []
    n = len(g.cs_bend or [])
    for s in ("l", "r"):
        starts = [f"cs_bb_{s}"] + [f"cs_bend{k}_{s}" for k in range(n)]
        ends = [f"cs_bend{k}_{s}_x" for k in range(n)] + [_stay_end(g, s)]
        for k, (a, b) in enumerate(zip(starts, ends)):
            if k == n:
                prof = tube(g.cs, g.cs_end_od)
            elif g.cs_rect:
                prof = {"kind": "rect", "width": g.cs_rect[0], "height": g.cs_rect[1], "wall": g.cs_rect[2], "up": (0, 0, 1)}
            else:
                prof = tube(g.cs)
            out.append({"id": f"chainstay_{s}" + (f"_{k + 1}" if k else ""), "start_node": a, "end_node": b,
                        "profile": prof, "priority": 1, "material": m})
    return out


def frame_spec(g: FrameGeometry | None = None) -> WeldmentSpec:
    g = g or FrameGeometry()
    nodes, derived = frame_nodes(g)
    ha = math.radians(g.head_angle)
    u = (-math.cos(ha), 0.0, math.sin(ha))
    old, axle_d = REAR_AXLES[g.rear_axle]
    cup = SHIS_BORE[g.headset]

    def tube(od_wall, end_od=None):
        od, wall = od_wall
        return {"od": od, "wall": wall, **({"od_start": od, "od_end": end_od} if end_od else {})}

    m = g.material
    members = [
        {"id": "seat_tube", "start_node": "bb", "end_node": "st_top", "profile": tube(g.st), "priority": 3, "material": m},
        {"id": "down_tube", "start_node": "bb", "end_node": "dt_front", "profile": tube(g.dt), "priority": 2, "material": m},
        {"id": "top_tube", "start_node": "tt_front", "end_node": "tt_rear", "profile": tube(g.tt), "priority": 1, "material": m},
        *_chainstays(g, tube),
        *_seatstays(g, tube),
    ]
    shells = [
        {"id": "head_tube", "start_node": "ht_bottom", "end_node": "ht_top", "od": g.head_tube_od, "bore": cup, "material": m},
        {"id": "bb_shell", "node": "bb", "axis": (0.0, 1.0, 0.0), "length": float(g.bb_shell_width),
         "od": g.bb_shell_od, "bore": g.bb_shell_bore, "material": m},
        {"id": "dropout_boss_l", "node": "dropout_l", "axis": (0.0, 1.0, 0.0), "length": g.dropout_thickness,
         "od": g.dropout_od, "bore": axle_d, "material": m},
        {"id": "dropout_boss_r", "node": "dropout_r", "axis": (0.0, 1.0, 0.0), "length": g.dropout_thickness,
         "od": g.dropout_od, "bore": axle_d, "material": m},
    ]
    ports = [
        {"name": "bb_shell", "node": "bb", "z": (0.0, -1.0, 0.0), "x": (1.0, 0.0, 0.0),
         "label": "BB shell axis, z toward the drive side",
         "contract": {"standard": "BSA", "shell_width": g.bb_shell_width, "thread": "1.370x24TPI",
                      "drive_side_thread": "LH", "bore": g.bb_shell_bore}},
        {"name": "head_tube_top", "node": "ht_top", "z": u, "x": (0.0, 1.0, 0.0), "label": "upper headset cup seat",
         "contract": {"headset": "1-1/8 threadless", "shis": f"{g.headset}/28.6", "cup_bore": cup, "steerer_d": 28.6}},
        {"name": "head_tube_bottom", "node": "ht_bottom", "z": tuple(-c for c in u), "x": (0.0, 1.0, 0.0),
         "label": "lower headset cup seat",
         "contract": {"headset": "1-1/8 threadless", "shis": f"{g.headset}/30", "cup_bore": cup, "crown_race_d": 30.0}},
        {"name": "seat_tube_top", "node": "st_top", "z_nodes": ("bb", "st_top"), "x": (0.0, 1.0, 0.0),
         "label": "seatpost entry", "contract": {"seatpost_d": g.seatpost_d}},
        {"name": "rear_dropout", "node": "rear_axle", "z": (0.0, 1.0, 0.0), "x": (1.0, 0.0, 0.0),
         "label": "rear axle centre between dropouts",
         "contract": {"axle": g.rear_axle, "old": old, "axle_d": axle_d}},
    ]
    return WeldmentSpec(
        name="bike_frame",
        nodes=nodes,
        members=members,
        shells=shells,
        ports=ports,
        meta={"template": "diamond_frame", "geometry": g.model_dump(), "derived": {k: round(v, 3) for k, v in derived.items()},
              "skeleton": {k: nodes[k] for k in ("front_axle", "rear_axle", "crown_race")}},
    )


def build_frame(g: FrameGeometry | None = None, strict: bool = True) -> WeldmentResult:
    return build_weldment(frame_spec(g), strict=strict)


# ---------------------------------------------------------------- fork


class ForkGeometry(BaseModel):
    """Straight-bladed, rigid fork. Defaults match ``FrameGeometry`` (395 mm a2c, 50 mm offset)."""

    model_config = ConfigDict(extra="forbid")

    a2c: float = Field(395.0, gt=0)  # parallel to the steering axis, crown-race seat to axle
    offset: float = Field(50.0, ge=0)
    steerer_length: float = Field(280.0, gt=0)  # above the crown-race seat
    steerer: tuple[float, float] = (28.6, 1.8)  # 1-1/8"
    axle: Literal["12x100", "100x9qr"] = "12x100"
    blade_od: float = 28.0
    blade_end_od: float = 14.0
    blade_wall: float = 1.0
    blade_spread: float = 48.0  # blade centre from the fork plane at the crown
    crown_depth: float = 40.0  # fore-aft
    crown_height: float = 25.0
    crown_wall: float = 2.5
    dropout_od: float = 26.0
    dropout_thickness: float = 14.0
    blade_end_outset: float = Field(0.0, ge=0)  # like FrameGeometry.stay_end_outset
    material: str = "chromoly"


def fork_spec(g: ForkGeometry | None = None) -> WeldmentSpec:
    """Fork in its own frame: crown-race seat at the origin, steering axis +Z, +X forward, +Y left."""
    g = g or ForkGeometry()
    old, axle_d = FRONT_AXLES[g.axle]
    zc = -g.crown_height / 2
    half_crown = g.blade_spread + g.blade_od / 2 + 2.0
    y_do = old / 2 + g.dropout_thickness / 2
    nodes = {
        "crown_race": (0.0, 0.0, 0.0),
        "crown_c": (0.0, 0.0, zc),
        "crown_l": (0.0, half_crown, zc),
        "crown_r": (0.0, -half_crown, zc),
        "blade_top_l": (0.0, g.blade_spread, zc),
        "blade_top_r": (0.0, -g.blade_spread, zc),
        "steerer_top": (0.0, 0.0, g.steerer_length),
        "front_axle": (g.offset, 0.0, -g.a2c),
        "dropout_l": (g.offset, y_do, -g.a2c),
        "dropout_r": (g.offset, -y_do, -g.a2c),
    }
    end = {"l": "dropout_l", "r": "dropout_r"}
    if g.blade_end_outset > 0:
        for side, sign in (("l", 1.0), ("r", -1.0)):
            end[side] = f"blade_end_{side}"
            nodes[end[side]] = (g.offset, sign * (y_do + g.blade_end_outset), -g.a2c)
    blade = {"od": g.blade_od, "wall": g.blade_wall, "od_start": g.blade_od, "od_end": g.blade_end_od}
    m = g.material
    members = [
        {"id": "crown", "start_node": "crown_r", "end_node": "crown_l", "priority": 2, "material": m,
         "profile": {"kind": "rect", "width": g.crown_depth, "height": g.crown_height, "wall": g.crown_wall, "up": (0, 0, 1)}},
        {"id": "steerer", "start_node": "crown_c", "end_node": "steerer_top", "priority": 1, "material": m,
         "profile": {"od": g.steerer[0], "wall": g.steerer[1]}},
        {"id": "blade_l", "start_node": "blade_top_l", "end_node": end["l"], "profile": blade, "material": m},
        {"id": "blade_r", "start_node": "blade_top_r", "end_node": end["r"], "profile": blade, "material": m},
    ]
    shells = [
        {"id": f"dropout_boss_{side}", "node": f"dropout_{side}", "axis": (0.0, 1.0, 0.0), "length": g.dropout_thickness,
         "od": g.dropout_od, "bore": axle_d, "material": m}
        for side in ("l", "r")
    ]
    ports = [
        {"name": "crown_race", "node": "crown_race", "z": (0.0, 0.0, 1.0), "x": (1.0, 0.0, 0.0),
         "label": "crown-race seat, steering axis up",
         "contract": {"headset": "1-1/8 threadless", "steerer_d": g.steerer[0], "crown_race_d": 30.0}},
        {"name": "steerer_top", "node": "steerer_top", "z": (0.0, 0.0, 1.0), "x": (1.0, 0.0, 0.0),
         "label": "steerer top", "contract": {"steerer_d": g.steerer[0]}},
        {"name": "front_axle", "node": "front_axle", "z": (0.0, 1.0, 0.0), "x": (1.0, 0.0, 0.0),
         "label": "front axle centre between dropouts", "contract": {"axle": g.axle, "old": old, "axle_d": axle_d}},
    ]
    return WeldmentSpec(name="bike_fork", nodes=nodes, members=members, shells=shells, ports=ports,
                        meta={"template": "rigid_fork", "geometry": g.model_dump()})


def build_fork(g: ForkGeometry | None = None, strict: bool = True) -> WeldmentResult:
    return build_weldment(fork_spec(g), strict=strict)


def export_demo(out_dir) -> dict[str, str]:
    """Write the default frame and fork as STEP files (for visual inspection)."""
    from pathlib import Path

    import build123d as bd

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, res in (("bike_frame", build_frame()), ("bike_fork", build_fork())):
        path = out / f"{name}.step"
        bd.export_step(res.part.solid, str(path))
        paths[name] = str(path)
    return paths


if __name__ == "__main__":  # uv run python -m shilpa.weldment.bike_frame [out_dir]
    import sys

    print(export_demo(sys.argv[1] if len(sys.argv) > 1 else "var/weldment"))
