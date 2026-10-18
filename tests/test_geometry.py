"""Geometry acceptance tests from the workbook (T001, T002, T009-T012, T016-T018)."""

import copy
import json
import math
from pathlib import Path

import pytest

from shilpa.adapters import build123d_adapter as adapter
from shilpa.contracts.errors import ErrorCode
from shilpa.pipeline import execute
from shilpa.validators.geometry import hole_groups

from .test_contracts import BLUEPRINT_PLATE, with_params


def checks(res) -> dict:
    return {c["name"]: c for c in res.validation["checks"]}


def test_analytic_plate(tmp_path):  # T001
    res = execute(BLUEPRINT_PLATE, tmp_path, oracle={"bbox": [80, 40, 8], "volume": 24695.2213, "solid_count": 1,
                                                      "hole_centers": {"diameter": 6, "centers": [[-30, -10], [-30, 10], [30, -10], [30, 10]]}})
    assert res.ok, res.error
    m = res.validation["measurement"]
    assert m["bbox_size"] == [80, 40, 8]
    assert m["volume"] == pytest.approx(80 * 40 * 8 - 4 * math.pi * 9 * 8, rel=1e-6)
    assert checks(res)["oracle_hole_centers"]["passed"]


def test_width_edit_moves_holes_and_keeps_offset(tmp_path):  # T002
    res = execute(with_params(width=100), tmp_path, oracle={"bbox": [100, 40, 8],
                  "hole_centers": {"diameter": 6, "centers": [[-40, -10], [-40, 10], [40, -10], [40, 10]]}})
    assert res.ok, res.error
    assert checks(res)["oracle_hole_centers"]["passed"]


def test_overlapping_holes_rejected(tmp_path):  # T009
    r = copy.deepcopy(BLUEPRINT_PLATE)
    r["parameters"].update(d=6, pitch=4, n={"value": 2, "kind": "count"}, one={"value": 1, "kind": "count"})
    r["features"][2] = {"id": "grid", "op": "linear_hole_pattern", "body_ref": "base_solid", "diameter_ref": "d",
                        "count_x_ref": "n", "count_y_ref": "one", "pitch_x_ref": "pitch", "pitch_y_ref": "pitch"}
    res = execute(r, tmp_path)
    assert not res.ok and res.error.code == ErrorCode.PRECONDITION_FAILED
    assert "overlap" in res.error.message


def test_hole_edge_clearance_rejected(tmp_path):  # T010
    res = execute(with_params(hole_diameter=20), tmp_path)
    assert not res.ok and res.error.code == ErrorCode.PRECONDITION_FAILED
    assert not (tmp_path / "model.step").exists()


def test_hole_off_the_part_rejected(tmp_path):
    r = copy.deepcopy(BLUEPRINT_PLATE)
    r["parameters"].update(x=38)
    r["features"][2] = {"id": "h", "op": "hole", "body_ref": "base_solid", "diameter_ref": "hole_diameter", "center_x_ref": "x"}
    res = execute(r, tmp_path)
    assert not res.ok and res.error.code == ErrorCode.PRECONDITION_FAILED


def test_excessive_fillet_is_structured_kernel_failure(tmp_path):  # T011
    r = copy.deepcopy(BLUEPRINT_PLATE)
    r["parameters"]["r"] = 30
    r["features"].insert(2, {"id": "round", "op": "fillet", "body_ref": "base_solid", "radius_ref": "r",
                             "edges": {"direction": "parallel_z", "boundary": "outer", "expected_count": 4}})
    r["features"][3]["body_ref"] = "round"
    res = execute(r, tmp_path)
    assert not res.ok
    assert res.error.code in (ErrorCode.KERNEL_FAILURE, ErrorCode.PRECONDITION_FAILED)
    assert res.error.feature_id == "round" and res.error.retryable


def test_selector_cardinality_is_enforced(tmp_path):  # T012
    r = copy.deepcopy(BLUEPRINT_PLATE)
    r["parameters"]["r"] = 2
    r["features"].append({"id": "round", "op": "fillet", "body_ref": "mount_holes", "radius_ref": "r",
                          "edges": {"direction": "parallel_z", "boundary": "outer", "expected_count": 2}})
    res = execute(r, tmp_path)
    assert not res.ok and res.error.code == ErrorCode.SELECTOR_AMBIGUOUS
    assert res.error.details == {"matched": 4, "expected": 2}


