"""Assembly spec, placement, checks and export (roadmap stage S3)."""

import copy
import csv
import json

import build123d as bd
import numpy as np
import pytest
from pydantic import ValidationError

from evals.golden_assemblies import GOLDEN, box, case, inst, outcome_errors, port
from shilpa.adapters import freecad_adapter
from shilpa.assembly import build as asm_build
from shilpa.assembly.build import build_assembly, mate_matrix, port_matrix, register_source
from shilpa.assembly.export import export_all, export_fcstd, export_step, write_bom
from shilpa.contracts.assembly import AssemblySpec, Mate, check_spec, contracts_compatible
from shilpa.contracts.ports import BuiltPart, Port
from shilpa.validators.assembly import validate_assembly

UP, DOWN = (0, 0, 1), (0, 0, -1)


def codes(spec) -> list[str]:
    return sorted(i.code for i in check_spec(AssemblySpec.model_validate(spec)))


def two_blocks(**mate):
    return {"instances": [inst("a", box(20, 20, 10), [port("top", (0, 0, 10), UP, standard="M6", diameter=6)], grounded=True),
                          inst("b", box(10, 10, 10), [port("foot", (0, 0, 0), DOWN, standard="m6 ", diameter=6.0)])],
            "mates": [{"a": "a.top", "b": "b.foot", "type": "fixed", **mate}]}


# ---------------------------------------------------------------- golden assemblies


@pytest.mark.parametrize("name", list(GOLDEN))
def test_golden_assembly(name):
    build = build_assembly(case(name))
    report = validate_assembly(build)
    assert not outcome_errors(name, report), (outcome_errors(name, report), [(c.name, c.actual, c.note) for c in report.checks])
    assert sorted({i.code for i in build.issues}) == sorted(GOLDEN[name]["issues"])
    assert report.passed == (not GOLDEN[name]["fail"])


def test_golden_numbers_match_closed_form():
    _, r = GOLDEN_RUN("press_fit_dowel")
    vol = r.check("interference[dowel+plate]").actual
    assert vol == pytest.approx(np.pi / 4 * (6.02**2 - 6**2) * 8, rel=1e-4)
    _, r = GOLDEN_RUN("interfering")
    assert r.check("interference[block+plate]").actual == pytest.approx(800, rel=1e-6)
    _, r = GOLDEN_RUN("hovering")
    assert r.check("contact[plate.top~block.foot]").actual == pytest.approx(0.5, abs=1e-6)
    b, r = GOLDEN_RUN("shaft_bearings")
    assert r.check("clearance[block1+shaft]").actual == pytest.approx(0.1, abs=1e-6)
    assert b.placed["shaft"].bounding_box().min.Y == pytest.approx(-80)
    _, r = GOLDEN_RUN("lid_hits_wall")
    assert r.check("sweep[hinge]").actual[0]["value"] == 100 and r.check("sweep[hinge]").actual[0]["pair"] == "lid+wall"


def GOLDEN_RUN(name):
    b = build_assembly(case(name))
    return b, validate_assembly(b)


def test_dof_and_clearance_mismatch_fail():
    spec = case("hinge")
    spec["dof"] = 0
    spec["clearances"] = [{"a": "lid", "b": "pin", "min": 2.5}]
    r = validate_assembly(build_assembly(spec))
    assert set(r.failed) == {"dof", "clearance[lid+pin]"}
    assert r.dof == {"computed": 1, "intended": 0, "by_mate": {"base.pin_seat~pin.seat": 0, "hinge": 1}}


def test_bom_quantity_mismatch():
    spec = case("standoff_stack")
    spec["bom"] = {"plate": 2, "standoff": 3}
    r = validate_assembly(build_assembly(spec))
    assert r.failed == ["bom_quantities"]
    assert {line["part_number"]: line["quantity"] for line in r.bom} == {"plate": 2, "standoff": 4}


