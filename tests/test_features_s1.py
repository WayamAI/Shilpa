"""IR 1.1 feature vocabulary (roadmap stage S1): schema, static checks, geometry oracles, FreeCAD lowering.

Volumes and boxes are closed form (shoelace, Pappus, frusta, bicylinders), never read back from
the adapter under test.
"""

import copy
import json
import math
from dataclasses import asdict
from pathlib import Path

import pytest
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps

from shilpa.adapters import CAPABILITIES
from shilpa.adapters import build123d_adapter as adapter
from shilpa.adapters import freecad_adapter
from shilpa.agent.llm import strict_schema
from shilpa.agent.schemas import PlanOutput, from_recipe, to_recipe
from shilpa.contracts import iso_holes
from shilpa.contracts.compile import compile_recipe
from shilpa.contracts.errors import ErrorCode, ShilpaError
from shilpa.contracts.ir import ALL_OPS, MAX_FEATURES
from shilpa.pipeline import execute

from .test_contracts import BLUEPRINT_PLATE

PI = math.pi
CORPUS = Path(__file__).resolve().parents[1] / "evals" / "corpus"
NEW_PARTS = [f"N{i:02d}" for i in range(1, 16)]


def circ(d):
    return PI * d * d / 4


def fixture(fid):
    return json.loads((CORPUS / f"{fid}.json").read_text(encoding="utf-8"))


def built(recipe):
    res = adapter.build(recipe)
    assert res.ok, res.error
    return res


def code_of(recipe) -> ErrorCode:
    with pytest.raises(ShilpaError) as ei:
        res = adapter.build(recipe)
        if res.error:
            raise res.error
    return ei.value.code


def bbox(shape):
    bb = shape.bounding_box()
    return [round(v, 6) for v in (bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z)]


def plate(*extra, w=80, d=40, t=8, **params):
    return {"parameters": {"w": w, "d": d, "t": t, **params},
            "features": [{"id": "outline", "op": "centered_rectangle", "width_ref": "w", "height_ref": "d"},
                         {"id": "plate", "op": "extrude", "profile_ref": "outline", "distance_ref": "t"}, *extra]}


# ---------------------------------------------------------------- schema


def test_schema_versions_and_feature_cap():
    old = compile_recipe(BLUEPRINT_PLATE, CAPABILITIES)
    assert old.recipe.schema_version == "1.0"  # 1.0 recipes are still accepted unchanged
    assert compile_recipe({k: v for k, v in BLUEPRINT_PLATE.items() if k != "schema_version"}).recipe.schema_version == "1.1"
    sketches = [{"id": f"s{i}", "op": "circle", "diameter_ref": "d"} for i in range(MAX_FEATURES - 1)]
    ok = {"parameters": {"d": 10, "h": 5}, "features": sketches + [{"id": "body", "op": "extrude", "profile_ref": "s0", "distance_ref": "h"}]}
    assert MAX_FEATURES == 200 and len(compile_recipe(ok).features) == 200
    over = copy.deepcopy(ok)
    over["features"].insert(0, {"id": "extra", "op": "circle", "diameter_ref": "d"})
    with pytest.raises(ShilpaError) as ei:
        compile_recipe(over)
    assert ei.value.code == ErrorCode.INVALID_SCHEMA


def test_every_op_is_in_both_adapters():
    assert set(adapter._OPS) == ALL_OPS
    assert freecad_adapter.CAPABILITIES == ALL_OPS
    assert len(ALL_OPS) == 23


def test_plan_schema_offers_new_ops_in_strict_mode():
    s = strict_schema(PlanOutput.model_json_schema())
    ops = {d["properties"]["op"]["enum"][0] for d in s["$defs"].values() if "op" in d.get("properties", {})}
    assert ops == ALL_OPS
    # Strict mode: nested segment and face selector objects are closed and fully required too.
    for name in ("Segment", "FaceSelector"):
        d = s["$defs"][name]
        assert d["additionalProperties"] is False and set(d["required"]) == set(d["properties"])


def test_plan_roundtrip_strips_nested_nulls():
    rec = fixture("N02")["recipe"]
    plan = from_recipe(rec)
    # What strict mode returns: every optional field present as null, including inside segments.
    for f in plan["features"]:
        for seg in f.get("segments", []):
            seg.update({k: seg.get(k) for k in ("mid_x_ref", "mid_y_ref", "radius_ref", "clockwise")})
    back = to_recipe({**plan, "change_summary": None})
    assert back["schema_version"] == "1.1"
    assert compile_recipe(back, CAPABILITIES).output_id == "tube"
    assert all(None not in s.values() for f in back["features"] for s in f.get("segments", []))


