"""Gearbox template: sizing maths, offline parsing, routing, router repairs and the full product run."""

import math

import pytest

from shilpa.agent.product_planner import parse_request_offline
from shilpa.agent.router import classify_rules
from shilpa.contracts.product import check_product
from shilpa.product.templates import gearbox as gb


# ---------------------------------------------------------------- maths


def test_lewis_y_table_and_interpolation():
    assert gb.lewis_y(17) == pytest.approx(0.303)
    assert gb.lewis_y(23) == pytest.approx((0.331 + 0.337) / 2)
    assert gb.lewis_y(10) == pytest.approx(0.245) and gb.lewis_y(1000) == pytest.approx(0.480)


def test_hand_calculation_m2_z18():
    # Shigley-style check by hand: T = 20 N.m, m 2, z 18, b 20 mm, 1500 rpm.
    v = math.pi * 36 * 1500 / 60000  # 2.827 m/s
    kv = (6.1 + v) / 6.1
    ft = 2000 * 20 / 36  # 1111 N
    assert gb.bending_stress(20, 2, 18, 20, 1500) == pytest.approx(kv * ft / (20 * 2 * 0.309), rel=1e-9)
    i = math.cos(math.radians(20)) * math.sin(math.radians(20)) / 2 * 3 / 4
    assert gb.contact_stress(20, 2, 18, 54, 20, 1500) == pytest.approx(191 * math.sqrt(kv * ft / (20 * 36 * i)), rel=1e-9)
    # The face that brings contact down to the allowable gives exactly the allowable.
    b = gb.face_for_contact(20, 2, 18, 54, 1500, 520)
    assert gb.contact_stress(20, 2, 18, 54, b, 1500) == pytest.approx(520, rel=1e-9)


def test_shaft_and_bearing_sizing():
    assert gb.shaft_for(20) == 15  # needs 13.7 mm at 40 MPa
    assert gb.shaft_stress(20, 15) <= gb.TAU_ALLOW < gb.shaft_stress(20, 12)
    # L10h = (C/P)^3 10^6 / (60 n): 6002 (C 5.85 kN) at 500 N and 1000 rpm.
    assert gb.bearing_life_h("6002", 500, 1000) == pytest.approx((5850 / 500) ** 3 * 1e6 / 60000, rel=1e-9)


@pytest.mark.parametrize("ratio", [1.5, 2.0, 3.0, 3.7, 4.5, 6.0, 8.0])
def test_teeth_within_tolerance_and_hunting(ratio):
    z1, z2 = gb.pick_teeth(ratio)
    assert 17 <= z1 <= 30
    assert abs(z2 / z1 - ratio) / ratio <= gb.RATIO_TOL
    hunting = [(a, round(a * ratio)) for a in range(17, 31)
               if abs(round(a * ratio) / a - ratio) / ratio <= gb.RATIO_TOL and math.gcd(a, round(a * ratio)) == 1]
    if hunting:  # 3:2 or any integer ratio has none within 1 % for 17-30 teeth
        assert (z1, z2) == hunting[0]


def test_default_spec_is_consistent():
    spec = gb.gearbox_spec({})
    assert spec.template == gb.TEMPLATE_ID and spec.requirements.product_class == "gearbox"
    assert check_product(spec) == []
    assert spec.assembly.dof == 2 and len(spec.assembly.instances) == 22
    v = {k: p.value for k, p in spec.skeleton.items()}
    assert v["centre_distance"] == v["module"] * (v["pinion_teeth"] + v["gear_teeth"]) / 2
    assert gb.pinion_web_ok(v["module"], v["pinion_teeth"], v["shaft_d_in"])
    assert spec.skeleton["ratio"].source == "default" and spec.skeleton["module"].source == "derived"


def test_overrides_are_user_provenance():
    spec = gb.gearbox_spec({"ratio": 3, "overrides": {"module": 3}})
    assert spec.skeleton["module"].value == 3 and spec.skeleton["module"].source == "user"
    assert spec.skeleton["ratio"].source == "user"
    with pytest.raises(ValueError):
        gb.gearbox_spec({"overrides": {"plate_w": 300}})


# ---------------------------------------------------------------- parsing and routing