# ---------------------------------------------------------------- static validation


def test_contract_agreement_tolerates_case_and_int_float():
    assert codes(two_blocks()) == []
    assert contracts_compatible({"standard": "BSA", "shell_width": 68}, {"standard": "bsa", "shell_width": 68.0}) == []
    assert contracts_compatible({"gender": "male"}, {"gender": "male"}) == ["gender: both 'male'"]
    assert contracts_compatible({"gender": "male", "x": 1}, {"gender": "female", "y": 2}) == []


def test_contract_mismatch_reported():
    spec = two_blocks()
    spec["instances"][1]["ref"]["ports"][0]["contract"]["diameter"] = 8
    issues = check_spec(AssemblySpec.model_validate(spec))
    assert [i.code for i in issues] == ["port_contract_mismatch"] and "diameter: 6 vs 8" in issues[0].message


def test_unknown_instance_and_port():
    spec = two_blocks()
    spec["mates"].append({"a": "a.side", "b": "ghost.foot"})
    assert codes(spec) == ["unknown_instance", "unknown_port"]


def test_grounds():
    spec = two_blocks()
    spec["instances"][1]["grounded"] = True
    assert codes(spec) == ["multiple_grounds"]
    spec["instances"][0]["grounded"] = spec["instances"][1]["grounded"] = False
    assert codes(spec) == ["no_ground"]


def test_cycle_reported_with_its_loop():
    spec = case("standoff_stack")
    spec["mates"].append({"a": "so2.top", "b": "top.b2", "type": "fixed"})
    issues = [i for i in check_spec(AssemblySpec.model_validate(spec)) if i.code == "cycle"]
    assert len(issues) == 1
    assert issues[0].where[0] == "so2.top~top.b2"
    assert issues[0].where[1:] == ["so2", "base", "so1", "top"]
    # Placement still follows the spanning tree; the closing mate is redundant here, so geometry is identical.
    b = build_assembly(spec)
    assert not b.ok and "so2" in b.matrices and validate_assembly(b).failed == ["spec_valid"]


def test_schema_rejections():
    with pytest.raises(ValidationError, match="both ends on one instance"):
        Mate(a="x.p", b="x.q")
    with pytest.raises(ValidationError, match="limits only apply"):
        Mate(a="x.p", b="y.q", type="fixed", limits=(0, 1))
    with pytest.raises(ValidationError, match="pitch"):
        Mate(a="x.p", b="y.q", type="screw")
    with pytest.raises(ValidationError, match="loops"):
        AssemblySpec.model_validate({"instances": [inst("a", copy_of="b"), inst("b", copy_of="a")]})
    with pytest.raises(ValidationError, match="needs a ref"):
        AssemblySpec.model_validate({"instances": [inst("a")]})
    with pytest.raises(ValidationError, match="ref.generator"):
        AssemblySpec.model_validate({"instances": [inst("a", box(1, 1, 1), source="catalog")]})
    with pytest.raises(ValidationError, match="duplicate instance"):
        AssemblySpec.model_validate({"instances": [inst("a", box(1, 1, 1)), inst("a", box(1, 1, 1))]})


# ---------------------------------------------------------------- placement convention


def test_opposed_fixed_with_offset_and_angle():
    b = build_assembly(two_blocks(offset=2, angle=90, xy=(3, 0)))
    T = b.matrices["b"]
    # b's foot frame: origin at a's top + 2 mm along a's z, shifted 3 mm along a's x, z flipped, then turned 90 deg.
    assert np.allclose(T[:3, 3], (3, 0, 12))
    assert np.allclose(T[:3, 2], (0, 0, 1))  # the block still stands upright: z(-Z) opposes a's +Z
    assert np.allclose(T[:3, 0], (0, -1, 0)) or np.allclose(T[:3, 0], (0, 1, 0))
    bb = b.placed["b"].bounding_box()
    assert (bb.min.Z, bb.max.Z) == pytest.approx((12, 22))