def test_plan_members_lead_with_id_and_op():  # regression: gpt-5.5 picked helix / linear_pattern when holes led with body_ref
    s = strict_schema(PlanOutput.model_json_schema())
    for name, d in s["$defs"].items():
        if "op" in d.get("properties", {}):
            assert list(d["properties"])[:2] == ["id", "op"], name


def test_plan_nulls_mean_defaults():  # regression: strict mode returned clockwise / left_handed as null
    from shilpa.agent.planner import _normalize_plan

    plan = from_recipe(fixture("N11")["recipe"])
    plan.update(change_summary=None)
    plan["features"][1]["left_handed"] = None
    plan["features"][0]["inner_diameter_ref"] = ""
    PlanOutput.model_validate(_normalize_plan(plan))


def test_requirements_coverage_counts_bend_angles_and_screw_sizes():
    from shilpa.agent.planner import check_requirements

    dims = [{"name": "bend_angle", "value": 90, "unit": "deg", "kind": "angle", "source": "user"},
            {"name": "bend_radius", "value": 40, "unit": "mm", "kind": "length", "source": "user"}]
    check_requirements(fixture("N02")["recipe"], {"units": "mm", "dimensions": dims})  # the tangent arc sweeps 90 deg
    check_requirements(fixture("N06")["recipe"], {"units": "mm", "dimensions": [
        {"name": "screw", "value": 5, "unit": "mm", "kind": "length", "source": "user"}]})  # "M5" is met by standard_size


# ---------------------------------------------------------------- static checks


def test_revolve_axis_must_lie_in_sketch_plane():
    r = {"parameters": {"w": 10, "h": 5, "x": 20},
         "features": [{"id": "p", "op": "centered_rectangle", "plane": "XZ", "width_ref": "w", "height_ref": "h", "center_x_ref": "x"},
                      {"id": "r", "op": "revolve", "profile_ref": "p", "axis": "Y"}]}
    with pytest.raises(ShilpaError) as ei:
        compile_recipe(r)
    assert ei.value.code == ErrorCode.INVALID_SCHEMA and "XZ" in ei.value.info.message


def test_loft_offsets_must_increase():
    r = {"parameters": {"a": 20, "b": 10, "h": 30},
         "features": [{"id": "s1", "op": "circle", "diameter_ref": "a", "offset_ref": "h"},
                      {"id": "s2", "op": "circle", "diameter_ref": "b"},
                      {"id": "l", "op": "loft", "profile_refs": ["s1", "s2"]}]}
    with pytest.raises(ShilpaError) as ei:
        compile_recipe(r)
    assert "increasing" in ei.value.info.message


def test_segment_fields_and_path_smoothness():
    base = {"id": "p", "op": "path", "plane": "XZ", "start_x_ref": "0 * l", "start_y_ref": "0 * l"}
    wrong = {"parameters": {"l": 10}, "features": [{**base, "segments": [{"kind": "line", "x_ref": "l", "y_ref": "l", "radius_ref": "l"}]}]}
    sharp = {"parameters": {"l": 10}, "features": [{**base, "segments": [{"x_ref": "0 * l", "y_ref": "l"}, {"x_ref": "l", "y_ref": "l"}]}]}
    for r, words in ((wrong, "takes"), (sharp, "sharp corner")):
        with pytest.raises(ShilpaError) as ei:
            compile_recipe(r)
        assert ei.value.code == ErrorCode.INVALID_SCHEMA and words in ei.value.info.message


def test_iso_hole_lookup_and_overrides():
    m6 = iso_holes.lookup("M6")
    assert (m6.clearance["medium"], m6.tap_drill, m6.cbore_diameter, m6.cbore_depth, m6.thread) == (6.6, 5.0, 11.0, 6.4, "M6x1")
    r = plate({"id": "h", "op": "hole", "body_ref": "plate", "hole_type": "counterbore", "standard_size": "M6",
               "cbore_depth_ref": "cb"}, cb=5)
    v = compile_recipe(r).features[-1].values
    assert (v["diameter_ref"], v["cbore_diameter_ref"], v["cbore_depth_ref"]) == (6.6, 11.0, 5)  # explicit ref wins
    t = plate({"id": "h", "op": "hole", "body_ref": "plate", "hole_type": "tapped", "standard_size": "M8", "mode": "blind", "depth_ref": "dd",
               "thread_depth_ref": "td"}, dd=6, td=5)
    cf = compile_recipe(t).features[-1]
    assert cf.values["diameter_ref"] == 6.8 and cf.meta["thread"] == "M8x1.25" and cf.meta["thread_depth"] == 5


