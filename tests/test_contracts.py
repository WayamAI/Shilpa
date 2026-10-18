"""Static IR checks that run before any geometry (T007, T008, T013, T014, T015, T026)."""

import math

import pytest

from shilpa.adapters import CAPABILITIES
from shilpa.agent.llm import strict_schema
from shilpa.agent.planner import apply_clarification_policy, apply_parameter_edit
from shilpa.agent.schemas import PlanOutput, Requirements, from_recipe, to_recipe
from shilpa.contracts import expr
from shilpa.contracts.compile import compile_recipe
from shilpa.contracts.errors import ErrorCode, ShilpaError

# The worked example from blueprint section 8, verbatim.
BLUEPRINT_PLATE = {
    "schema_version": "1.0",
    "intent": "engineering_cad",
    "units": "mm",
    "parameters": {"width": 80, "height": 40, "thickness": 8, "hole_diameter": 6, "edge_offset": 10},
    "frame": {"origin": [0, 0, 0], "normal": [0, 0, 1]},
    "features": [
        {"id": "base_profile", "op": "centered_rectangle", "plane": "XY", "width_ref": "width", "height_ref": "height"},
        {"id": "base_solid", "op": "extrude", "profile_ref": "base_profile", "distance_ref": "thickness", "direction": "positive_z"},
        {"id": "mount_holes", "op": "corner_hole_pattern", "body_ref": "base_solid", "diameter_ref": "hole_diameter",
         "edge_offset_ref": "edge_offset", "mode": "through_all"},
    ],
    "assertions": {"solid_count": 1, "valid_brep": True},
    "exports": ["STEP", "STL", "GLB"],
}


def with_params(**overrides):
    r = {**BLUEPRINT_PLATE, "parameters": {**BLUEPRINT_PLATE["parameters"], **overrides}}
    return r


def code_of(recipe) -> ErrorCode:
    with pytest.raises(ShilpaError) as ei:
        compile_recipe(recipe, CAPABILITIES)
    return ei.value.code


def test_blueprint_example_compiles():
    c = compile_recipe(BLUEPRINT_PLATE, CAPABILITIES)
    assert c.output_id == "mount_holes"
    assert c.features[1].values["distance_ref"] == 8


def test_negative_thickness_rejected_before_execution():  # T007
    assert code_of(with_params(thickness=-8)) == ErrorCode.INVALID_PARAMETER


def test_zero_thickness_rejected():  # T008
    assert code_of(with_params(thickness=0)) == ErrorCode.INVALID_PARAMETER


def test_nonfinite_rejected():  # T015
    assert code_of(with_params(width=math.inf)) == ErrorCode.INVALID_PARAMETER
    assert code_of(with_params(width=math.nan)) == ErrorCode.INVALID_PARAMETER


def test_inch_units_normalised_with_evidence():  # T013
    r = {**BLUEPRINT_PLATE, "units": "in", "parameters": {"width": 4, "height": 2, "thickness": 0.25, "hole_diameter": 0.25, "edge_offset": 0.5}}
    c = compile_recipe(r, CAPABILITIES)
    assert c.params["width"].value == pytest.approx(101.6)
    assert any(e.parameter == "width" and e.source_unit == "in" for e in c.conversions)


def test_angle_units_and_kind_safety():  # T014
    q = {"x": expr.Quantity(10, "length"), "a": expr.Quantity(30, "angle")}
    with pytest.raises(ShilpaError) as ei:
        expr.evaluate("x + a", q)
    assert ei.value.code == ErrorCode.UNIT_MISMATCH
    r = with_params(start=dict(value=math.pi / 6, kind="angle", unit="rad"))
    assert compile_recipe(r, CAPABILITIES).params["start"].value == pytest.approx(30)


def test_angle_in_length_field_rejected():
    r = with_params(a={"value": 10, "kind": "angle"})
    r["features"] = [dict(r["features"][0], width_ref="a"), *r["features"][1:]]
    assert code_of(r) == ErrorCode.UNIT_MISMATCH


def test_expression_is_not_eval():
    for bad in ("__import__('os')", "width.__class__", "[1,2]", "width if 1 else 2", "width ** 2", "lambda: 1"):
        with pytest.raises(ShilpaError):
            expr.parse(bad)
    assert expr.evaluate("width / 2 - edge", {"width": expr.Quantity(80, "length"), "edge": expr.Quantity(10, "length")}).value == 30


