"""Offline gold-test derivation from recipes and the verify_part convenience (no network)."""

import copy
import json
from pathlib import Path

import build123d as bd
import pytest

from shilpa.adapters import build123d_adapter as adapter
from shilpa.contracts.compile import compile_recipe
from shilpa.verify.gold import DerivedSuite, derive_tests, verify_part
from shilpa.verify.mutants import evaluate_mutants, make_mutants, mutation_score
from shilpa.verify.requirements import RequirementTest

CORPUS = Path(__file__).resolve().parents[1] / "evals" / "corpus"
REPRESENTATIVE = ["P01", "F01", "N07", "S05", "E04", "B04"]


def recipe(fid: str) -> dict:
    return json.loads((CORPUS / f"{fid}.json").read_text(encoding="utf-8"))["recipe"]


@pytest.fixture(scope="module")
def builds():
    out = {}
    for fid in REPRESENTATIVE:
        b = adapter.build(recipe(fid))
        assert b.ok, b.error
        out[fid] = b
    return out


def kinds(suite: DerivedSuite) -> set[str]:
    return {t.kind for t in suite.tests}


def find(suite: DerivedSuite, kind: str, **args) -> RequirementTest:
    for t in suite.tests:
        if t.kind == kind and all(t.args.get(k) == v for k, v in args.items()):
            return t
    raise AssertionError(f"no {kind} {args} in {[(t.kind, t.args) for t in suite.tests]}")


# ---------------------------------------------------------------- derivation content


def test_plate_derivation_from_recipe_alone():
    s = derive_tests(recipe("P01"))
    find(s, "valid_solid")
    find(s, "bbox", values=[80.0, 40.0, 8.0])
    find(s, "hole_count", diameter=6.0, count=4)
    find(s, "hole_count", diameter=6.0, count=4, through=True)
    find(s, "hole_edge_offset", value=10.0, diameter=6.0)
    assert "hole_positions" not in kinds(s)  # absolute positions need the nominal bounding box
    assert not s.dropped


def test_compiled_recipe_input_matches_dict_input():
    a = derive_tests(recipe("F01"))
    b = derive_tests(compile_recipe(recipe("F01")))
    assert [t.model_dump() for t in a.tests] == [t.model_dump() for t in b.tests]


def test_flange_counts_bore_and_bolt_circle():
    s = derive_tests(recipe("F01"))
    find(s, "hole_count", diameter=10.0, count=4)
    find(s, "hole_count", diameter=40.0, count=1)
    find(s, "hole_pattern_circle", pcd=70.0, diameter=10.0, count=4)


def test_hole_series_uses_drill_diameters_and_side_faces(builds):
    s = derive_tests(recipe("N07"), build=builds["N07"])
    # M8 counterbore: 9 mm clearance drill through, 15 mm counterbore cylinder 8.6 deep (ISO table)
    find(s, "hole_count", diameter=9.0, count=2, through=True)
    cb = find(s, "hole_count", diameter=15.0, count=2)
    assert "through" not in cb.args
    find(s, "hole_depth", diameter=15.0)
    # M10 tapped side port: 8.5 tap drill, blind 15 deep from x_max
    find(s, "hole_count", diameter=8.5, count=1, through=False)
    find(s, "hole_depth", diameter=8.5, value=15.0)
    pos = find(s, "hole_positions", diameter=8.5)
    assert pos.args["points"] == [[15.0, 10.0]]  # (Y, Z) on a side face, Z from the bottom
    find(s, "hole_distance", value=50.0, diameter=9.0, mode="nearest")
    assert not s.dropped


def test_edge_treatments_need_a_build(builds):
    assert "chamfer" not in kinds(derive_tests(recipe("E04")))
    s = derive_tests(recipe("E04"), build=builds["E04"])
    find(s, "chamfer", distance=1.5)
    s = derive_tests(recipe("B04"), build=builds["B04"])
    find(s, "edge_radius", radius=6.0)
    find(s, "hole_positions", diameter=10.5)


def test_body_mirror_suppresses_hole_counts():
    s = derive_tests(recipe("N08"))
    assert "hole_count" not in kinds(s)
    assert any("mirror" in n for n in s.notes)


def test_sanity_filter_relaxes_and_drops(builds):
    r = copy.deepcopy(recipe("P01"))
    # The assertion says 4 holes; an extra centre hole of the same diameter makes it 5.
    r["features"].append({"id": "extra", "op": "hole", "body_ref": "mount_holes", "diameter_ref": "hole_diameter"})
    b = adapter.build(r)
    assert b.ok
    s = derive_tests(r, build=b)
    assert all(verify_part(b, [t]).passed for t in s.tests)
    # 5 holes now, so the corner pattern no longer owns every Ø6 hole: no edge offset is derived at all,
    # and the assertion count (4) fails on the nominal part and is relaxed to >= 4.
    assert "hole_edge_offset" not in kinds(s)
    assert any("relaxed" in n for n in s.notes)


def test_nominal_flag_pins_size_and_volume(builds):
    s = derive_tests(recipe("E04"), build=builds["E04"], nominal=True)
    v = find(s, "volume")
    assert v.args["value"] == pytest.approx(builds["E04"].shape.volume)


# ---------------------------------------------------------------- the derived suites pass the nominal part


@pytest.mark.parametrize("fid", REPRESENTATIVE)
def test_derived_suite_passes_nominal_and_step(fid, builds, tmp_path):
    b = builds[fid]
    s = derive_tests(recipe(fid), build=b)
    assert not s.dropped, s.dropped
    assert len(s) >= 3
    res = verify_part(b, s)
    assert res.passed, [r for r in res.results if not r.passed]
    step = tmp_path / f"{fid}.step"
    bd.export_step(b.shape, str(step))
    res = verify_part(step, s.to_dicts())
    assert res.passed, [r for r in res.results if not r.passed]
    # recipe-only derivation is valid on the nominal part too
    assert verify_part(b.shape, derive_tests(recipe(fid))).passed


# ---------------------------------------------------------------- verify_part errors


def test_verify_part_errors(builds, tmp_path):
    suite = derive_tests(recipe("P01")).tests
    with pytest.raises(FileNotFoundError):
        verify_part(tmp_path / "missing.step", suite)
    (tmp_path / "x.txt").write_text("x")
    with pytest.raises(ValueError):
        verify_part(tmp_path / "x.txt", suite)
    with pytest.raises(TypeError):
        verify_part(42, suite)
    with pytest.raises(ValueError, match="malformed"):
        verify_part(builds["P01"], [{"id": "bad", "kind": "not_a_kind", "requirement": "x"}])

    class Failed:
        shape = None
        error = "boom"

    with pytest.raises(ValueError, match="boom"):
        verify_part(Failed(), suite)
    # a single dict and a shape are fine
    assert verify_part(builds["P01"].shape, {"id": "v", "kind": "valid_solid", "requirement": "valid"}).passed


# ---------------------------------------------------------------- teeth


def test_derived_suite_kills_mutants():
    r = recipe("P01")
    suite = derive_tests(r, build=adapter.build(r)).to_dicts()
    muts = [m for m in make_mutants(r, seed=0) if m.operator in ("dim", "count", "drop")]
    ev = evaluate_mutants(r, muts, {"derived": suite})
    assert ev["reference_passes"]["derived"]
    score = mutation_score([ev], "derived")
    assert score["evaluated"] >= 4
    assert score["score"] >= 0.8, score["survivors"]
