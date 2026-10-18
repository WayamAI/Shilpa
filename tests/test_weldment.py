"""Weldment sub-IR and bicycle frame template: analytic geometry checks."""

import math
from pathlib import Path

import build123d as bd
import pytest

from shilpa.catalog import resolve
from shilpa.contracts.errors import ShilpaError
from shilpa.weldment import WeldmentSpec, build_weldment
from shilpa.weldment.bike_frame import FrameGeometry, ForkGeometry, build_fork, build_frame, frame_nodes

OUT = Path(__file__).resolve().parents[1] / "evals" / "out"


def tee(angle_deg=45.0, R=20.0, r=12.5, wall=1.5, branch_len=280.0):
    a = math.radians(angle_deg)
    return WeldmentSpec(
        params={"h": 300.0, "c": 150.0},
        nodes={"a": (0, 0, 0), "b": (0, 0, "h"), "c": (0, 0, "c"),
               "d": (branch_len * math.sin(a), 0, 150 + branch_len * math.cos(a))},
        members=[{"id": "main", "start_node": "a", "end_node": "b", "profile": {"od": 2 * R, "wall": 2}, "priority": 1},
                 {"id": "branch", "start_node": "c", "end_node": "d", "profile": {"od": 2 * r, "wall": wall}}],
        ports=[{"name": "top", "node": "b", "z": (0, 0, 1)}, {"name": "branch_end", "node": "d", "z_nodes": ("c", "d")}],
    )


def entry(res, mid):
    return next(e for e in res.cut_list if e["id"] == mid)


def test_tube_volumes_before_coping():
    spec = WeldmentSpec(
        nodes={"o": (0, 0, 0), "a": (300, 0, 0), "b": (0, 300, 0), "c": (0, 0, 300)},
        members=[{"id": "round", "start_node": "o", "end_node": "a", "profile": {"od": 30, "wall": 2}},
                 {"id": "taper", "start_node": "o", "end_node": "b", "profile": {"od": 30, "wall": 1, "od_start": 30, "od_end": 16}},
                 {"id": "box", "start_node": "o", "end_node": "c", "profile": {"kind": "rect", "width": 40, "height": 20, "wall": 2}}],
    )
    res = build_weldment(spec)
    assert entry(res, "round")["raw_volume"] == pytest.approx(math.pi * (15**2 - 13**2) * 300, abs=1e-3)
    frustum = lambda r0, r1: math.pi * 300 * (r0 * r0 + r0 * r1 + r1 * r1) / 3
    assert entry(res, "taper")["raw_volume"] == pytest.approx(frustum(15, 8) - frustum(14, 7), abs=1e-3)
    assert entry(res, "box")["raw_volume"] == pytest.approx((40 * 20 - 36 * 16) * 300, abs=1e-3)
    # The highest-ranked member is never cut, so its solid matches the analytic volume.
    assert res.pieces["round"].volume == pytest.approx(entry(res, "round")["raw_volume"], rel=1e-6)


@pytest.mark.parametrize("angle", [45.0, 60.0, 90.0])
def test_cope_ends_on_outer_surface(angle):
    R, r = 20.0, 12.5
    res = build_weldment(tee(angle, R, r), strict=True)
    assert res.ok and res.part.source == "weldment"
    br = entry(res, "branch")
    # Saddle curve of the cope: the branch generator at angle phi meets the main tube (radius R about Z)
    # at axial distance t(phi) = (sqrt(R^2 - r^2 sin^2 phi) - r cos phi cos a) / sin a from the node.
    a = math.radians(angle)
    short = min((math.sqrt(R * R - (r * math.sin(f)) ** 2) - r * math.cos(f) * math.cos(a)) / math.sin(a)
                for f in (i * math.pi / 3600 for i in range(7201)))
    assert br["kept_from"] == pytest.approx(short, abs=0.01)
    assert br["cut_length"] == pytest.approx(br["centreline_length"] - short, abs=0.01)
    start = br["ends"][0]
    assert start["type"] == "cope" and start["against"] == "main"
    assert start["cope_angle_deg"] == pytest.approx(angle, abs=1e-6)
    assert br["ends"][1]["type"] == "square"
    assert br["volume"] < br["raw_volume"]
    # Pieces are disjoint, so they add up to the fused solid; the main tube is untouched.
    assert res.part.solid.volume == pytest.approx(sum(p.volume for p in res.pieces.values()), rel=1e-4)
    assert entry(res, "main")["cut_length"] == pytest.approx(300.0, abs=1e-6)
    assert res.part.port("top").origin == (0.0, 0.0, 300.0)