@pytest.mark.parametrize("hole, words", [
    ({"hole_type": "counterbore", "diameter_ref": "t"}, "cbore_diameter_ref is required"),
    ({"hole_type": "tapped", "diameter_ref": "t"}, "need standard_size"),
    ({"hole_type": "countersink", "standard_size": "M18"}, "M18 has no countersink"),
    ({"diameter_ref": "t", "cbore_depth_ref": "t"}, "does not apply"),
    ({"hole_type": "counterbore", "standard_size": "M6", "mode": "blind", "depth_ref": "t", "cbore_depth_ref": "t"}, "less than the hole depth"),
])
def test_hole_series_static_errors(hole, words):
    with pytest.raises(ShilpaError) as ei:
        compile_recipe(plate({"id": "h", "op": "hole", "body_ref": "plate", **hole}))
    assert ei.value.code == ErrorCode.INVALID_SCHEMA and words in ei.value.info.message


# ---------------------------------------------------------------- geometry oracles (build123d)


def test_profile_arcs_bulge_the_right_way():
    # Semicircular radius arc bulging out (+), then a clockwise minor arc dipping into the outline (-).
    r = {"parameters": {"a": 40, "b": 20, "r": 10, "big": 25, "t": 5},
         "features": [{"id": "p", "op": "profile", "start_x_ref": "0 * a", "start_y_ref": "0 * a", "segments": [
                           {"x_ref": "a", "y_ref": "0 * a"},
                           {"kind": "radius_arc", "x_ref": "a", "y_ref": "b", "radius_ref": "r"},
                           {"kind": "radius_arc", "x_ref": "0 * a", "y_ref": "b", "radius_ref": "big", "clockwise": True}]},
                      {"id": "e", "op": "extrude", "profile_ref": "p", "distance_ref": "t"}]}
    theta = 2 * math.asin(20 / 25)
    dip = 25 ** 2 / 2 * (theta - math.sin(theta))
    res = built(r)
    assert res.shape.volume == pytest.approx((40 * 20 + PI * 100 / 2 - dip) * 5, rel=1e-9)
    assert bbox(res.shape) == [0, 0, 0, 50, 20, 5]


def test_rotated_slot():
    r = {"parameters": {"l": 30, "w": 10, "t": 4, "a": {"value": 30, "kind": "angle"}},
         "features": [{"id": "s", "op": "slot", "length_ref": "l", "width_ref": "w", "rotation_angle_ref": "a"},
                      {"id": "e", "op": "extrude", "profile_ref": "s", "distance_ref": "t"}]}
    res = built(r)
    assert res.shape.volume == pytest.approx((30 * 10 + circ(10)) * 4, rel=1e-9)
    bb = res.shape.bounding_box()
    assert bb.size.X == pytest.approx(30 * math.cos(PI / 6) + 10, abs=1e-6)
    assert bb.size.Y == pytest.approx(30 * math.sin(PI / 6) + 10, abs=1e-6)


def test_partial_revolve_turns_counter_clockwise():
    r = {"parameters": {"w": 10, "h": 5, "x": 25, "a": {"value": 90, "kind": "angle"}},
         "features": [{"id": "p", "op": "centered_rectangle", "plane": "XY", "width_ref": "h", "height_ref": "w", "center_y_ref": "x"},
                      {"id": "r", "op": "revolve", "profile_ref": "p", "axis": "X", "angle_ref": "a"}]}
    res = built(r)
    assert res.shape.volume == pytest.approx(5 * PI * (30 ** 2 - 20 ** 2) / 4, rel=1e-9)
    assert bbox(res.shape) == [-2.5, 0, 0, 2.5, 30, 30]  # +Y swings towards +Z about +X


def test_revolve_profile_may_not_cross_axis():
    r = {"parameters": {"w": 10, "h": 5},
         "features": [{"id": "p", "op": "centered_rectangle", "plane": "XZ", "width_ref": "w", "height_ref": "h"},
                      {"id": "r", "op": "revolve", "profile_ref": "p", "axis": "Z"}]}
    assert code_of(r) == ErrorCode.PRECONDITION_FAILED


