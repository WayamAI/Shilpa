from __future__ import annotations

import math

import build123d as bd
import pytest

from shilpa.catalog import list_generators, resolve
from shilpa.contracts.ports import BuiltPart, Port
from shilpa.validators.ports import PORT_TOL, check_port, check_ports, port_kind


def _part(solid, *ports: Port) -> BuiltPart:
    return BuiltPart("synthetic", solid, {p.name: p for p in ports}, "recipe")


def _box() -> bd.Solid:
    return bd.Solid.make_box(20, 10, 5, bd.Plane(origin=(-10, -5, -2.5)))  # centred on the origin


def _tube(od: float = 20.0, bore: float = 10.0, length: float = 30.0) -> bd.Solid:
    return bd.Solid.make_cylinder(od / 2, length) - bd.Solid.make_cylinder(bore / 2, length)


def _one(part: BuiltPart, name: str):
    (check,) = [c for c in check_ports(part) if c.name.startswith(f"port_{name}_")]
    return check


# ---------------------------------------------------------------- kind inference


@pytest.mark.parametrize("name,label,contract,kind", [
    ("spindle_axis", "", {}, "axis"),
    ("rear_dropout", "rear axle centre between dropouts", {}, "axis"),
    ("stem_clamp", "clamp section centre, bar axis to the left", {"clamp_d": 31.8}, "axis"),
    ("drive_shell_seat", "drive cup seat on shell face", {}, "face"),
    ("dropout_left", "non-drive locknut face", {"axle_d": 12.0}, "face"),
    ("head_tube_top", "upper headset cup seat", {"cup_bore": 44.0}, "face"),
    ("min_insertion", "minimum insertion mark", {"seatpost_d": 27.2}, "axis"),
    ("saddle_clamp", "saddle rail clamp centre", {}, "point"),
    ("pedal_left", "left pedal thread", {}, "axis"),
    ("outer", "outside diameter, fits a housing", {"od": 22}, "axis"),
    ("datum", "", {}, "point"),
])
def test_kind_inference(name, label, contract, kind):
    assert port_kind(Port(name=name, label=label, contract=contract)) == kind


def test_explicit_kind_wins():
    assert port_kind(Port(name="bore_axis", contract={"kind": "point"})) == "point"

    class Tagged:  # a future Port with a ``kind`` field
        name, label, contract, kind = "face_a", "", {}, "axis"

    assert port_kind(Tagged()) == "axis"


# ---------------------------------------------------------------- face ports


def test_face_port_on_box_face_passes():
    c = _one(_part(_box(), Port(name="top_face", origin=(3, 2, 2.5))), "top_face")
    assert c.passed, c
    assert c.actual["plane_offset"] <= PORT_TOL


def test_face_port_off_plane_fails():
    c = _one(_part(_box(), Port(name="top_face", origin=(0, 0, 3.0))), "top_face")
    assert not c.passed
    assert c.actual["plane_offset"] == pytest.approx(0.5)


def test_face_port_flipped_normal_fails_with_hint():
    c = _one(_part(_box(), Port(name="top_face", origin=(0, 0, 2.5), z=(0, 0, -1))), "top_face")
    assert not c.passed
    assert "flipped" in c.note


def test_face_port_beside_face_fails():
    c = _one(_part(_box(), Port(name="top_face", origin=(30, 0, 2.5))), "top_face")
    assert not c.passed
    assert c.actual["outside_face_by"] == pytest.approx(20.0)


def test_face_port_tilted_fails():
    z = (math.sin(math.radians(2)), 0.0, math.cos(math.radians(2)))
    c = _one(_part(_box(), Port(name="top_face", origin=(0, 0, 2.5), z=z, x=(z[2], 0.0, -z[0]))), "top_face")
    assert not c.passed


def test_annular_seat_accepts_bore_centre():
    # The origin sits on the axis, inside the bore, yet the annular end face is the seat.
    c = _one(_part(_tube(), Port(name="end_face", origin=(0, 0, 30))), "end_face")
    assert c.passed, c


# ---------------------------------------------------------------- axis ports


def test_axis_port_with_right_diameters_passes():
    part = _part(_tube(), Port(name="bore_axis", contract={"bore_d": 10.0}), Port(name="outer", contract={"od": 20.0}))
    checks = check_ports(part)
    assert all(c.passed for c in checks), checks
    assert checks[0].actual["coaxial_diameters"] == [10.0, 20.0]


def test_axis_port_reversed_direction_passes():
    c = _one(_part(_tube(), Port(name="bore_axis", origin=(0, 0, 15), z=(0, 0, -1), contract={"bore_d": 10})), "bore_axis")
    assert c.passed, c


