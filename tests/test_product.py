"""Product layer (stage S4): request parsing, bicycle template, product spec checks, part sources,
rollback router and the ``run_product`` entry point. Offline: the LLM planner is exercised only
through a fake client with canned structured outputs."""

import json
import math
from types import SimpleNamespace

import pytest

from shilpa.agent import llm
from shilpa.agent.product_planner import parse_request_offline, plan_product
from shilpa.assembly.build import build_assembly, sources
from shilpa.contracts.errors import ShilpaError
from shilpa.contracts.product import ProductSpec, check_product
from shilpa.product.checks import ProductCheck
from shilpa.product.router import Action, apply_repairs, plan_repairs
from shilpa.product.templates.bicycle import (
    ROLE_OF,
    SIZE_TABLE,
    SIZES,
    BicycleChoices,
    bicycle_spec,
    size_for_height,
)

REQUESTS = {
    "medium road bike for 178 cm rider, 700c": {"use_case": "road", "frame_size": "M", "rider_height_cm": 178.0,
                                                "wheel_size": "700c"},
    "650b gravel bike small rider 45 mm tyres": {"use_case": "gravel", "frame_size": "S", "wheel_size": "650b",
                                                 "tyre_width_mm": 45.0},
    "bike for a 2 m rider": {"rider_height_cm": 200.0},
}


# ---------------------------------------------------------------- offline parser


@pytest.mark.parametrize("text", list(REQUESTS))
def test_offline_parser_canonical_requests(text):
    res = parse_request_offline(text)
    assert res.ok and res.supported and res.usage == []
    got = res.choices.model_dump(exclude_unset=True, exclude={"text", "notes"})
    assert got == REQUESTS[text]
    assert res.plan["stated_by_user"] == sorted(REQUESTS[text])


@pytest.mark.parametrize("text, expect", [
    ("road bike, rider 1.85 m, inseam 86 cm, 700x32c", {"rider_height_cm": 185.0, "rider_inseam_cm": 86.0, "tyre_width_mm": 32.0,
                                                       "wheel_size": "700c", "use_case": "road"}),
    ("gravel bicycle for a 5 ft 6 rider, 1x, quick release, tires 40mm", {"use_case": "gravel", "rider_height_cm": 167.6,
                                                                          "chainrings": [40], "tyre_width_mm": 40.0,
                                                                          "rear_axle": "135x10qr", "front_axle": "100x9qr"}),
    ("XL endurance bike with 172.5 mm cranks and a BSA73 shell", {"frame_size": "XL", "use_case": "road", "crank_length_mm": 172.5,
                                                                  "bb_standard": "BSA73"}),
])
def test_offline_parser_rules(text, expect):
    res = parse_request_offline(text)
    assert res.supported
    assert res.choices.model_dump(exclude_unset=True, exclude={"text", "notes"}) == expect


@pytest.mark.parametrize("text, what", [("design a drone", "drone"), ("an electric mountain bike", "electric"),
                                        ("a coffee table", "table"), ("make me a toaster", "toaster")])
def test_offline_parser_refuses_other_products(text, what):
    res = parse_request_offline(text)
    assert res.ok and not res.supported and res.choices is None
    assert what in res.plan["product_class"] and "bicycle.diamond_v1" in res.message


# ---------------------------------------------------------------- LLM planner with a fake client


def _plan(**kw):
    base = {"supported": True, "product_class": "bicycle", "template": "bicycle.diamond_v1", "unsupported_reason": None,
            "use_case": None, "frame_size": None, "rider_height_cm": None, "rider_inseam_cm": None, "wheel_size": None,
            "tyre_width_mm": None, "bb_standard": None, "rear_axle": None, "front_axle": None, "crank_length_mm": None,
            "chainrings": None, "overrides": [], "stated_by_user": [], "assumptions": []}
    return {**base, **kw}


CANNED = {
    "medium road bike for 178 cm rider, 700c": _plan(use_case="road", frame_size="M", rider_height_cm=178, wheel_size="700c",
                                                     stated_by_user=["use_case", "frame_size", "rider_height_cm", "wheel_size"]),
    "650b gravel bike small rider 45 mm tyres": _plan(use_case="gravel", frame_size="S", wheel_size="650b", tyre_width_mm=45,
                                                      stated_by_user=["use_case", "frame_size", "wheel_size", "tyre_width_mm"]),
    "bike for a 2 m rider": _plan(use_case="road", rider_height_cm=200, wheel_size="700c", stated_by_user=["rider_height_cm"],
                                  assumptions=["road use and 700c wheels assumed"]),
    "design a drone": _plan(supported=False, product_class="drone", template=None,
                            unsupported_reason="drones are not a bicycle-template product"),
}


