"""Persistent topology naming and IR 1.2 named selectors."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import build123d as bd
import pytest

from shilpa.adapters import build123d_adapter as adapter
from shilpa.adapters import freecad_adapter
from shilpa.contracts.compile import compile_recipe
from shilpa.contracts.errors import ErrorCode, ShilpaError
from shilpa.topology import name_map, refs, resolve
from shilpa.topology.robustness import run as robustness

CORPUS = Path(__file__).resolve().parents[1] / "evals" / "corpus"


def fixture(fid: str) -> dict:
    return copy.deepcopy(json.loads((CORPUS / f"{fid}.json").read_text(encoding="utf-8"))["recipe"])


def faces(res) -> set[str]:
    return {n for n, s in name_map(res).items() if s.kind == "face"}


def feature(recipe: dict, fid: str) -> dict:
    return next(f for f in recipe["features"] if f["id"] == fid)


# ---------------------------------------------------------------- references


def test_ref_grammar():
    assert refs.kind("hole_1.wall&plate.top") == "edges"
    assert refs.kind("pocket_2.floor") == "faces"
    assert refs.feature_ids("hole_1.wall&plate.top, row[*].boss.top.edges") == {"hole_1", "plate", "row"}
    for bad in ("", "Plate.top", "a&b&c", "hole_1.wall, hole_1.wall&plate.top", "x.y[", "a..b"):
        with pytest.raises(refs.RefSyntaxError):
            refs.kind(bad)


def test_ref_matching_and_generalisation():
    assert refs.matches("hole_1.wall[2]#1", "hole_1.wall") and refs.matches("hole_1.wall[2]", "hole_1.wall[2]")
    assert not refs.matches("hole_10.wall[0]", "hole_1") and not refs.matches("hole_1.walls", "hole_1.wall")
    assert refs.matches("row[3].boss.top", "row[*].boss.top") and not refs.matches("boss.top", "row[*].boss.top")
    assert refs.generalize("hole_1.wall[2]#1") == "hole_1.wall"
    assert refs.generalize("mirror_1[1].hole_1.wall[0]") == "mirror_1[*].hole_1.wall"


# ---------------------------------------------------------------- names


def test_names_follow_features_through_booleans_and_fillets():
    res = adapter.build(fixture("B04"))
    assert res.ok
    assert {"base.top", "base.bottom", "base.side.x_max", "leg.top", "leg.side.y_min", "base_holes.wall[0]",
            "base_holes.wall[1]", "inner_round.face[0]"} <= faces(res)
    # The bracket's inner edge is named by the two faces that meet there.
    pre = res.names["bracket"]
    kind, edges = pre.resolve("base.top&leg.side.y_min")
    assert kind == "edges" and len(edges) == 1


def test_names_for_pockets_shells_mirrors_and_patterns():
    assert {"cavity.floor", "cavity.wall.x_max", "box.top"} <= faces(adapter.build(fixture("E01")))
    assert {"enclosure.rim.block.top", "enclosure.inner.block.side.x_max", "enclosure.inner.block.bottom"} <= \
        faces(adapter.build(fixture("N05")))
    assert {"half.side.seg[1]", "half_drilled.wall[0]", "link[1].half_drilled.wall[0]"} <= faces(adapter.build(fixture("N08")))
    res = adapter.build(fixture("N10"))
    assert len(resolve("boss.top, boss_row[*].boss.top", res)) == 4
    assert len(resolve("holes.wall", res)) == 4


def test_every_corpus_body_is_named():
    for path in sorted(CORPUS.glob("*.json")):
        res = adapter.build(json.loads(path.read_text(encoding="utf-8"))["recipe"])
        assert res.ok, path.stem
        assert not [f.id for f in res.features if f.detail.get("naming_error")], path.stem
        assert set(res.names) >= {f.id for f in res.features if f.volume is not None}, path.stem


def test_resolve_by_signature_after_step_roundtrip(tmp_path):
    res = adapter.build(fixture("P03"))
    sigs = {n: s.to_dict() for n, s in name_map(res).items()}
    bd.export_step(res.shape, str(tmp_path / "p.step"))
    again = bd.import_step(str(tmp_path / "p.step"))
    walls = resolve("grid.wall", again, sigs)
    exact = resolve("grid.wall", res)
    assert len(walls) == len(exact) == 6
    assert sorted(round(f.center().X, 6) for f in walls) == sorted(round(f.center().X, 6) for f in exact)
    assert len(resolve("grid.wall&base_solid.top", again, sigs)) == 6


# ---------------------------------------------------------------- named selectors


def test_named_fillet_matches_heuristic():
    heuristic = adapter.build(fixture("B04"))
    rec = fixture("B04")
    feature(rec, "inner_round")["edges"] = {"ref": "base.top&leg.side.y_min", "expected_count": 1}
    named = adapter.build(rec)
    assert named.ok and abs(named.shape.volume - heuristic.shape.volume) < 1e-6
    detail = next(f for f in named.features if f.id == "inner_round").detail
    assert detail["refs"] == ["base.top&leg.side.y_min"] and len(detail["selected"]) == 1


def chamfered_p03(count_x: int, edges: dict) -> dict:
    rec = fixture("P03")
    rec["parameters"]["count_x"]["value"] = count_x
    rec["parameters"]["brk"] = 0.5
    rec["features"].append({"id": "entry_break", "op": "chamfer", "body_ref": "grid", "distance_ref": "brk", "edges": edges})
    rec["assertions"] = {}
    return rec


def test_named_chamfer_survives_a_count_edit_the_heuristic_does_not():
    heuristic = {"curve": "circle", "location": "top", "boundary": "inner", "expected_count": 6}
    named = {"ref": "grid.wall&base_solid.top"}
    assert adapter.build(chamfered_p03(3, heuristic)).ok and adapter.build(chamfered_p03(3, named)).ok
    broken = adapter.build(chamfered_p03(2, heuristic))
    assert broken.error.code == ErrorCode.SELECTOR_AMBIGUOUS
    res = adapter.build(chamfered_p03(2, named))
    assert res.ok and next(f for f in res.features if f.id == "entry_break").detail["edges"] == 4
    pinned = adapter.build(chamfered_p03(2, {**named, "expected_count": 6}))
    assert pinned.error.code == ErrorCode.SELECTOR_AMBIGUOUS


def test_named_shell_opening_matches_heuristic():
    heuristic = adapter.build(fixture("N05"))
    rec = fixture("N05")
    feature(rec, "enclosure")["open_faces"] = [{"ref": "block.top"}]
    named = adapter.build(rec)
    assert named.ok and abs(named.shape.volume - heuristic.shape.volume) < 1e-6


def test_hole_enters_a_named_lower_step():
    rec = {"parameters": {"w": 60, "d": 30, "t": 10, "step_w": 20, "step_h": 15, "hd": 5, "depth": 6},
           "features": [{"id": "base_o", "op": "centered_rectangle", "width_ref": "w", "height_ref": "d"},
                        {"id": "base", "op": "extrude", "profile_ref": "base_o", "distance_ref": "t"},
                        {"id": "step_o", "op": "centered_rectangle", "width_ref": "step_w", "height_ref": "d",
                         "center_x_ref": "w / 2 - step_w / 2"},
                        {"id": "step", "op": "extrude", "profile_ref": "step_o", "distance_ref": "step_h", "offset_ref": "t"},
                        {"id": "stepped", "op": "boolean", "operation": "union", "target_ref": "base", "tool_ref": "step"},
                        {"id": "drill", "op": "hole", "body_ref": "stepped", "diameter_ref": "hd", "mode": "blind",
                         "depth_ref": "depth", "center_x_ref": "-w / 4", "entry_face": {"ref": "base.top"}}]}
    res = adapter.build(rec)
    assert res.ok, res.error
    wall = resolve("drill.wall", res)[0]
    bb = wall.bounding_box()
    assert abs(bb.max.Z - 10) < 1e-6 and abs(bb.min.Z - 4) < 1e-6  # enters at the lower step, 6 deep
    assert next(f for f in res.features if f.id == "drill").detail["entry"] == 10
    with pytest.raises(ShilpaError) as ei:  # the FreeCAD lowering declines rather than mis-placing it
        freecad_adapter.lower(res.compiled, [f.__dict__ for f in res.features])
    assert ei.value.code == ErrorCode.UNSUPPORTED_OPERATION


def test_compile_checks_named_references():
    rec = fixture("B04")
    feature(rec, "inner_round")["edges"] = {"ref": "nope.top&leg.side.y_min"}
    with pytest.raises(ShilpaError) as ei:
        compile_recipe(rec)
    assert ei.value.code == ErrorCode.UNKNOWN_REFERENCE
    feature(rec, "inner_round")["edges"] = {"ref": "base.top"}  # faces where edges are needed
    with pytest.raises(ShilpaError) as ei:
        compile_recipe(rec)
    assert ei.value.code == ErrorCode.INVALID_SCHEMA


def test_unknown_role_is_a_repairable_selector_error():
    rec = fixture("B04")
    feature(rec, "inner_round")["edges"] = {"ref": "base.roof&leg.side.y_min"}
    res = adapter.build(rec)
    assert res.error.code == ErrorCode.SELECTOR_EMPTY and "base.top" in res.error.info.details["available"]


def test_freecad_lowering_carries_signatures():
    rec = fixture("B04")
    feature(rec, "inner_round")["edges"] = {"ref": "base.top&leg.side.y_min"}
    res = adapter.build(rec)
    plan = freecad_adapter.lower(res.compiled, [f.__dict__ for f in res.features])
    op = next(o for o in plan["ops"] if o["id"] == "inner_round")
    assert op["selector"]["expected_count"] == 1 and op["selector"]["signatures"][0]["geom"] == "LINE"


def test_selection_drift_flags_stale_freecad_references():
    res = adapter.build(chamfered_p03(2, {"ref": "grid.wall&base_solid.top"}))
    assert freecad_adapter.selection_drift(res, {"selections": [{"id": "entry_break", "subs": ["Edge1"] * 6}]})
    assert not freecad_adapter.selection_drift(res, {"selections": [{"id": "entry_break", "subs": ["Edge1"] * 4}]})


# ---------------------------------------------------------------- edit robustness


def test_edit_robustness_named_beats_heuristic_on_count_edits():
    rec = chamfered_p03(3, {"curve": "circle", "location": "top", "boundary": "inner", "expected_count": 6})
    r = robustness(rec)
    assert r["feasible"] > 0 and r["named_ok"] == r["feasible"]
    assert r["heuristic_ok"] < r["named_ok"]
    assert {s["ref"] for s in r["selections"]} >= {"base_solid.top&grid.wall"}