def test_port_frames_coincide_after_placement():
    b = build_assembly(case("shaft_bearings"))
    for m, _ in b.order:
        A = b.matrices[m.inst_a] @ port_matrix(b.parts[m.inst_a].port(m.port_a)) @ mate_matrix(m)
        B = b.matrices[m.inst_b] @ port_matrix(b.parts[m.inst_b].port(m.port_b))
        assert np.allclose(A, B, atol=1e-9), m.name


def test_reversed_mate_direction_places_identically():
    spec = case("hinge")
    fwd = build_assembly(spec).matrices
    rev = copy.deepcopy(spec)
    for m in rev["mates"]:
        m["a"], m["b"] = m["b"], m["a"]  # the ground is now on the b side of every mate
    # Swapping ends turns M into its inverse, so the same pose needs the inverse joint values.
    for m in rev["mates"]:
        m["angle"] = -m.get("angle", 0)
    back = build_assembly(rev).matrices
    for k in fwd:
        assert np.allclose(fwd[k], back[k], atol=1e-9), k


def test_revolute_pose_and_moving_side():
    b = build_assembly(case("lid_hits_wall"))
    hinge = next(m for m, _ in b.order if m.name == "hinge")
    assert b.moving_side(hinge) == {"lid"}
    T = b.pose({"hinge": {"angle": 90}})
    bb = b.world_solid("lid", T["lid"]).bounding_box()
    assert (bb.min.Y, bb.max.Y, bb.min.Z, bb.max.Z) == pytest.approx((22, 25, 11, 51), abs=1e-6)


def test_mirror_of_flips_geometry_and_ports():
    bracket = box(20, 10, 5, cx=15)  # x in [5, 25]
    spec = {"instances": [inst("base", box(100, 100, 5), [port("l", (-30, 0, 5), UP), port("r", (30, 0, 5), UP)], grounded=True),
                          inst("left", bracket, [port("foot", (15, 0, 0), DOWN)], part_number="bracket_l"),
                          inst("right", mirror_of={"instance": "left", "plane": "YZ"})],
            "mates": [{"a": "base.l", "b": "left.foot"}, {"a": "base.r", "b": "right.foot"}]}
    b = build_assembly(spec)
    assert b.parts["right"].port("foot").origin == (-15, 0, 0)
    assert b.parts["right"].solid.bounding_box().max.X == pytest.approx(-5)
    r = validate_assembly(b)
    assert r.passed, r.failed
    assert sorted(line["part_number"] for line in r.bom) == ["base", "bracket_l", "right"]


# ---------------------------------------------------------------- part sources


def test_registered_generator_source(monkeypatch):
    monkeypatch.setattr(asm_build, "_SOURCES", dict(asm_build._SOURCES))

    def washer(ref):
        p = ref.params
        solid = bd.Cylinder(p["od"] / 2, p["t"], align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)) - \
            bd.Cylinder(p["id"] / 2, p["t"], align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))
        ports = {"bottom": Port(name="bottom", z=DOWN, contract={"diameter": p["id"]}),
                 "top": Port(name="top", origin=(0, 0, p["t"]), contract={"diameter": p["id"]})}
        return BuiltPart(f"washer_{p['id']}", solid, ports, "catalog", {"standard": "ISO 7089"})

    register_source("catalog", washer)
    with pytest.raises(ValueError, match="already registered"):
        register_source("catalog", washer)
    spec = {"instances": [inst("plate", box(30, 30, 5), [port("hole", (0, 0, 5), UP, diameter=6.4)], grounded=True),
                          {"id": "w", "source": "catalog", "ref": {"generator": "iso7089", "params": {"od": 12, "id": 6.4, "t": 1.6}}}],
            "mates": [{"a": "plate.hole", "b": "w.bottom", "intent": "contact"}], "bom": {"plate": 1, "w": 1}}
    b = build_assembly(spec)
    r = validate_assembly(b)
    assert r.passed, r.failed
    assert b.placed["w"].bounding_box().max.Z == pytest.approx(6.6)
    assert next(line for line in r.bom if line["part_number"] == "w")["generator"] == "iso7089"
    # A generator part's mate is checked against the built ports, contract included.
    spec["instances"][0]["ref"]["ports"][0]["contract"]["diameter"] = 8.4
    assert [i.code for i in build_assembly(spec).issues] == ["port_contract_mismatch"]