def test_roundtrip_stl_and_glb_scale(tmp_path):  # T016 T017 T018
    res = execute(BLUEPRINT_PLATE, tmp_path)
    c = checks(res)
    assert c["step_roundtrip_volume"]["passed"]
    assert c["stl_watertight"]["passed"] and c["stl_extent_mm"]["passed"]
    assert c["glb_extent_m"]["passed"]
    assert sorted(c["glb_extent_m"]["actual"]) == pytest.approx(sorted([0.08, 0.04, 0.008]), abs=5e-5)
    units = json.loads((tmp_path / "model.stl.units.json").read_text())
    assert units["units"] == "mm"


def test_cancel_between_operations(tmp_path):
    from shilpa.contracts.errors import ShilpaError

    calls = {"n": 0}

    def cancel():
        calls["n"] += 1
        return calls["n"] > 1

    with pytest.raises(ShilpaError) as ei:
        adapter.build(BLUEPRINT_PLATE, cancel_check=cancel)
    assert ei.value.code == ErrorCode.CANCELLED


def test_hole_detection_counts_unique_axes(tmp_path):
    res = execute(BLUEPRINT_PLATE, tmp_path)
    from shilpa.validators.geometry import Measurement, Cylinder

    m = res.validation["measurement"]
    cyl = [Cylinder(c["diameter"], tuple(c["axis"]), tuple(c["center"]), c["kind"]) for c in m["cylinders"]]
    meas = Measurement(**{**m, "cylinders": cyl})
    assert hole_groups(meas) == {6.0: 4}


@pytest.mark.parametrize("cutter_length,direction", [("thickness * 2", "symmetric"), ("thickness", "positive_z")])
def test_boolean_cut_cannot_notch_through_a_wall(tmp_path, cutter_length, direction):  # regression: G2 L051 (both runs)
    r = copy.deepcopy(BLUEPRINT_PLATE)
    r["parameters"].update(width=50, height=50, thickness=5, r=10, d=8, e=5)
    r["features"] = [
        {"id": "outline", "op": "centered_rectangle", "width_ref": "width", "height_ref": "height", "corner_radius_ref": "r"},
        {"id": "plate", "op": "extrude", "profile_ref": "outline", "distance_ref": "thickness"},
        {"id": "hole_profile", "op": "circle", "diameter_ref": "d", "center_x_ref": "width / 2 - e", "center_y_ref": "height / 2 - e"},
        {"id": "cutter", "op": "extrude", "profile_ref": "hole_profile", "distance_ref": cutter_length, "direction": direction},
        {"id": "cut", "op": "boolean", "operation": "cut", "target_ref": "plate", "tool_ref": "cutter"},
    ]
    res = execute(r, tmp_path)
    assert not res.ok and res.error.code == ErrorCode.PRECONDITION_FAILED and res.error.feature_id == "cut"


def test_boolean_cut_inside_is_allowed(tmp_path):
    r = copy.deepcopy(BLUEPRINT_PLATE)
    r["features"] = BLUEPRINT_PLATE["features"][:2] + [
        {"id": "hp", "op": "circle", "diameter_ref": "hole_diameter"},
        {"id": "cutter", "op": "extrude", "profile_ref": "hp", "distance_ref": "thickness * 2", "direction": "symmetric"},
        {"id": "cut", "op": "boolean", "operation": "cut", "target_ref": "base_solid", "tool_ref": "cutter"},
    ]
    assert execute(r, tmp_path).ok


def test_single_row_pattern_allows_zero_pitch(tmp_path):  # regression: G2 L025
    r = copy.deepcopy(BLUEPRINT_PLATE)
    r["parameters"].update(n={"value": 2, "kind": "count"}, one={"value": 1, "kind": "count"}, pitch=40, zero=0)
    r["features"][2] = {"id": "row", "op": "linear_hole_pattern", "body_ref": "base_solid", "diameter_ref": "hole_diameter",
                        "count_x_ref": "n", "count_y_ref": "one", "pitch_x_ref": "pitch", "pitch_y_ref": "zero"}
    assert execute(r, tmp_path).ok


def test_large_round_part_mesh_checks(tmp_path):  # regression: 180 mm flange failed fixed 0.05 mm mesh tolerance
    import json as _json
    from pathlib import Path as _P

    fx = _json.loads((_P(__file__).resolve().parents[1] / "evals" / "corpus" / "F02.json").read_text())
    r = copy.deepcopy(fx["recipe"])
    r["parameters"].update(outer_diameter=180, thickness=18, bore_diameter=75, bolt_diameter=13.5, pitch_diameter=145)
    r["assertions"].pop("holes", None)
    res = execute(r, tmp_path)
    assert res.ok, [c for c in res.validation["checks"] if not c["passed"]]
