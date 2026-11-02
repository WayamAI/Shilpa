"""Unit normalisation and the plausibility check (spec 3.2)."""

import math

import pytest

from shilpa.compose import units
from shilpa.contracts.composition import Qty


@pytest.mark.parametrize("text, mm, unit, prov", [
    ("10 mm", 10, "mm", "user"), ("10mm", 10, "mm", "user"), ("1.5 cm", 15, "cm", "user"), ("10 m", 10000, "m", "user"),
    ("2 in", 50.8, "in", "user"), ("1 ft", 304.8, "ft", "user"), ("12", 12, "mm", "assumed"), ("3 metres", 3000, "m", "user"),
    ("30 deg", 30, "deg", "user"), ("45°", 45, "deg", "user"), ("0.5 inches", 12.7, "in", "user"), ("-5 mm", -5, "mm", "user"),
])
def test_parse_and_normalise(text, mm, unit, prov):
    q = units.parse(text)
    assert math.isclose(q.mm, mm) and q.unit == unit and q.provenance == prov and q.as_typed == text


def test_radians():
    assert math.isclose(units.parse("1 rad").mm, 57.29577951308232, rel_tol=1e-9)


@pytest.mark.parametrize("text", ["", "ten mm", "10 parsecs", "1e400 mm", "mm", "10 mm 5", "nan mm"])
def test_unreadable(text):
    with pytest.raises(units.UnitError):
        units.parse(text)


def test_mm_is_recomputed_never_trusted():
    q = units.normalise(Qty(value=10, unit="m", mm=10))  # a model claiming 10 m == 10 mm is overruled
    assert q.mm == 10000


def test_echo():
    assert units.echo(units.parse("10 m")) == "10 m → 10 000 mm"
    assert units.echo(units.parse("10 mm")) == "10 mm"
    assert units.echo(units.parse("0.5 rad")).endswith("deg")


def test_ten_metre_typo_is_suspect():
    q = units.parse("10 m")
    found = units.suspect(q, 120)
    assert found is not None and found["ratio"] == pytest.approx(83.3, abs=0.1)
    assert "10 m (10 000 mm)" in found["message"] and "120 mm across" in found["message"]
    labels = [label for label, _ in found["options"]]
    assert labels == ["10 mm", "10 cm", "Keep 10 m"]
    assert [o.mm for _, o in found["options"]] == [10, 100, 10000]
    assert all(o.confirmed and o.provenance == "user" for _, o in found["options"])
    assert "—" not in found["message"] and "–" not in found["message"]


def test_plausible_and_confirmed_values_pass():
    assert units.suspect(units.parse("10 mm"), 120) is None
    assert units.suspect(units.parse("2 m"), 120) is None  # 2000 < 20 x 120
    assert units.suspect(units.parse("10 m").model_copy(update={"confirmed": True}), 120) is None
    assert units.suspect(units.parse("90 deg"), 1) is None  # angles are not lengths
    assert units.suspect(units.parse("10 m"), 0) is None  # an empty scene has no scale yet