def test_self_crossing_profile_rejected():
    r = {"parameters": {"a": 10, "t": 2},
         "features": [{"id": "p", "op": "profile", "start_x_ref": "0 * a", "start_y_ref": "0 * a",
                       "segments": [{"x_ref": "a", "y_ref": "a"}, {"x_ref": "a", "y_ref": "0 * a"}, {"x_ref": "0 * a", "y_ref": "a"}]},
                      {"id": "e", "op": "extrude", "profile_ref": "p", "distance_ref": "t"}]}
    assert code_of(r) == ErrorCode.PRECONDITION_FAILED


def test_sweep_profile_must_sit_at_path_start():
    rec = copy.deepcopy(fixture("N02")["recipe"])
    rec["features"][0]["offset_ref"] = "rise"  # section lifted off the spine start
    assert code_of(rec) == ErrorCode.PRECONDITION_FAILED


def test_outward_shell_and_face_count():
    res = built(plate({"id": "s", "op": "shell", "body_ref": "plate", "thickness_ref": "wall", "direction": "outward",
                       "open_faces": [{"side": "top"}]}, w=40, d=30, t=20, wall=2))
    assert res.shape.volume == pytest.approx(44 * 34 * 22 - 40 * 30 * 20, rel=1e-9)
    assert bbox(res.shape) == [-22, -17, -2, 22, 17, 20]
    bad = plate({"id": "s", "op": "shell", "body_ref": "plate", "thickness_ref": "wall", "open_faces": [{"side": "top", "expected_count": 2}]},
                wall=2)
    assert code_of(bad) == ErrorCode.SELECTOR_AMBIGUOUS


def test_mirror_offset_and_patterns():
    box = {"parameters": {"a": 10, "h": 5, "at": 10},
           "features": [{"id": "s", "op": "centered_rectangle", "width_ref": "a", "height_ref": "a", "center_x_ref": "a / 2"},
                        {"id": "b", "op": "extrude", "profile_ref": "s", "distance_ref": "h"},
                        {"id": "m", "op": "mirror", "body_ref": "b", "plane": "YZ", "offset_ref": "at"}]}
    res = built(box)
    assert res.shape.volume == pytest.approx(1000) and bbox(res.shape)[0::3] == [0, 20]  # the plane sits at x = 10
    pins = {"parameters": {"d": 6, "h": 5, "x": 30, "n": {"value": 3, "kind": "count"}, "a": {"value": 90, "kind": "angle"}},
            "features": [{"id": "c", "op": "circle", "diameter_ref": "d", "center_x_ref": "x"},
                         {"id": "pin", "op": "extrude", "profile_ref": "c", "distance_ref": "h"},
                         {"id": "p", "op": "polar_pattern", "body_ref": "pin", "count_ref": "n", "angle_ref": "a"}]}
    res = built(pins)
    assert res.shape.volume == pytest.approx(3 * circ(6) * 5) and len(res.shape.solids()) == 3
    assert bbox(res.shape) == [-3, -3, 0, 33, 33, 5]  # copies at 0, 45 and 90 degrees


def test_cross_hole_through_round_shaft():
    def bicylinder(r, R, n=4000):
        f = lambda t: r * r * math.cos(t) ** 2 * math.sqrt(R * R - (r * math.sin(t)) ** 2)  # noqa: E731
        h = (PI / 2) / n
        return 8 * h / 3 * (f(0) + f(PI / 2) + sum((4 if i % 2 else 2) * f(i * h) for i in range(1, n)))

    shaft = {"parameters": {"d": 20, "l": 80, "hd": 6, "z": 70},
             "features": [{"id": "s", "op": "stepped_shaft", "sections": [{"diameter_ref": "d", "length_ref": "l"}]},
                          {"id": "x", "op": "hole", "body_ref": "s", "face": "x_max", "diameter_ref": "hd", "center_y_ref": "z"}]}
    res = built(shaft)
    # OCC's default volume integration is only good to ~3e-6 on these intersection faces; integrate precisely.
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(res.shape.wrapped, props, 1e-9)
    assert props.Mass() == pytest.approx(circ(20) * 80 - bicylinder(3, 10), rel=1e-9)
    blind = copy.deepcopy(shaft)
    blind["features"][1].update(mode="blind", depth_ref="hd")
    assert code_of(blind) == ErrorCode.PRECONDITION_FAILED  # a curved entry takes through holes only


