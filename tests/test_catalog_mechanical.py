"""Pipes, ASME B16.5 flanges, OpenBuilds motion parts, sprockets and worm drives (bd_warehouse)."""

import math

import build123d as bd
import pytest

from shilpa.catalog import resolve
from shilpa.catalog.mechanical import FLANGES, flange_sizes
from shilpa.catalog.preview import browse
from shilpa.contracts.assembly import contracts_compatible
from shilpa.contracts.errors import ErrorCode, ShilpaError


def overlap(a, b) -> float:
    x = a.intersect(b)
    return sum(s.volume for s in x.solids()) if x else 0.0


def test_families():
    fams = {g["family"] for g in browse()["generators"]}
    assert {"Pipes and flanges", "OpenBuilds motion", "Chain and worm drives"} <= fams and "Other" not in fams


@pytest.mark.parametrize("gen,cls,has_face", [(g, c, f) for g, c, _, f in FLANGES])
@pytest.mark.parametrize("flange_class", [150, 300])
def test_flange_size_rule_matches_bd_warehouse(gen, cls, has_face, flange_class):
    sizes = flange_sizes(gen, flange_class)
    make = (lambda n: cls(n, flange_class, "Raised")) if has_face else (lambda n: cls(n, flange_class))
    make(sizes[0]), make(sizes[-1])  # both ends of the advertised range build
    from shilpa.catalog.mechanical import NPS

    for outside in [n for n in (NPS[NPS.index(sizes[0]) - 1] if NPS.index(sizes[0]) else None,
                                NPS[NPS.index(sizes[-1]) + 1] if sizes[-1] != NPS[-1] else None) if n]:
        with pytest.raises(Exception):
            make(outside)


def test_flange_pair_contract_and_bolt_pattern():
    a = resolve("flange.weld_neck", {"nps": "4", "flange_class": 150})
    b = resolve("flange.blind", {"nps": "4", "flange_class": 150})
    c = resolve("flange.blind", {"nps": "4", "flange_class": 300})
    ga, gb, gc = (x.ports["gasket_face"].contract for x in (a, b, c))
    assert contracts_compatible(ga, gb) == []
    assert any(k.startswith(("flange_class", "bolt_circle")) for k in contracts_compatible(ga, gc))
    assert a.meta["bolt_count"] == 8 and a.meta["bolt_circle"] == pytest.approx(190.5)  # B16.5 NPS 4 class 150
    assert a.solid.bounding_box().min.Z == pytest.approx(0, abs=1e-6)
    with pytest.raises(ShilpaError) as e:
        resolve("flange.weld_neck", {"nps": "14"})
    assert e.value.code == ErrorCode.INVALID_PARAMETER and "NPS 1 to 12" in e.value.info.message


def test_pipe_dimensions_and_fit_through_a_slip_on_flange():
    p = resolve("pipe.straight", {"nps": "2", "material": "steel", "identifier": "40", "length": 300})
    assert p.meta["od"] == pytest.approx(60.325, abs=0.01) and p.meta["wall"] == pytest.approx(3.912, abs=0.01)
    bb = p.solid.bounding_box()
    assert (bb.size.X, bb.size.Z) == pytest.approx((60.325, 300), abs=0.01)
    f = resolve("flange.slip_on", {"nps": "2"})
    assert f.ports["bore_axis"].contract["bore_d"] > p.meta["od"]
    assert overlap(p.solid.moved(bd.Location((0, 0, -100))), f.solid) < 0.01
    with pytest.raises(ShilpaError) as e:
        resolve("pipe.straight", {"nps": "2", "material": "copper", "identifier": "40"})
    assert "schedules for that size" in e.value.info.message
    assert resolve("pipe.straight", {"nps": "1/2", "material": "copper", "identifier": "K"}).meta["mass_g"] > 0


def test_sprocket_pitch_diameter_and_bore():
    s = resolve("drive.sprocket", {"chain": "40", "teeth": 20})
    assert s.meta["pitch_d"] == pytest.approx(12.7 / math.sin(math.pi / 20), abs=1e-3)
    assert s.ports["bore_axis"].contract["bore_d"] == s.meta["bore_d"]
    a, b = resolve("drive.sprocket", {"chain": "40", "teeth": 15}), resolve("drive.sprocket", {"chain": "50"})
    assert contracts_compatible(s.ports["mesh"].contract, a.ports["mesh"].contract) == []
    assert contracts_compatible(s.ports["mesh"].contract, b.ports["mesh"].contract)
    with pytest.raises(ShilpaError):
        resolve("drive.sprocket", {"teeth": 9, "bore_d": 40})


def test_worm_and_wheel_mesh_data():
    worm = resolve("drive.worm", {"module": 2, "diametral_quotient": 10})
    wheel = resolve("drive.worm_wheel", {"module": 2, "teeth": 30, "diametral_quotient": 10})
    assert wheel.meta["centre_distance"] == pytest.approx(2 * (10 + 30) / 2) and wheel.meta["ratio"] == 30
    assert contracts_compatible(worm.ports["mesh"].contract, wheel.ports["mesh"].contract) == []
    lefty = resolve("drive.worm_wheel", {"module": 2, "teeth": 30, "hand": "left"})
    assert contracts_compatible(worm.ports["mesh"].contract, lefty.ports["mesh"].contract)


@pytest.mark.parametrize("motor,shaft,frame", [("Nema17", 5.0, 42.3), ("Nema23", 6.35, 56.4)])
def test_stepper(motor, shaft, frame):
    m = resolve("openbuilds.stepper_motor", {"motor_type": motor})
    assert m.ports["shaft_axis"].contract["shaft_d"] == shaft and m.meta["frame_nominal"] == frame
    assert len(m.solid.solids()) == 1 and m.ports["mount_face"].z == (0.0, 0.0, 1.0)


def test_c_beam_and_lead_screw_lengths():
    c = resolve("openbuilds.c_beam_rail", {"length": 750})
    assert c.solid.bounding_box().size.Z == pytest.approx(750, abs=1e-6)
    s = resolve("openbuilds.lead_screw", {"length": 400})
    assert s.solid.bounding_box().size.Z == pytest.approx(400, abs=1e-6) and s.meta["thread"] == "Tr8x8"
