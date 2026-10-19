"""Motion parts from published dimensions: pulleys and belts, profile rails, ball screws, bushings,
pillow blocks, collars, dowels and springs."""

import math

import build123d as bd
import pytest

from shilpa.assembly.build import build_assembly
from shilpa.catalog import resolve
from shilpa.catalog.preview import browse
from shilpa.contracts.assembly import contracts_compatible
from shilpa.contracts.errors import ErrorCode, ShilpaError


def overlap(a, b) -> float:
    x = a.intersect(b)
    return sum(s.volume for s in x.solids()) if x else 0.0


def test_families():
    fams = {g["family"] for g in browse()["generators"]}
    assert {"Belts and pulleys", "Linear motion", "Collars, pins and springs"} <= fams and "Other" not in fams


@pytest.mark.parametrize("profile,teeth,pitch,pld", [("GT2", 20, 2, 0.254), ("HTD3M", 24, 3, 0.381),
                                                     ("HTD5M", 30, 5, 0.5715)])
def test_pulley_outside_diameter(profile, teeth, pitch, pld):
    p = resolve("pulley.timing", {"profile": profile, "teeth": teeth})
    assert p.meta["od"] == pytest.approx(teeth * pitch / math.pi - 2 * pld, abs=1e-3)
    assert p.ports["mesh"].contract["belt"] == profile and p.ports["mesh"].contract["pitch"] == pitch
    with pytest.raises(ShilpaError):
        resolve("pulley.timing", {"profile": profile, "teeth": 10, "bore_d": 30})


def test_belt_length_is_whole_teeth():
    b = resolve("belt.timing", {"profile": "GT2", "length": 401})
    assert b.meta["teeth"] == 200 and b.meta["length"] == 400
    assert b.solid.bounding_box().size.X == pytest.approx(400, abs=1e-6)


def test_carriage_slides_on_its_rail():
    spec = {"instances": [
        {"id": "rail", "source": "catalog", "ref": {"generator": "linear.guide_rail",
                                                    "params": {"size": "MGN12", "length": 300}}, "grounded": True},
        {"id": "block", "source": "catalog", "ref": {"generator": "linear.guide_carriage", "params": {"size": "MGN12"}}},
    ], "mates": [{"id": "travel", "a": "rail.track", "b": "block.track", "type": "slider", "align": "aligned",
                  "offset": 150, "limits": [30, 270]}], "dof": 1}
    from shilpa.validators.assembly import validate_assembly

    b = build_assembly(spec)
    assert b.ok, b.issues
    r = validate_assembly(b)
    assert r.passed, r.failed
    rail, block = b.placed["rail"], b.placed["block"]
    assert overlap(rail, block) < 0.01 and rail.distance_to(block) < 1e-6  # seated: touching, not overlapping
    assert block.bounding_box().max.Z == pytest.approx(13, abs=1e-6)  # MGN12 assembly height


def test_rail_and_carriage_of_different_sizes_do_not_mate():
    a = resolve("linear.guide_rail", {"size": "MGN12"}).ports["track"].contract
    b = resolve("linear.guide_carriage", {"size": "MGN9"}).ports["track"].contract
    assert contracts_compatible(a, b)
    with pytest.raises(ShilpaError) as e:
        resolve("linear.guide_carriage", {"size": "HGR15", "block": "H"})
    assert e.value.code == ErrorCode.INVALID_PARAMETER


def test_ball_nut_on_its_screw():
    screw = resolve("linear.ball_screw", {"designation": "SFU1605", "length": 300})
    nut = resolve("linear.ball_nut", {"designation": "SFU1605"})
    assert contracts_compatible(screw.ports["screw_axis"].contract, nut.ports["screw_axis"].contract) == []
    other = resolve("linear.ball_nut", {"designation": "SFU2005"})
    assert contracts_compatible(screw.ports["screw_axis"].contract, other.ports["screw_axis"].contract)
    assert overlap(screw.solid, nut.solid.moved(bd.Location((0, 0, 100)))) < 0.01
    assert nut.meta["bolt_pcd"] == 38 and nut.ports["flange_face"].contract["bolt_count"] == 6


def test_bushing_runs_on_its_shaft():
    shaft = resolve("linear.shaft", {"diameter": 8, "length": 200})
    bush = resolve("linear.bushing", {"designation": "LM8UU"})
    assert contracts_compatible(shaft.ports["shaft_axis"].contract, bush.ports["bore_axis"].contract) == []
    assert overlap(shaft.solid, bush.solid.moved(bd.Location((0, 0, 50)))) < 0.01
    assert (bush.meta["d"], bush.meta["D"], bush.meta["L"]) == (8, 15, 24)
    flanged = resolve("linear.bushing", {"designation": "LMF12UU"})
    assert flanged.solid.bounding_box().size.X == pytest.approx(42, abs=1e-6)


def test_pillow_block_centre_height():
    pb = resolve("bearing.pillow_block", {"designation": "UCP204"})
    bb = pb.solid.bounding_box()
    assert (bb.size.X, bb.size.Y, bb.size.Z) == pytest.approx((127, 38, 65), abs=1e-6)
    assert pb.ports["bore_axis"].origin == (0.0, 0.0, 33.3) and pb.ports["bore_axis"].contract["bore_d"] == 20


def test_collar_dowel_and_spring():
    c = resolve("shaft.collar", {"d": 20})
    assert (c.meta["D"], c.meta["b"], c.meta["set_screw"]) == (32, 14, "M8")
    d = resolve("pin.dowel", {"d": 6, "length": 20})
    assert d.solid.bounding_box().size.Z == pytest.approx(20, abs=1e-6) and d.meta["tolerance"] == "m6"
    with pytest.raises(ShilpaError):
        resolve("pin.dowel", {"d": 3, "length": 50})
    s = resolve("spring.compression", {"wire_d": 1, "mean_d": 10, "free_length": 30, "coils": 8})
    assert s.meta["rate_N_per_mm"] == pytest.approx(79300 * 1 / (8 * 1000 * 6), rel=1e-3)
    bb = s.solid.bounding_box()
    assert (bb.min.Z, bb.max.Z) == pytest.approx((0, 30), abs=1e-6) and {"end_a", "end_b"} <= set(s.ports)
    with pytest.raises(ShilpaError):
        resolve("spring.compression", {"wire_d": 3, "mean_d": 6})
