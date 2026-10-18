"""Standard-parts catalog: registry, dimensions against the standards, ports and contracts."""

import math

import pytest

from shilpa.catalog import list_generators, resolve
from shilpa.catalog.bicycle import pitch_diameter
from shilpa.contracts.errors import ErrorCode, ShilpaError
from shilpa.contracts.ports import BuiltPart

NAMES = {g["name"] for g in list_generators()}


def size(part):
    bb = part.solid.bounding_box()
    return bb, (bb.size.X, bb.size.Y, bb.size.Z)


def test_registry_lists_schemas():
    assert {"iso4762_socket_head_cap_screw", "iso4032_hex_nut", "iso7089_washer", "deep_groove_ball_bearing",
            "bike.bb_shell_bsa", "bike.bb_bsa", "bike.headset_cup", "bike.steerer", "bike.hub", "bike.rim", "bike.tyre",
            "bike.seatpost", "bike.handlebar", "bike.stem", "bike.crankset", "bike.saddle"} <= NAMES
    for g in list_generators():
        assert g["params"]["type"] == "object" and "material" in g["params"]["properties"]
        assert g["standard"]


@pytest.mark.parametrize("name", sorted(NAMES))
def test_every_generator_builds_with_defaults(name):
    part = resolve(name, {})
    assert isinstance(part, BuiltPart) and part.source == "catalog"
    assert part.solid.is_valid and len(part.solid.solids()) == 1
    assert part.ports and {"standard", "size", "designation", "generator"} <= set(part.meta)


def test_errors_are_typed():
    with pytest.raises(ShilpaError) as e:
        resolve("no.such.part", {})
    assert e.value.code == ErrorCode.UNSUPPORTED_OPERATION
    for name, params in [("iso4762_socket_head_cap_screw", {"size": "M7"}),
                         ("iso4762_socket_head_cap_screw", {"size": "M3", "length": 80}),
                         ("bike.rim", {"bsd": 600}), ("bike.crankset", {"teeth": [70]}), ("bike.hub", {"bogus": 1})]:
        with pytest.raises(ShilpaError) as e:
            resolve(name, params)
        assert e.value.code == ErrorCode.INVALID_PARAMETER


# ---------------------------------------------------------------- fasteners


@pytest.mark.parametrize("sz,dk", [("M3", 5.5), ("M6", 10.0), ("M12", 18.0)])
def test_cap_screw_geometry_and_ports(sz, dk):
    L = 25.0
    part = resolve("iso4762_socket_head_cap_screw", {"size": sz, "length": L, "material": "steel"})
    bb, _ = size(part)
    d = float(sz[1:])
    assert bb.min.Z == pytest.approx(-L, abs=1e-6)
    assert bb.max.Z == pytest.approx(d, abs=1e-3)  # ISO 4762 head height k = d
    assert part.meta["head_d"] == pytest.approx(dk, abs=0.3)  # dk (bd_warehouse tables the knurled max)
    seat, tip = part.port("head_seat"), part.port("thread_tip")
    assert seat.origin == (0, 0, 0) and seat.z == (0, 0, -1)
    assert tip.origin == (0, 0, -L)
    assert seat.contract["thread"].startswith(sz + "x")
    assert part.meta["mass_g"] == pytest.approx(part.solid.volume * 7.85 / 1000, abs=1e-3)
    assert part.meta["designation"] == f"ISO 4762 {sz}x25"


def test_nut_and_washer_dimensions():
    nut = resolve("iso4032_hex_nut", {"size": "M8"})
    assert nut.meta["width_across_flats"] == pytest.approx(13.0, abs=0.01)  # ISO 4032 M8: s = 13
    assert nut.meta["thickness"] == pytest.approx(6.8, abs=0.01)  # m = 6.8
    assert nut.port("face_b").origin[2] == pytest.approx(6.8, abs=0.01)
    w = resolve("iso7089_washer", {"size": "M6"})
    assert (w.meta["inner_d"], w.meta["outer_d"]) == (6.4, 12.0)  # ISO 7089 M6: d1 6.4, d2 12
    assert w.solid.volume == pytest.approx(math.pi / 4 * (12**2 - 6.4**2) * w.meta["thickness"], rel=1e-3)


# ---------------------------------------------------------------- bearings