def test_parameter_cycle_detected():
    r = with_params(width={"expr": "height * 2"}, height={"expr": "width / 2"})
    assert code_of(r) == ErrorCode.REFERENCE_CYCLE


def test_unknown_reference():
    r = dict(BLUEPRINT_PLATE)
    r["features"] = [dict(r["features"][0], width_ref="wdith"), *r["features"][1:]]
    assert code_of(r) == ErrorCode.UNKNOWN_REFERENCE


def test_unsupported_operation_before_worker():  # T026
    assert code_of({**BLUEPRINT_PLATE, "features": [{"id": "blade", "op": "loft_freeform"}]}) == ErrorCode.INVALID_SCHEMA
    with pytest.raises(ShilpaError) as ei:
        compile_recipe(BLUEPRINT_PLATE, {"centered_rectangle", "extrude"})
    assert ei.value.code == ErrorCode.UNSUPPORTED_OPERATION


def test_feature_reference_must_be_earlier_and_right_kind():
    r = dict(BLUEPRINT_PLATE)
    r["features"] = [r["features"][0], dict(r["features"][1], profile_ref="mount_holes"), r["features"][2]]
    assert code_of(r) == ErrorCode.UNKNOWN_REFERENCE


def test_extra_fields_rejected():
    r = dict(BLUEPRINT_PLATE)
    r["features"] = [dict(r["features"][0], python="import os"), *r["features"][1:]]
    assert code_of(r) == ErrorCode.INVALID_SCHEMA


def test_parameter_edit_is_deterministic():
    out = apply_parameter_edit(BLUEPRINT_PLATE, {"width": 100})
    assert out["parameters"]["width"] == 100 and BLUEPRINT_PLATE["parameters"]["width"] == 80
    with pytest.raises(ShilpaError):
        apply_parameter_edit(BLUEPRINT_PLATE, {"nope": 1})


def test_plan_roundtrip_and_strict_schema():
    plan = from_recipe(BLUEPRINT_PLATE)
    assert compile_recipe(to_recipe({**plan, "change_summary": None}), CAPABILITIES).output_id == "mount_holes"
    for model in (PlanOutput, Requirements):
        s = strict_schema(model.model_json_schema())

        def walk(n):
            if isinstance(n, dict):
                if n.get("type") == "object" and "properties" in n:
                    assert n["additionalProperties"] is False
                    assert set(n["required"]) == set(n["properties"])
                assert "default" not in n and "const" not in n
                for v in n.values():
                    walk(v)
            elif isinstance(n, list):
                for v in n:
                    walk(v)

        walk(s)


def _req(**kw):
    base = {"task_class": "engineering_cad", "family": "plate", "summary": "plate", "units": "mm", "dimensions": [], "features": [],
            "missing": [], "conflicts": [], "unsupported_reason": None}
    return {**base, **kw}


def test_clarification_policy():  # T022 T023 T024 T026
    missing = _req(missing=[{"name": "hole_diameter", "question": "Hole diameter?", "critical": True}])
    assert apply_clarification_policy(missing)["status"] == "needs_clarification"
    no_units = apply_clarification_policy(_req(units=None))
    assert no_units["status"] == "ready" and no_units["units_source"] == "project default"
    conflict = _req(conflicts=[{"description": "overall length differs from sum", "fields": ["a", "b"]}])
    assert apply_clarification_policy(conflict)["status"] == "needs_clarification"
    assert apply_clarification_policy(_req(task_class="visual_asset"))["status"] == "unsupported"
    null_critical = _req(dimensions=[{"name": "thickness", "value": None, "unit": None, "kind": "length", "critical": True, "source": "user", "evidence": None}])
    assert apply_clarification_policy(null_critical)["status"] == "needs_clarification"