class FakeClient:
    """Stands in for ``AzureOpenAI``: answers ``chat.completions.create`` from ``CANNED``, records requests."""

    def __init__(self):
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def with_options(self, **_):
        return self

    def _create(self, **kw):
        self.requests.append(kw)
        text = kw["messages"][1]["content"]
        msg = SimpleNamespace(content=json.dumps(CANNED[text]), refusal=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")], model="fake-model",
                               usage=SimpleNamespace(prompt_tokens=1200, completion_tokens=150))


@pytest.fixture
def fake_llm(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(llm, "_client", lambda: fake)
    return fake


@pytest.mark.parametrize("text", [t for t in CANNED if t != "design a drone"])
def test_llm_planner_with_fake_client(fake_llm, text):
    res = plan_product(text)
    assert res.ok and res.supported and res.choices is not None
    req = fake_llm.requests[-1]
    assert req["response_format"]["json_schema"]["name"] == "product_plan" and req["response_format"]["json_schema"]["strict"]
    assert res.usage == [{"purpose": "product_plan", "input_tokens": 1200, "output_tokens": 150, "ms": res.usage[0]["ms"],
                          "model": "fake-model"}]
    spec = bicycle_spec(res.choices)
    if text.startswith("bike for a 2 m"):
        # The model's assumptions are tagged "llm", the stated height "user", the size comes from the table.
        assert spec.skeleton["use_case"].source == "llm" and spec.skeleton["wheel_bsd"].source == "llm"
        assert spec.skeleton["rider_height"].source == "user" and spec.value("size") == "XXL"
        assert spec.skeleton["size"].source == "table"
    else:
        assert spec.skeleton["size"].source == "user" and spec.skeleton["use_case"].source == "user"
    # The offline parser agrees with the planner on everything the request itself states.
    llm_choices = res.choices.model_dump(exclude_unset=True)
    offline = parse_request_offline(text).choices.model_dump(exclude_unset=True, exclude={"text", "notes"})
    assert offline == {k: llm_choices[k] for k in offline}
    assert set(res.choices.llm_fields) == set(llm_choices) - set(CANNED[text]["stated_by_user"]) - {
        "text", "notes", "overrides", "llm_fields"}


def test_llm_planner_refuses_drone(fake_llm):
    res = plan_product("design a drone")
    assert res.ok and not res.supported and res.choices is None
    assert "unsupported product class 'drone'" in res.message and "bicycle.diamond_v1" in res.message


def test_llm_planner_without_azure_raises():
    """With Azure unset (as in every test), the real client refuses before any network call."""
    with pytest.raises(ShilpaError, match="not configured"):
        plan_product("medium road bike")


# ---------------------------------------------------------------- template and product spec


def test_sizing_table_lookup():
    assert size_for_height(178) == ("L", None)
    assert size_for_height(169) == ("M", None)
    assert size_for_height(145)[0] == "XS" and "below" in size_for_height(145)[1]
    assert size_for_height(212)[0] == "XXL" and "above" in size_for_height(212)[1]
    assert [r[0] for r in SIZE_TABLE.values()][1:] == [r[1] for r in SIZE_TABLE.values()][:-1]  # contiguous ranges


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("use_case, wheel", [("road", "700c"), ("road", "650b"), ("gravel", "700c"), ("gravel", "650b")])
def test_skeleton_closes_for_every_size(size, use_case, wheel):
    spec = bicycle_spec({"frame_size": size, "use_case": use_case, "wheel_size": wheel})
    # Both axles at one height by construction: the 4.3 mm front-axle level error of a free FrameGeometry is gone.
    assert abs(spec.derived["front_axle_level_error"]) < 1e-6
    assert spec.value("head_tube_length") >= 90
    sp = next(m for m in spec.assembly.mates if m.name == "seatpost")
    assert spec.value("seatpost_min_insertion") <= -sp.offset <= spec.value("seat_tube_length") - 90
    assert spec.derived["ground_z"] == pytest.approx(spec.value("bb_drop") - spec.value("wheel_bsd") / 2 - spec.value("tyre_width"))
    assert 45 <= spec.derived["trail"] <= 80
    assert check_product(spec, ROLE_OF) == []


def test_provenance_and_tree():
    spec = bicycle_spec(BicycleChoices(rider_height_cm=163, use_case="gravel", overrides={"steer_lock": 40}))
    sk = spec.skeleton
    assert (sk["size"].value, sk["size"].source) == ("S", "table")
    assert sk["rider_height"].source == "user" and sk["use_case"].source == "user"
    assert sk["wheel_bsd"].source == "default" and sk["stack"].source == "table"
    assert sk["fork_a2c"].source == "derived" and sk["head_tube_length"].source == "derived"
    assert (sk["steer_lock"].value, sk["steer_lock"].source) == (40, "user")
    assert spec.value("chainrings") == [40] and spec.value("stack") == SIZE_TABLE["S"][2] + 20
    leaves = {leaf.id: leaf for leaf in spec.tree.leaves()}
    assert leaves["frame"].procurement == "make" and leaves["headset"].procurement == "standard"
    assert leaves["crankset"].procurement == "buy" and leaves["headset"].instances == ["headset_upper", "headset_lower"]
    steering = next(m for m in spec.assembly.mates if m.name == "steering")
    assert steering.type == "revolute" and steering.limits == (-40, 40)
    assert spec.assembly.dof == 5 and [i.id for i in spec.assembly.instances if i.grounded] == ["frame"]
    ProductSpec.model_validate_json(spec.model_dump_json())  # round-trips
    with pytest.raises(ValueError, match="unknown skeleton override"):
        bicycle_spec({"overrides": {"wheel_base": 1000}})


def test_check_product_flags_tree_and_standard_problems():
    spec = bicycle_spec({})
    data = spec.model_dump(mode="json")
    wheels = next(c for c in data["tree"]["children"] if c["id"] == "wheels")
    wheels["children"][0]["children"][0]["instances"] = ["front_hub", "ghost"]  # unknown instance
    wheels["children"][1]["children"][0]["instances"] = []  # rear hub leaf without instance, rear_hub orphaned
    frame = next(i for i in data["assembly"]["instances"] if i["id"] == "frame")
    frame["ref"]["params"]["bb_shell_width"] = 73  # frame no longer honours BSA68
    bad = ProductSpec.model_validate(data)
    codes = sorted(i.code for i in check_product(bad, ROLE_OF))
    assert codes == ["leaf_without_instance", "orphan_instance", "standard_mismatch", "unknown_instance"]


# ---------------------------------------------------------------- part sources


def test_builtin_sources_registered_and_build():
    assert {"recipe", "catalog", "weldment", "sheet_metal"} <= sources()
    weld = {"nodes": {"a": [0, 0, 0], "b": [0, 0, 200], "c": [0, 0, 100], "d": [120, 0, 100]},
            "members": [{"id": "post", "start_node": "a", "end_node": "b", "profile": {"od": 30, "wall": 2}, "priority": 1},
                        {"id": "arm", "start_node": "c", "end_node": "d", "profile": {"od": 20, "wall": 1.5}}],
            "ports": [{"name": "foot", "node": "a", "z": [0, 0, -1]}, {"name": "tip", "node": "d", "z_nodes": ["c", "d"]}]}
    sheet = {"thickness": 2, "bend_radius": 2, "base": {"kind": "rect", "width": 60, "depth": 40},
             "flanges": [{"id": "lip", "edge": "base.north", "length": 15}]}
    spec = {"instances": [
        {"id": "stand", "source": "weldment", "grounded": True, "ref": {"generator": "weldment", "params": {"spec": weld}}},
        {"id": "plate", "source": "sheet_metal", "ref": {"generator": "tab", "params": sheet,
                                                         "ports": [{"name": "under", "z": [0, 0, -1]}]}},
        {"id": "nut", "source": "catalog", "ref": {"generator": "iso4032_hex_nut", "params": {"size": "M6"}}}],
        "mates": [{"a": "stand.tip", "b": "plate.under"}]}
    b = build_assembly(spec)
    assert not b.errors, b.errors
    assert b.parts["stand"].meta["cut_list"] and set(b.parts["stand"].meta["pieces"]) == {"post", "arm"}
    assert b.parts["plate"].source == "sheet_metal" and "lip_top" in b.parts["plate"].ports
    assert b.parts["nut"].source == "catalog"
    assert {"stand", "plate"} <= set(b.placed)


def test_bike_weldment_sources_and_errors():
    from shilpa.assembly.sources import cache_stats

    spec = bicycle_spec({"frame_size": "M"})
    frame = spec.assembly.instance("frame")
    before = cache_stats()["hits"]
    a = build_assembly({"instances": [frame.model_dump(), spec.assembly.instance("fork").model_dump() | {"grounded": False}],
                        "mates": [m.model_dump() for m in spec.assembly.mates if m.name == "steering"]})
    b = build_assembly({"instances": [frame.model_dump()]})
    assert not a.errors and not b.errors and cache_stats()["hits"] > before  # the frame is built once
    assert {"head_tube_top", "head_tube_bottom", "bb_shell", "rear_dropout", "seat_tube_top"} <= set(a.parts["frame"].ports)
    assert a.parts["frame"].solid.volume > 0 and "front_axle" in a.parts["fork"].ports
    bad = build_assembly({"instances": [{"id": "x", "source": "weldment", "grounded": True,
                                         "ref": {"generator": "bike.frame", "params": {"stack": -5}}},
                                        {"id": "y", "source": "weldment", "ref": {"generator": "bike.wheel"}}]})
    assert bad.errors["x"].code.value == "invalid_parameter" and bad.errors["y"].code.value == "unsupported_operation"


# ---------------------------------------------------------------- router rules (no geometry)


def _fail(name, actual, detail, level="design"):
    return ProductCheck(name, False, "clearance", actual, 5.0, "mm", level=level, detail=detail)


def _report(*checks):
    return SimpleNamespace(checks=list(checks))


def test_router_rules_and_change_log():
    spec = bicycle_spec({"frame_size": "M", "tyre_width_mm": 50})
    rep = _report(_fail("tyre_clearance[front_tyre~fork]", 0.0, {"member": "crown", "deficit": 5.0, "overlap_mm3": 900.0}),
                  _fail("tyre_clearance[rear_tyre~frame]", 0.0, {"member": "chainstay_l", "deficit": 5.0, "overlap_mm3": 50.0}),
                  ProductCheck("toe_overlap", False, "fit", 0.0, 0.0, "mm", severity="warning"),
                  ProductCheck("crank_sweep", False, "motion", 1.0, 2.0, "mm"))
    actions, unresolved, suggestions = plan_repairs(spec, rep)
    # Both tyre checks blame the 32 mm design tyre: one design-level change, not two.
    assert [(a.param, a.new, a.level) for a in actions] == [("max_tyre_width", 50.0, "design")]
    assert [u["check"] for u in unresolved] == ["crank_sweep"] and suggestions[0]["check"] == "toe_overlap"
    fixed = apply_repairs(spec, actions, 1)
    assert fixed.skeleton["max_tyre_width"].source == "router"
    # Re-derived around the 50 mm tyre: a longer fork and a shorter head tube keep both axles level.
    grow = fixed.value("fork_a2c") - spec.value("fork_a2c")
    assert grow == pytest.approx(18.0)
    assert spec.value("head_tube_length") - fixed.value("head_tube_length") == pytest.approx(grow, abs=1e-3)
    assert abs(fixed.derived["front_axle_level_error"]) < 1e-6
    h = fixed.history[0]
    assert (h.iteration, h.param, h.old, h.new, h.level, h.check) == (1, "max_tyre_width", 32.0, 50.0, "design",
                                                                      "tyre_clearance[front_tyre~fork]")

    # Next round: the stays still crowd the tyre beside a 2x crankset -> go 1x and lengthen them.
    rep = _report(_fail("tyre_clearance[rear_tyre~frame]", 0.0, {"member": "chainstay_l_2", "deficit": 5.0, "overlap_mm3": 3.0}))
    actions, _, _ = plan_repairs(fixed, rep)
    assert [(a.param, a.new) for a in actions] == [("chainrings", [40]), ("chainline", 45.0), ("chainstay_length", 460.0)]
    again = apply_repairs(fixed, actions, 2)
    assert again.value("cs_bend")[1] > fixed.value("cs_bend")[1]  # the stay bends further out past the single ring
    assert [h.param for h in again.history] == ["max_tyre_width", "chainrings", "chainline", "chainstay_length"]
    crank = again.assembly.instance("crankset").ref.params
    assert crank["teeth"] == [40] and crank["chainline"] == 45.0


def test_router_seatpost_steering_and_head_tube_floor():
    spec = bicycle_spec({"frame_size": "M"})
    sp = ProductCheck("seatpost_insertion", False, "fit", 60.0, [80, 430], "mm", level="part",
                      detail={"insertion": 60.0, "min": 80.0, "usable": 430.0})
    def steer(*angles):
        return ProductCheck("steering_sweep", False, "motion", 0.0, 0.0, "mm",
                            detail={"contact_angles": list(angles), "pair": "front_tyre.front_tyre+frame.down_tube"})

    # Contact at the 45 deg end: the stop moves one sample (11.25 deg) inside the first contact.
    actions, unresolved, _ = plan_repairs(spec, _report(sp, steer(45.0, -45.0)))
    assert not unresolved
    assert [(a.param, a.new, a.level) for a in actions] == [("seatpost_length", 350.0, "part"), ("steer_lock", 33.0, "design")]
    post = apply_repairs(spec, actions, 1)
    assert post.assembly.instance("seatpost").ref.params["length"] == 350.0
    assert next(m for m in post.assembly.mates if m.name == "steering").limits == (-33.0, 33.0)
    # Contact at 33.75 deg would need a stop below the 30 deg minimum: reported, not applied.
    actions, unresolved, _ = plan_repairs(spec, _report(steer(33.75)))
    assert not actions and unresolved[0]["check"] == "steering_sweep" and "30" in unresolved[0]["reason"]
    # Very long fork: the derived head tube would fall below 90 mm, so the router raises stack instead.
    big = apply_repairs(spec, [Action("fork_a2c", spec.value("fork_a2c") + 80, "design", "x", "test")], 1)
    assert big.value("head_tube_length") == pytest.approx(90.0, abs=0.05)
    assert big.skeleton["stack"].source == "router" and big.history[-1].check == "derived:head_tube_length"
    assert abs(big.derived["front_axle_level_error"]) < 1e-6


# ---------------------------------------------------------------- end to end (geometry)


def test_run_product_end_to_end(tmp_path):
    from shilpa.product import run_product

    r = run_product("medium road bike for 178 cm rider, 700c", tmp_path, freecad=False)
    json.dumps(r)  # plain JSON
    assert r["status"] == "passed" and r["product"] == "bicycle_road_m_622", r["checks"]["failed"]
    assert r["planner"]["plan"]["parser"] == "offline"
    names = set(r["checks"]["summary"])
    assert {"tyre_clearance[front_tyre~fork]", "tyre_clearance[rear_tyre~frame]", "ground_contact", "steering_sweep",
            "crank_sweep", "toe_overlap", "standover", "seatpost_insertion", "chainline", "bom_complete", "standards"} <= names
    checks = {c["name"]: c for c in r["checks"]["checks"]}
    assert checks["ground_contact"]["actual"]["front_tyre"] == pytest.approx(0, abs=1e-6)
    assert checks["ground_contact"]["actual"]["rear_tyre"] == pytest.approx(0, abs=1e-6)
    assert checks["steering_sweep"]["actual"] > 0 and checks["crank_sweep"]["actual"] >= 2.0
    assert r["checks"]["timings_s"]["sweeps"] < 30
    assert set(r["placements"]) == {i["id"] for i in r["spec"]["assembly"]["instances"]}
    assert {line["part_number"] for line in r["bom"]} >= {"frame", "fork", "rim", "tyre", "crankset"}
    assert next(line for line in r["bom"] if line["part_number"] == "tyre")["quantity"] == 2
    for key in ("step", "bom_csv", "bom_json", "product_bom_csv", "spec_json", "report_json"):
        assert (tmp_path / r["exports"][key].split("\\")[-1].split("/")[-1]).exists()
    assert set(r["renders"]) == {"side", "iso"} and all((tmp_path / f"render_{v}.png").stat().st_size > 10_000 for v in r["renders"])
    assert "fcstd" not in r["exports"] and r["freecad"] is None

    refused = run_product("design a drone", tmp_path / "drone")
    assert refused["status"] == "unsupported" and refused["spec"] is None and refused["exports"] == {}


def test_bad_variant_fails_clearance_then_is_repaired():
    from shilpa.product.router import run_with_router

    r = run_with_router(bicycle_spec({"frame_size": "M", "tyre_width_mm": 50}))
    first = r.iterations[0]["failed"]
    assert "tyre_clearance[front_tyre~fork]" in first and "tyre_clearance[rear_tyre~frame]" in first
    assert r.status == "repaired" and r.report.passed and len(r.iterations) <= 4
    assert [h.param for h in r.spec.history] == ["max_tyre_width", "chainrings", "chainline", "chainstay_length"]
    assert all(r.spec.skeleton[h.param].source == "router" for h in r.spec.history)
    assert r.report.check("tyre_clearance[rear_tyre~frame]").actual >= 5.0
    assert math.isclose(r.report.check("ground_contact").actual["front_tyre"], 0, abs_tol=1e-6)