def test_unregistered_source_and_failed_part_reported():
    spec = {"instances": [inst("plate", box(30, 30, 5), [port("top", (0, 0, 5), UP)], grounded=True),
                          {"id": "x", "source": "weldment", "ref": {"generator": "frame", "ports": [{"name": "foot", "z": [0, 0, -1]}]}},
                          inst("bad", box(30, 30, 5, holes=[{"kind": "center", "d": 40}]), [port("foot", (0, 0, 0), DOWN)])],
            "mates": [{"a": "plate.top", "b": "x.foot"}, {"a": "plate.top", "b": "bad.foot"}]}
    b = build_assembly(spec)
    assert set(b.errors) == {"x", "bad"} and b.errors["x"].code == "unsupported_operation"
    r = validate_assembly(b)
    assert {"part_built[x]", "part_built[bad]", "bom_built", "all_placed"} <= set(r.failed)


# ---------------------------------------------------------------- export


def test_step_keeps_labels_and_colours(tmp_path):
    b = build_assembly(case("standoff_stack"))
    p = export_step(b, tmp_path / "a.step")
    # Copies share one STEP product (one geometry, several occurrences); occurrences carry the instance ids.
    text = p.read_text(errors="ignore")
    for iid in ("base", "so1", "so2", "so3", "so4", "top"):
        assert f"','{iid}','" in text
    assert text.count("PRODUCT(") == 3  # assembly, plate, standoff
    back = bd.import_step(str(p))
    assert len(back.children) == 6 and back.volume == pytest.approx(b.compound.volume, rel=1e-6)
    colours = sorted(str(c.color).split("'")[1] for c in back.children)
    assert colours == ["GOLD"] * 4 + ["LIGHTSTEELBLUE", "STEELBLUE"]


def test_bom_files(tmp_path):
    b = build_assembly(case("shaft_bearings"))
    cs, js = write_bom(b, tmp_path)
    rows = list(csv.DictReader(cs.open(encoding="utf-8")))
    assert [(r["part_number"], r["quantity"], r["instances"]) for r in rows] == [
        ("base", "1", "base"), ("block", "2", "block1 block2"), ("shaft", "1", "shaft")]
    assert json.loads(js.read_text())["lines"][1]["quantity"] == 2
    paths = export_all(b, tmp_path / "all")
    assert {"STEP", "BOM_CSV", "BOM_JSON", "PLACEMENTS"} <= set(paths)
    table = json.loads(paths["PLACEMENTS"].read_text())
    assert table["block2"][2][3] == pytest.approx(26)  # block local y (+20 up) maps to world z, foot at z=6


@pytest.mark.skipif(not freecad_adapter.available(), reason="FreeCAD not installed")
@pytest.mark.parametrize("name", ["standoff_stack", "hinge", "slider_rail"])
def test_freecad_assembly_joints(tmp_path, name):
    b = build_assembly(case(name))
    res = export_fcstd(b, tmp_path)
    assert res["ok"], res.get("error")
    assert res["joints"] == "all" and res["solve"] == 0
    assert res["joints_satisfied"], res["joint_residuals"]  # parts were scrambled first, so the joints did this
    if name == "standoff_stack":
        assert res["placements_match"]  # fully rigid: the solver must land exactly on Shilpa's placement
    assert (tmp_path / "assembly.FCStd").exists()