def test_revolved_groove_may_break_the_side_wall():
    r = {"parameters": {"d": 20, "l": 60, "depth": 2, "w": 3, "z": 30},
         "features": [{"id": "s", "op": "stepped_shaft", "sections": [{"diameter_ref": "d", "length_ref": "l"}]},
                      {"id": "g", "op": "centered_rectangle", "plane": "XZ", "width_ref": "2 * depth", "height_ref": "w",
                       "center_x_ref": "d / 2", "center_y_ref": "z"},
                      {"id": "ring", "op": "revolve", "profile_ref": "g", "axis": "Z"},
                      {"id": "grooved", "op": "boolean", "operation": "cut", "target_ref": "s", "tool_ref": "ring"}]}
    assert built(r).shape.volume == pytest.approx(circ(20) * 60 - PI * (10 ** 2 - 8 ** 2) * 3, rel=1e-9)


def test_tapped_hole_records_thread_metadata():
    res = built(fixture("N07")["recipe"])
    side = next(f for f in res.features if f.id == "side_tap")
    assert side.detail["thread"] == "M10x1.5" and side.detail["thread_depth"] == 12 and side.detail["face"] == "x_max"


@pytest.mark.parametrize("fid", NEW_PARTS)
def test_new_corpus_part_against_oracle(fid, tmp_path):
    fx = fixture(fid)
    res = execute(fx["recipe"], tmp_path, oracle=fx["oracle"])
    failed = [c for c in res.validation["checks"] if not c["passed"]] if res.validation else []
    assert res.ok, (res.error, failed)


# ---------------------------------------------------------------- FreeCAD lowering (no FreeCAD needed)


def lowered(fid):
    res = built(fixture(fid)["recipe"])
    return freecad_adapter.lower(res.compiled, [asdict(f) for f in res.features])["ops"]


def test_lowering_uses_native_partdesign_features():
    kinds = {fid: [op["pd"] for op in lowered(fid)] for fid in ("N01", "N02", "N04", "N08", "N11", "N12", "N14")}
    assert kinds["N01"] == ["Revolution"]
    assert kinds["N02"] == ["AdditivePipe"]
    assert kinds["N04"] == ["AdditiveLoft", "Thickness"]
    assert kinds["N08"] == ["Pad", "Pocket", "Mirrored"]
    assert kinds["N11"] == ["AdditiveHelix"]
    assert kinds["N12"] == ["Pad", "Pad", "PolarPattern", "Pocket"]
    assert kinds["N14"] == ["Pad", "Pocket", "Mirrored", "Pocket"]  # the mirrored slot cutter became a pocket


def test_lowering_hole_series():
    ops = {op["id"]: op for op in lowered("N07")}
    assert ops["cbores_cbore"]["pd"] == "Pocket" and ops["cbores_cbore"]["length"] == {"v": 8.6}  # ISO table constant
    tap = ops["side_tap"]
    assert tap["sketch"]["plane"] == "YZ" and tap["meta"] == {"ShilpaThread": "M10x1.5 depth 12 mm"}
    assert tap["sketch"]["offset"]["e"] == "(cbores.Shape.BoundBox.XMax * 1 mm)" and tap["reversed"] is False
    csk = {op["id"]: op for op in lowered("N06")}["csk_holes_csk"]
    assert csk["taper"] == {"v": -45.0} and csk["length"]["v"] == pytest.approx(2.85)


def test_lowering_rejects_mirror_without_original():
    rec = copy.deepcopy(fixture("N08")["recipe"])
    rec["features"][-1]["keep_original"] = False
    res = built(rec)
    with pytest.raises(ShilpaError) as ei:
        freecad_adapter.lower(res.compiled, [asdict(f) for f in res.features])
    assert ei.value.code == ErrorCode.UNSUPPORTED_OPERATION


@pytest.mark.skipif(not freecad_adapter.available(), reason="FreeCAD not installed")
@pytest.mark.parametrize("fid", ["N07", "N14"])
def test_freecad_native_build_matches(fid, tmp_path):
    fx = fixture(fid)
    res = execute({**fx["recipe"], "exports": ["STEP", "FCSTD"]}, tmp_path, oracle=fx["oracle"])
    fc = [c for c in res.validation["checks"] if c["name"].startswith("freecad")]
    assert res.ok and fc and all(c["passed"] for c in fc), [c for c in fc if not c["passed"]]
