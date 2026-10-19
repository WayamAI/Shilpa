"""Structural sections: dimensions from the EN tables, section properties computed from the drawn profile."""

import math

import pytest

from shilpa.assembly.build import build_assembly
from shilpa.catalog import resolve
from shilpa.catalog.preview import browse


def test_family():
    assert "Structural sections" in {g["family"] for g in browse()["generators"]}


# Published values (area cm2, I about the strong axis cm4, I about the weak axis cm4), EN 10365 / EN 10219 tables.
@pytest.mark.parametrize("gen,des,area,i_strong,i_weak,tol", [
    ("section.i_beam", "IPE 200", 28.5, 1943, 142, 0.005),
    ("section.i_beam", "IPE 400", 84.5, 23130, 1318, 0.005),
    ("section.i_beam", "HEA 300", 112.5, 18260, 6310, 0.005),
    ("section.i_beam", "HEB 200", 78.1, 5696, 2003, 0.005),
    ("section.round_tube", "CHS 114.3x5", 17.2, 257, 257, 0.005),
    ("section.angle", "L 50x5", 4.8, 11.0, 11.0, 0.03),  # toe radii not modelled
    ("section.channel", "UPN 200", 32.2, 1910, 148, 0.05),  # toe radius not modelled
])
def test_section_properties_match_the_tables(gen, des, area, i_strong, i_weak, tol):
    m = resolve(gen, {"designation": des, "length": 500}).meta
    assert m["area_cm2"] == pytest.approx(area, rel=tol)
    assert m["Ixx_cm4"] == pytest.approx(i_strong, rel=tol)
    assert m["Iyy_cm4"] == pytest.approx(i_weak, rel=tol)


@pytest.mark.parametrize("gen,des,h,b,t", [("section.square_tube", "SHS 100x100x5", 100, 100, 5),
                                          ("section.rect_tube", "RHS 100x50x4", 100, 50, 4),
                                          ("section.square_tube", "SHS 200x200x10", 200, 200, 10)])
def test_hollow_section_area_is_the_en10219_formula(gen, des, h, b, t):
    ro = 2 * t if t <= 6 else 2.5 * t if t <= 10 else 3 * t
    area = 2 * t * (h + b - 2 * t) - (4 - math.pi) * (ro ** 2 - (ro - t) ** 2)
    assert resolve(gen, {"designation": des}).meta["area_cm2"] == pytest.approx(area / 100, rel=1e-4)


def test_mass_per_metre_and_length():
    p = resolve("section.i_beam", {"designation": "IPE 200", "length": 2500})
    assert p.meta["mass_kg_per_m"] == pytest.approx(22.4, abs=0.1)
    assert p.solid.bounding_box().size.Z == pytest.approx(2500, abs=1e-6)
    assert p.meta["mass_g"] == pytest.approx(22.36 * 2.5 * 1000, rel=0.01)
    assert resolve("section.flat_bar", {"width": 40, "thickness": 5}).meta["mass_kg_per_m"] == pytest.approx(1.57,
                                                                                                           abs=0.01)


def test_beam_on_a_column_from_their_ports():
    """An IPE 300 beam resting on an HEB 200 column, 100 mm in from the beam end: placed by the section ports."""
    from shilpa.validators.assembly import validate_assembly

    spec = {"instances": [
        {"id": "column", "source": "catalog", "grounded": True,
         "ref": {"generator": "section.i_beam", "params": {"designation": "HEB 200", "length": 3000}}},
        {"id": "beam", "source": "catalog",
         "ref": {"generator": "section.i_beam", "params": {"designation": "IPE 300", "length": 4000}}},
    ], "mates": [
        # bottom_flange sits at the beam's mid-length; shift it 1900 mm along the column top's x so the column
        # stands 100 mm in from the beam's end.
        {"a": "column.end_b", "b": "beam.bottom_flange", "type": "fixed", "xy": [1900, 0], "intent": "welded"},
    ], "dof": 0}
    b = build_assembly(spec)
    assert b.ok, b.issues
    r = validate_assembly(b)
    assert r.passed, r.failed  # touching (contact check), no interference
    beam = b.placed["beam"].bounding_box()
    assert beam.min.Z == pytest.approx(3000, abs=1e-6) and beam.size.X == pytest.approx(4000, abs=1e-6)
    assert beam.min.X == pytest.approx(-100, abs=1e-6)  # the column (centred on x = 0) is 100 mm in from the end
