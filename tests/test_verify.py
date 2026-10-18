"""Requirement tests, test generation plumbing and mutation scoring on analytic parts (no network)."""

import json
import math
from pathlib import Path

import build123d as bd
import pytest

from shilpa.adapters import build123d_adapter as adapter
from shilpa.verify.mutants import evaluate_mutants, make_mutants, mutation_score
from shilpa.verify.requirements import MAX_LEN_TOL, Probe, RequirementTest, aggregate, run_tests
from shilpa.verify.testgen import to_tests

from .test_contracts import BLUEPRINT_PLATE

CORPUS = Path(__file__).resolve().parents[1] / "evals" / "corpus"


def fixture(fid: str) -> dict:
    return json.loads((CORPUS / f"{fid}.json").read_text(encoding="utf-8"))


def shape_of(recipe: dict):
    b = adapter.build(recipe)
    assert b.ok, b.error
    return b.shape


def T(kind, **args):
    return {"id": f"t-{kind}", "requirement": kind, "kind": kind, "args": args}


PLATE_SUITE = [
    T("valid_solid"),
    T("solid_count", count=1),
    T("bbox", values=[80, 40, 8]),
    T("bbox_extent", axis="z", value=8),
    T("bbox_ratio", axis="x", other_axis="y", value=2),
    T("volume", value=80 * 40 * 8 - 4 * math.pi * 9 * 8),
    T("mass", density=7.85, value=(80 * 40 * 8 - 4 * math.pi * 9 * 8) * 7.85e-3),
    T("hole_count", count=4, diameter=6, through=True),
    T("hole_diameter", diameter=6, count=4),
    T("hole_depth", diameter=6, value=8),
    T("hole_edge_offset", value=10, diameter=6),
    T("hole_positions", diameter=6, points=[[30, 10], [-30, 10], [30, -10], [-30, -10]]),
    T("hole_distance", value=20, diameter=6, mode="nearest"),
    T("hole_distance", value=60, diameter=6),
    T("face_type_count", surface="plane", axis="z", count=2),
    T("face_type_count", surface="cylinder", axis="z", diameter=6, count=4, op="ge"),
    T("wall_thickness", value=8, mode="all"),
    T("symmetric", plane="yz"),
    T("symmetric", plane="xz"),
    T("centered", a={"type": "solid"}),
]


@pytest.fixture(scope="module")
def plate():
    return shape_of(BLUEPRINT_PLATE)


def test_plate_suite_passes_on_correct_part(plate):
    r = run_tests(PLATE_SUITE, plate)
    assert r.passed, [x for x in r.results if not x.passed]
    assert r.score == 1.0 and r.total == len(PLATE_SUITE)
    cats = {x.category for x in r.results}
    assert cats == {"validity", "topology", "geometric_type", "dimension", "volume", "spatial"}


def test_canonical_frame_ignores_planner_orientation(plate, tmp_path):
    turned = plate.rotate(bd.Axis.Z, 90).moved(bd.Location((13, -7, 5)))
    step = tmp_path / "turned.step"
    bd.export_step(turned, str(step))
    r = run_tests(PLATE_SUITE, step)  # STEP path: reimported, independent of the recipe
    assert r.passed, [x for x in r.results if not x.passed]


def test_wrong_part_fails_specific_requirements():
    bad = {**BLUEPRINT_PLATE, "parameters": {**BLUEPRINT_PLATE["parameters"], "edge_offset": 12}}
    r = run_tests(PLATE_SUITE, shape_of(bad))
    failed = {x.kind for x in r.results if not x.passed}
    assert not r.passed and 0 < r.score < 1
    assert {"hole_edge_offset", "hole_positions", "hole_distance"} <= failed
    assert "bbox" not in failed and "volume" not in failed  # moving holes keeps size and volume


def test_blind_hole_depth_and_position():
    recipe = {
        "units": "mm", "parameters": {"w": 50, "d": 30, "h": 20, "hd": 10, "depth": 12},
        "features": [
            {"id": "p", "op": "centered_rectangle", "width_ref": "w", "height_ref": "d"},
            {"id": "b", "op": "extrude", "profile_ref": "p", "distance_ref": "h", "direction": "positive_z"},
            {"id": "hole1", "op": "hole", "body_ref": "b", "diameter_ref": "hd", "mode": "blind", "depth_ref": "depth"},
        ],
    }
    s = shape_of(recipe)
    suite = [T("hole_count", count=1, diameter=10, through=False), T("hole_count", count=0, through=True),
             T("hole_depth", diameter=10, value=12), T("centered", a={"type": "hole", "diameter": 10}),
             T("relative_position", a={"type": "hole", "diameter": 10}, b={"type": "solid"}, axis="z", relation="gt")]
    assert run_tests(suite, s).passed


def test_stepped_shaft_order_lengths_and_concentricity():
    s = shape_of(fixture("H02")["recipe"])  # 25x10, 18x40, 12x25 from the bottom up

    def up(a, b):
        return T("relative_position", a={"type": "boss", "diameter": a}, b={"type": "boss", "diameter": b}, axis="z", relation="gt")

    suite = [T("cylinder", type="boss", diameter=25, length=10, axis="z"),
             T("cylinder", type="boss", diameter=18, length=40, axis="z"),
             T("cylinder", type="boss", diameter=12, length=25, axis="z"),
             up(18, 25), up(12, 18),
             T("concentric", a={"type": "boss", "diameter": 12}, b={"type": "boss", "diameter": 25})]
    assert run_tests(suite, s).passed
    assert not run_tests([up(25, 18)], s).passed  # reversed order is caught