def test_member_swallowed_by_shell_fails_check():
    spec = WeldmentSpec(
        nodes={"c": (0, 0, 0), "a": (0, 0, -5), "b": (0, 0, 5)},
        shells=[{"id": "sleeve", "node": "c", "axis": (0, 1, 0), "length": 60, "od": 40, "bore": 30}],
        members=[{"id": "stub", "start_node": "a", "end_node": "b", "profile": {"od": 10, "wall": 1}}],
    )
    res = build_weldment(spec)
    assert not res.ok
    assert {c["name"] for c in res.failed()} >= {"member_intact:stub", "positive_length:stub"}
    with pytest.raises(ShilpaError):
        build_weldment(spec, strict=True)


def test_spec_rejects_unknown_nodes_and_bad_walls():
    with pytest.raises(ValueError):
        WeldmentSpec(nodes={"a": (0, 0, 0)}, members=[{"id": "m", "start_node": "a", "end_node": "zz", "profile": {"od": 10, "wall": 1}}])
    with pytest.raises(ValueError):
        WeldmentSpec(nodes={"a": (0, 0, 0), "b": (1, 0, 0)},
                     members=[{"id": "m", "start_node": "a", "end_node": "b", "profile": {"od": 10, "wall": 5}}])


# ---------------------------------------------------------------- bicycle frame


def test_frame_nodes_reproduce_geometry():
    g = FrameGeometry()
    n, d = frame_nodes(g)
    bb, top, bot = n["bb"], n["ht_top"], n["ht_bottom"]
    assert top[0] - bb[0] == pytest.approx(g.reach, abs=0.01)  # reach
    assert top[2] - bb[2] == pytest.approx(g.stack, abs=0.01)  # stack
    ht = [top[i] - bot[i] for i in range(3)]
    assert math.dist(top, bot) == pytest.approx(g.head_tube_length, abs=0.01)
    assert math.degrees(math.atan2(ht[2], -ht[0])) == pytest.approx(g.head_angle, abs=1e-6)
    st = n["st_top"]
    assert math.degrees(math.atan2(st[2], -st[0])) == pytest.approx(g.seat_angle, abs=1e-6)
    assert math.dist(bb, st) == pytest.approx(g.seat_tube_length, abs=0.01)
    ra = n["rear_axle"]
    assert math.dist(bb, ra) == pytest.approx(g.chainstay_length, abs=0.01)
    assert ra[2] - bb[2] == pytest.approx(g.bb_drop, abs=0.01)
    # Top-tube rear node lies on the seat-tube axis and the slope is as asked.
    tr, tf = n["tt_rear"], n["tt_front"]
    assert abs(tr[0] * st[2] - tr[2] * st[0]) / math.hypot(*st[::2]) < 1e-9
    assert math.degrees(math.atan2(tf[2] - tr[2], tf[0] - tr[0])) == pytest.approx(g.tt_slope, abs=1e-9)
    # Independent front-end computation: wheelbase and trail.
    ha = math.radians(g.head_angle)
    fz = g.stack - (g.head_tube_length + g.lower_stack + g.fork_a2c) * math.sin(ha) + g.fork_offset * math.cos(ha)
    fx = g.reach + (g.head_tube_length + g.lower_stack + g.fork_a2c) * math.cos(ha) + g.fork_offset * math.sin(ha)
    assert n["front_axle"][0] == pytest.approx(fx, abs=0.01) and n["front_axle"][2] == pytest.approx(fz, abs=0.01)
    assert d["wheelbase"] == pytest.approx(fx + math.sqrt(g.chainstay_length**2 - g.bb_drop**2), abs=0.01)
    assert d["trail"] == pytest.approx(((g.wheel_bsd / 2 + g.tyre_width) * math.cos(ha) - g.fork_offset) / math.sin(ha), abs=0.01)
    assert 990 < d["wheelbase"] < 1040 and 55 < d["trail"] < 70  # plausible road/gravel numbers


def test_frame_rejects_short_seat_tube():
    with pytest.raises(ShilpaError):
        frame_nodes(FrameGeometry(seat_tube_length=400))