@pytest.mark.parametrize("des,dims", [("608", (8, 22, 7)), ("6003", (17, 35, 10)), ("6204", (20, 47, 14))])
def test_bearing_envelope(des, dims):
    d, D, B = dims
    part = resolve("deep_groove_ball_bearing", {"designation": des})
    _, s = size(part)
    assert s == pytest.approx((D, D, B))
    annulus = math.pi / 4 * (D**2 - d**2) * B
    assert 0.97 * annulus < part.solid.volume < annulus  # minus the corner chamfers
    assert part.port("bore_axis").contract["bore_d"] == d and part.port("outer").contract["od"] == D
    assert part.port("face_b").origin == (0, 0, B / 2)
    assert part.meta["mass_basis"] == "catalog"


# ---------------------------------------------------------------- bicycle envelopes


def test_bb_shell_and_cups():
    shell = resolve("bike.bb_shell_bsa", {"shell_width": 73})
    _, s = size(shell)
    assert s[2] == pytest.approx(73)
    assert shell.port("drive_face").origin == (0, 0, -36.5) and shell.port("drive_face").contract["side_thread"] == "LH"
    bb = resolve("bike.bb_bsa", {"shell_width": 73})
    # Cup seats sit on the shell faces with opposed normals.
    assert bb.port("drive_shell_seat").origin == shell.port("drive_face").origin
    assert bb.port("drive_shell_seat").z == tuple(-c for c in shell.port("drive_face").z)
    assert shell.solid.intersect(bb.solid) is None or shell.solid.intersect(bb.solid).volume < 1e-6


def test_hub_spacing_and_rim_tyre_fit():
    for axle, old in [("100x9qr", 100), ("12x100", 100), ("135x10qr", 135), ("12x142", 142)]:
        hub = resolve("bike.hub", {"axle": axle})
        assert hub.port("dropout_left").origin[2] - hub.port("dropout_right").origin[2] == pytest.approx(old)
        assert size(hub)[1][2] == pytest.approx(old)
        assert hub.port("axle").contract["axle"] == axle
    for bsd in (622, 584, 559):
        rim = resolve("bike.rim", {"bsd": bsd, "inner_width": 21})
        tyre = resolve("bike.tyre", {"bsd": bsd, "width": 35})
        assert size(rim)[1][0] == pytest.approx(bsd + 2 * 6.0)  # bead seat + hook flanges
        assert size(tyre)[1][0] == pytest.approx(bsd + 2 * 35)
        assert rim.port("bead_seat").contract["bsd"] == tyre.port("rim_seat").contract["bsd"] == bsd
        common = rim.solid.intersect(tyre.solid)
        assert common is None or common.volume < 1e-6  # tyre envelope clears the rim
    assert resolve("bike.tyre", {"bsd": 622, "width": 28}).meta["designation"] == "ETRTO 28-622"


def test_cockpit_parts():
    bar = resolve("bike.handlebar", {"width": 700})
    _, s = size(bar)
    assert s == pytest.approx((31.8, 31.8, 700))
    stem = resolve("bike.stem", {"length": 100, "angle": 0, "stack": 40})
    assert stem.port("bar_clamp").origin == pytest.approx((100.0, 0.0, 20.0))
    assert stem.port("bar_clamp").contract["clamp_d"] == bar.port("stem_clamp").contract["clamp_d"] == 31.8
    cup = resolve("bike.headset_cup", {"position": "upper"})
    assert cup.port("stem_seat").contract["steerer_d"] == stem.port("steerer_clamp").contract["steerer_d"] == 28.6
    post = resolve("bike.seatpost", {"diameter": 31.6, "length": 400})
    assert post.port("saddle_clamp").origin == (0, 0, 400) and post.port("post_axis").contract["seatpost_d"] == 31.6
    saddle = resolve("bike.saddle", {})
    assert saddle.meta["freeform_approx"] is True
    assert size(saddle)[1][0] == pytest.approx(270, abs=0.01)


def test_crankset_pitch_diameters_and_pedals():
    assert pitch_diameter(50) == pytest.approx(12.7 / math.sin(math.pi / 50))
    assert pitch_diameter(50) == pytest.approx(202.26, abs=0.01)
    c = resolve("bike.crankset", {"crank_length": 170, "teeth": [52, 36]})
    assert c.port("pedal_right").origin == (170, 0, -73) and c.port("pedal_left").origin == (-170, 0, 73)
    rings = sorted((p for n, p in c.ports.items() if n.startswith("chainring")), key=lambda p: p.contract["teeth"])
    assert [p.contract["teeth"] for p in rings] == [36, 52]
    assert rings[1].contract["pitch_d"] == pytest.approx(pitch_diameter(52), abs=1e-3)
    assert (rings[0].contract["chainline"] + rings[1].contract["chainline"]) / 2 == pytest.approx(43.5)
    assert c.meta["crank_length"] == 170