def test_flange_bolt_circle_and_phase():
    s = shape_of(fixture("F02")["recipe"])  # 6 x 14 on PCD 115, first hole at 30 deg, 60 bore
    suite = [T("hole_pattern_circle", pcd=115, diameter=14, count=6), T("hole_angular_phase", value=30, diameter=14),
             T("concentric", a={"type": "hole", "diameter": 60}, b={"type": "boss", "diameter": 150})]
    assert run_tests(suite, s).passed
    assert not run_tests([T("hole_angular_phase", value=0, diameter=14)], s).passed
    assert not run_tests([T("hole_pattern_circle", pcd=110, diameter=14)], s).passed


def test_box_walls_fillets_and_chamfers():
    e02 = shape_of(fixture("E02")["recipe"])  # R6 outer, R3.5 inner, walls 2.5, floor 3
    assert run_tests([T("edge_radius", radius=6, count=4, convexity="convex"),
                      T("edge_radius", radius=3.5, count=4, convexity="concave"),
                      T("wall_thickness", value=2.5),
                      T("wall_thickness", values=[2.5, 3], mode="all")], e02).passed
    assert not run_tests([T("wall_thickness", value=2.5, mode="all")], e02).passed  # the 3 mm floor is a different wall
    s05 = shape_of(fixture("S05")["recipe"])  # 1 mm chamfer on the outer edge
    assert run_tests([T("chamfer", distance=1, count=1), T("face_type_count", surface="cone", count=1)], s05).passed


def test_asymmetry_is_detected():
    off = {**BLUEPRINT_PLATE, "features": BLUEPRINT_PLATE["features"][:2] + [
        {"id": "h", "op": "hole", "body_ref": "base_solid", "diameter_ref": "hole_diameter", "center_x_ref": "edge_offset"}]}
    r = run_tests([T("symmetric", plane="yz"), T("symmetric", plane="xz")], shape_of(off))
    assert [x.passed for x in r.results] == [False, True]


def test_missing_geometry_and_broken_tests_fail_cleanly(plate):
    r = run_tests(PLATE_SUITE, None)
    assert not r.passed and r.score == 0 and r.error == "no geometry"
    r = run_tests([T("hole_count"), T("feature_distance", a={"type": "boss", "diameter": 99}, b={"type": "solid"}, value=1)], plate)
    assert r.failed == 2 and all(x.note for x in r.results)
    assert not run_tests([], plate).passed
    agg = aggregate([run_tests(PLATE_SUITE, plate), None])
    assert agg["pass_rate"] == 0.5 and agg["requirement_score"] == 0.5


def test_generated_suite_conversion_and_tolerance_ceiling():
    raw = {"tests": [
        {"requirement": "four 6 mm holes", "kind": "hole_count", "count": 4, "diameter": 6.0, "through": True, "tol": None},
        {"requirement": "loose", "kind": "bbox", "values": [80, 40, 8], "tol": 25.0},
        {"requirement": "hub on top", "kind": "relative_position", "a": {"type": "boss", "diameter": 60, "which": None},
         "b": {"type": "boss", "diameter": 120, "which": None}, "axis": "z", "relation": "gt"},
        {"requirement": "nonsense", "kind": "teleport"},
    ], "notes": None}
    tests, problems = to_tests(raw, "L999-G")
    assert [t.id for t in tests] == ["L999-G-01", "L999-G-02", "L999-G-03"] and len(problems) == 1
    assert tests[1].tol == MAX_LEN_TOL
    assert tests[2].args["a"] == {"type": "boss", "diameter": 60, "which": "all"}
    assert all(isinstance(t, RequirementTest) for t in tests)


def test_mutants_are_killed_and_equivalents_excluded(plate, tmp_path):
    muts = make_mutants(BLUEPRINT_PLATE, seed=1)
    ops = {m.operator for m in muts}
    assert {"dim", "drop"} <= ops
    weak = [T("valid_solid"), T("bbox", values=[80, 40, 8])]
    ev = evaluate_mutants(BLUEPRINT_PLATE, muts, {"full": PLATE_SUITE, "weak": weak}, tmp_path)
    assert ev["reference_passes"] == {"full": True, "weak": True}
    full, weak_s = mutation_score([ev], "full"), mutation_score([ev], "weak")
    assert full["score"] == 1.0
    assert weak_s["score"] < full["score"]  # a size-only oracle misses dropped holes and hole-size changes
    assert any("drop" in s for s in weak_s["survivors"])


def test_mirror_of_symmetric_part_is_equivalent(tmp_path):
    recipe = fixture("B01")["recipe"]  # L bracket: leg at the back; a mirrored leg is the same part turned 180 degrees
    muts = make_mutants(recipe, seed=0, operators=("mirror", "move"))
    ev = evaluate_mutants(recipe, muts, {"s": [T("valid_solid")]}, tmp_path)
    status = {m["description"]: m["status"] for m in ev["mutants"]}
    mirrors = [v for k, v in status.items() if k.startswith("mirror")]
    assert mirrors and all(v == "equivalent" for v in mirrors)
    assert any(v == "evaluated" for k, v in status.items() if k.startswith("move leg_profile"))


def test_probe_cylinder_kinds(plate):
    p = Probe(plate)
    assert sorted(c.kind for c in p.cylinders) == ["hole"] * 4
    assert all(p.is_through(c) for c in p.cylinders)