def test_frame_weldment_builds_with_ports_and_cut_list():
    res = build_frame()
    assert res.ok, res.failed()
    part = res.part
    assert len(part.solid.solids()) == 1 and part.solid.is_valid
    ids = {e["id"] for e in res.cut_list}
    assert ids == {"head_tube", "bb_shell", "dropout_boss_l", "dropout_boss_r", "seat_tube", "down_tube", "top_tube",
                   "chainstay_l", "chainstay_r", "seatstay_l", "seatstay_r"}
    for e in res.cut_list:
        assert 0 < e["cut_length"] <= e["centreline_length"] + 1e-6
    # Shells are never coped; tubes end on the shells they join.
    assert entry(res, "head_tube")["cut_length"] == pytest.approx(140.0, abs=1e-6)
    tt = entry(res, "top_tube")
    assert [x["against"] for x in tt["ends"]] == ["head_tube", "seat_tube"]
    g = FrameGeometry()
    assert tt["ends"][0]["cope_angle_deg"] == pytest.approx(g.head_angle + g.tt_slope, abs=1e-6)
    assert tt["ends"][1]["cope_angle_deg"] == pytest.approx(g.seat_angle + g.tt_slope, abs=1e-6)
    st = entry(res, "seat_tube")
    # Square T onto the 40 mm BB shell: the cope's nearest point is sqrt(R^2 - r^2) from the shell axis.
    assert st["kept_from"] == pytest.approx(math.sqrt(20.0**2 - 14.3**2), abs=0.01)
    assert entry(res, "chainstay_l")["ends"][0]["against"] == "bb_shell"
    assert part.solid.volume == pytest.approx(sum(p.volume for p in res.pieces.values()), rel=1e-4)
    assert 1500 < part.meta["mass_g"] < 3000  # steel frame envelope, no dropout plates or bridges

    n, _ = frame_nodes(g)
    assert part.port("head_tube_top").origin == pytest.approx(n["ht_top"])
    assert part.port("bb_shell").contract == {"standard": "BSA", "shell_width": 68, "thread": "1.370x24TPI",
                                              "drive_side_thread": "LH", "bore": 34.8}
    assert part.port("head_tube_bottom").contract["cup_bore"] == 44.0
    assert part.port("seat_tube_top").contract == {"seatpost_d": 27.2}
    assert part.port("rear_dropout").contract["axle"] == "12x142"
    assert part.port("rear_dropout").origin == pytest.approx(n["rear_axle"])
    z = part.port("head_tube_top").z
    assert math.degrees(math.atan2(z[2], -z[0])) == pytest.approx(g.head_angle, abs=1e-6)

    OUT.mkdir(parents=True, exist_ok=True)
    assert bd.export_step(part.solid, str(OUT / "bike_frame.step"))
    assert (OUT / "bike_frame.step").stat().st_size > 10_000


def test_frame_ports_match_catalog_contracts():
    part = build_frame().part
    shell = resolve("bike.bb_bsa", {"shell_width": 68})
    assert shell.port("drive_shell_seat").contract["shell_width"] == part.port("bb_shell").contract["shell_width"]
    cup = resolve("bike.headset_cup", {"position": "lower", "shis": "ZS44"})
    assert cup.port("head_tube_seat").contract["cup_bore"] == part.port("head_tube_bottom").contract["cup_bore"]
    post = resolve("bike.seatpost", {"diameter": 27.2})
    assert post.port("post_axis").contract["seatpost_d"] == part.port("seat_tube_top").contract["seatpost_d"]
    hub = resolve("bike.hub", {"axle": "12x142"})
    for k in ("axle", "old", "axle_d"):
        assert hub.port("axle").contract[k] == part.port("rear_dropout").contract[k]


def test_fork_weldment():
    g = ForkGeometry()
    res = build_fork(g)
    assert res.ok, res.failed()
    part = res.part
    assert part.port("front_axle").origin == pytest.approx((g.offset, 0.0, -g.a2c))
    assert part.port("crown_race").contract["crown_race_d"] == 30.0
    assert part.port("front_axle").contract["axle"] == "12x100"
    steerer = entry(res, "steerer")
    assert steerer["cut_length"] == pytest.approx(g.steerer_length, abs=0.01)  # ends on the crown top face
    assert all(x["against"] == "crown" for x in (entry(res, "blade_l")["ends"][0], entry(res, "blade_r")["ends"][0]))
    bb = part.solid.bounding_box()
    assert bb.min.Z == pytest.approx(-g.a2c - g.dropout_od / 2, abs=0.01)