def test_axis_port_wrong_diameter_fails_and_reports_found():
    c = _one(_part(_tube(), Port(name="bore_axis", contract={"bore_d": 12.0})), "bore_axis")
    assert not c.passed
    assert c.actual["closest_diameter"] == 10.0
    assert c.actual["coaxial_diameters"] == [10.0, 20.0]


def test_axis_port_offset_fails():
    c = _one(_part(_tube(), Port(name="bore_axis", origin=(0.5, 0, 0), contract={"bore_d": 10.0})), "bore_axis")
    assert not c.passed
    assert c.actual is None and "0.500 mm" in c.note


def test_axis_port_perpendicular_fails():
    c = _one(_part(_tube(), Port(name="bore_axis", z=(1, 0, 0), x=(0, 1, 0))), "bore_axis")
    assert not c.passed


def test_axis_port_from_circular_edges():
    # A frustum has no cylindrical face; its end circles carry the axis.
    cone = bd.Solid.make_cone(10, 6, 20)
    c = _one(_part(cone, Port(name="shaft_axis", contract={"diameter": 12.0})), "shaft_axis")
    assert c.passed, c
    assert c.actual["coaxial_diameters"] == [12.0, 20.0]


def test_axis_port_without_diameter_checks_coaxiality_only():
    c = _one(_part(_tube(), Port(name="thread_axis", contract={"thread": "M10x1.5"})), "thread_axis")
    assert c.passed and "coaxiality only" in c.note


# ---------------------------------------------------------------- point ports, edge cases


def test_point_port_inside_and_outside():
    part = _part(_box(), Port(name="datum", origin=(1, 1, 0)), Port(name="far", label="reference centre", origin=(0, 0, 10)))
    near, far = check_ports(part)
    assert near.passed and near.actual["distance_to_solid"] == 0.0
    assert not far.passed and far.actual["distance_to_solid"] == pytest.approx(7.5)


def test_straddle_point_between_two_rods():
    rods = bd.Solid.make_box(40, 4, 4, bd.Plane(origin=(-20, 8, -2))).fuse(bd.Solid.make_box(40, 4, 4, bd.Plane(origin=(-20, -12, -2))))
    port = Port(name="rail_clamp", label="rail clamp centre", contract={"straddle": 10.0}, x=(1, 0, 0))
    plain = Port(name="rail_clamp", label="rail clamp centre", x=(1, 0, 0))
    wide = Port(name="rail_clamp", label="rail clamp centre", contract={"straddle": 20.0}, x=(1, 0, 0))
    assert check_port(_part(rods, port), port).passed
    assert not check_port(_part(rods, plain), plain).passed  # the centre itself is in the gap
    c = check_port(_part(rods, wide), wide)
    assert not c.passed and c.actual["straddle_distances"] == [pytest.approx(8.0), pytest.approx(8.0)]


def test_kind_override_and_missing_solid():
    port = Port(name="datum", origin=(0, 0, 2.5))
    assert check_port(_part(_box(), port), port, kind="face").passed
    (c,) = check_ports(_part(None, port))
    assert not c.passed and c.name == "ports_solid"


# ---------------------------------------------------------------- real parts

# Declared ports that do not sit on their geometry today (findings about the
# generators, not validator bugs). Empty: the ten first found were fixed in the
# generators (pedal-eye bores, chainring centre planes as references, hub
# flange ports on the outer faces, saddle rails, tyre bead band at the BSD,
# nominal-diameter screw shank, down tube clear of the head-tube bottom). Any
# new mismatch fails.
EXPECTED_MISMATCHES: set[tuple[str, str]] = set()


def _real_parts():
    for g in list_generators():
        yield g["name"], lambda name=g["name"]: resolve(name)


@pytest.mark.parametrize("generator,make", list(_real_parts()), ids=[g["name"] for g in list_generators()])
def test_catalog_ports_match_geometry(generator, make):
    part = make()
    checks = check_ports(part)
    assert len(checks) == len(part.ports)
    failed = {(generator, c.name.removeprefix("port_").rsplit("_", 1)[0]) for c in checks if not c.passed}
    assert failed <= EXPECTED_MISMATCHES, [c for c in checks if not c.passed]


@pytest.mark.parametrize("which", ["frame", "fork"])
def test_weldment_ports_match_geometry(which):
    from shilpa.weldment.bike_frame import build_fork, build_frame

    part = (build_frame if which == "frame" else build_fork)().part
    checks = check_ports(part)
    assert len(checks) == len(part.ports)
    failed = {(part.name, c.name.removeprefix("port_").rsplit("_", 1)[0]) for c in checks if not c.passed}
    assert failed <= EXPECTED_MISMATCHES, [c for c in checks if not c.passed]