@pytest.mark.parametrize("text,ratio,torque,rpm", [
    ("4:1 gearbox, 20 Nm input at 1500 rpm", 4.0, 20.0, 1500.0),
    ("gearbox with output torque 120 N.m and ratio 5, hardened gears", 5.0, 24.0, 1500.0),
    ("gearbox 3:1, 30 Nm at the output, input 1000 rpm", 3.0, 10.0, 1000.0),
    ("reducer, input 3000 rpm, output 600 rpm, 15 Nm in", 5.0, 15.0, 3000.0),
])
def test_offline_gearbox_parser(text, ratio, torque, rpm):
    r = parse_request_offline(text)
    assert r.ok and r.supported, r.message
    c = r.choices
    assert (c.ratio, c.input_torque_nm, c.input_rpm) == pytest.approx((ratio, torque, rpm))


def test_parser_motor_power_and_life():
    c = parse_request_offline("speed reducer from 1450 rpm to 360 rpm output, 2.2 kW motor, 20k hours").choices
    assert c.ratio == pytest.approx(1450 / 360, abs=1e-3)
    assert c.input_torque_nm == pytest.approx(9549 * 2.2 / 1450, abs=1e-3)
    assert c.input_rpm == 1450 and c.life_hours == 20000


@pytest.mark.parametrize("text", ["planetary gearbox 10:1", "two-stage gear reducer", "worm gearbox 30:1"])
def test_parser_refuses_other_gearboxes(text):
    r = parse_request_offline(text)
    assert r.ok and not r.supported and "single-stage spur" in r.message


def test_routing():
    assert classify_rules("4:1 gearbox for a conveyor").kind == "product"
    assert classify_rules("speed reducer 3:1").kind == "product"
    assert classify_rules("a gear train of two spur gears on shafts").kind == "assembly"
    assert parse_request_offline("medium road bike for a 178 cm rider").choices.frame_size == "M"


# ---------------------------------------------------------------- router outcomes (build + check)


@pytest.fixture(scope="module")
def routed():
    from shilpa.product.router import run_with_router

    cache = {}

    def run(**choices):
        key = tuple(sorted(choices.items()))
        if key not in cache:
            cache[key] = run_with_router(gb.gearbox_spec(choices))
        return cache[key]
    return run


def test_light_duty_passes_first_time(routed):
    r = routed(ratio=3, input_torque_nm=1)
    assert r.status == "passed" and not r.spec.history
    assert r.report.check("mesh").passed and r.report.check("ports_on_geometry").passed
    assert r.report.check("assembly").passed  # no interference, all contacts, clearances, DOF 2


def test_contact_failure_widens_the_face(routed):
    r = routed(ratio=3, input_torque_nm=10)
    assert r.status == "repaired"
    assert r.iterations[0]["failed"] == ["tooth_contact"]
    (change,) = r.spec.history
    assert (change.param, change.level, change.old) == ("face_width", "part", 20.0)
    assert r.report.check("tooth_contact").actual <= 520.0


def test_overlapping_bearing_bores_step_the_module(routed):
    r = routed(ratio=2, input_torque_nm=5, gear_material="hardened_steel", life_hours=30000)
    assert r.status == "repaired"
    assert "bearing_spacing" in r.iterations[0]["failed"]
    assert any(h.param == "module" and h.level == "design" for h in r.spec.history)
    assert r.report.check("bearing_spacing").actual >= 3.0


def test_overload_is_unresolved_with_a_reason(routed):
    r = routed(ratio=6, input_torque_nm=100, input_rpm=3000, life_hours=20000)
    assert r.status == "unresolved"
    assert [c.name for c in r.report.failed] == ["shaft_torsion_out"]
    assert "largest shaft" in r.unresolved[0]["reason"]


def test_run_product_exports(tmp_path):
    from shilpa.product import run_product

    res = run_product("3:1 gearbox, 1 Nm input at 1500 rpm", tmp_path, renders=False, freecad=False)
    assert res["status"] == "passed" and res["template"] == gb.TEMPLATE_ID
    assert res["exports"]["step"].endswith("gearbox.step") and (tmp_path / "gearbox.step").stat().st_size > 0
    by_node = {r["tree_node"]: r for r in res["bom"]}
    assert by_node["screws"]["quantity"] == 8 and by_node["side_plates"]["quantity"] == 2
    assert by_node["pinion"]["procurement"] == "buy" and by_node["input_bearings"]["quantity"] == 2