def test_requirements_coverage_catches_dropped_feature():  # regression: gpt-5-mini omitted a requested bore
    from shilpa.agent.planner import check_requirements

    req = {"units": "mm", "dimensions": [
        {"name": "width", "value": 80, "unit": "mm", "kind": "length", "source": "user"},
        {"name": "hole_diameter", "value": 6, "unit": "mm", "kind": "length", "source": "user"},
        {"name": "bore", "value": 20, "unit": "mm", "kind": "length", "source": "user"},
        {"name": "hole_count", "value": 4, "unit": None, "kind": "count", "source": "user"},
    ]}
    with pytest.raises(ShilpaError) as ei:
        check_requirements(BLUEPRINT_PLATE, req)
    assert ei.value.code == ErrorCode.REQUIREMENT_NOT_MET and "bore" in ei.value.info.message
    req["dimensions"].pop(2)
    check_requirements(BLUEPRINT_PLATE, req)  # every stated length is used
    inch = {"units": "in", "dimensions": [{"name": "w", "value": 80 / 25.4, "unit": "in", "kind": "length", "source": "user"}]}
    check_requirements(BLUEPRINT_PLATE, inch)  # matched after unit normalisation


def test_requirements_check_ignores_private_keys():  # regression: repair paths carry _change_summary
    from shilpa.agent.planner import check_requirements

    check_requirements({**BLUEPRINT_PLATE, "_change_summary": "fixed"}, {"units": "mm", "dimensions": []})
    absent = {"name": "centre_bore_diameter", "value": 0, "unit": "mm", "kind": "length", "source": "user"}
    check_requirements(BLUEPRINT_PLATE, {"units": "mm", "dimensions": [absent]})  # regression: G2 L010 "no centre bore"


def test_requirements_chamfer_angle_is_implicit():  # regression: drawing S05 "1 X 45°"
    import copy

    from shilpa.agent.planner import check_requirements

    r = copy.deepcopy(BLUEPRINT_PLATE)
    r["parameters"]["c"] = 1
    r["features"].append({"id": "edge", "op": "chamfer", "body_ref": "mount_holes", "distance_ref": "c",
                          "edges": {"direction": "perpendicular_z", "location": "top", "curve": "line", "boundary": "outer", "expected_count": 4}})
    angle = {"name": "chamfer_angle", "value": 45, "unit": "deg", "kind": "angle", "source": "drawing"}
    check_requirements(r, {"units": "mm", "dimensions": [angle]})
    with pytest.raises(ShilpaError):
        check_requirements(BLUEPRINT_PLATE, {"units": "mm", "dimensions": [angle]})  # no chamfer: 45 deg is unexplained


def test_relational_conflicts():  # regression: hard design X12 (hub larger than flange)
    def dim(n, v):
        return {"name": n, "value": v, "unit": "mm", "kind": "length", "critical": True, "source": "user", "evidence": None}

    bad = apply_clarification_policy(_req(family="flange", dimensions=[dim("outer_diameter", 80), dim("hub_diameter", 100), dim("bore_diameter", 30)]))
    assert bad["status"] == "needs_clarification" and any("hub_diameter" in c["description"] for c in bad["conflicts"])
    ok = apply_clarification_policy(_req(family="flange", dimensions=[dim("outer_diameter", 120), dim("hub_diameter", 60), dim("bore_diameter", 35), dim("bolt_circle_diameter", 90)]))
    assert ok["status"] == "ready" and not ok["conflicts"]


def test_plan_normalisation_and_error_explanation():  # regression: repair output rejected with an unhelpful union error
    from pydantic import ValidationError

    from shilpa.agent.planner import _explain_plan_error, _normalize_plan

    plan = from_recipe(BLUEPRINT_PLATE)
    plan["features"][0]["center_x_ref"] = ""  # strict mode cannot forbid empty strings
    plan.update(change_summary=None, name="t")
    PlanOutput.model_validate(_normalize_plan(plan))
    bad = from_recipe(BLUEPRINT_PLATE)
    bad.update(change_summary=None, name="t")
    bad["features"].append({"id": "r", "op": "fillet", "body_ref": "mount_holes", "radius_ref": "thickness",
                            "edges": {"direction": "parallel_z", "location": "any", "curve": "any", "boundary": "outer",
                                      "diameter_ref": None, "expected_count": 0}})
    with pytest.raises(ValidationError) as ei:
        PlanOutput.model_validate(bad)
    msg = _explain_plan_error(ei.value, bad)
    assert "fillet" in msg and "expected_count" in msg
