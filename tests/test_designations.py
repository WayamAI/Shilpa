"""Typed part names -> catalog parts (rule-based), and the standards data tables with their sources."""

import pytest

from shilpa import standards
from shilpa.catalog import resolve
from shilpa.catalog.designations import lookup


@pytest.mark.parametrize("text,gen,params", [
    ("M6x20 socket head", "screw.socket_head", {"standard": "iso4762", "size": "M6-1", "length": 20.0}),
    ("m8 x 25 SHCS", "screw.socket_head", {"size": "M8-1.25", "length": 25.0}),
    ("DIN 912 M10x40", "screw.socket_head", {"standard": "iso4762", "size": "M10-1.5"}),
    ("DIN 7991 M4x12", "screw.countersunk", {"standard": "iso10642", "size": "M4-0.7", "length": 12.0}),
    ("M8x30 hex bolt", "screw.hex_head", {"standard": "iso4017", "size": "M8-1.25"}),
    ("DIN 931 M12 x 80", "screw.hex_head", {"standard": "din931", "size": "M12-1.75", "length": 80.0}),
    ("M4x6 grub screw", "screw.set", {"standard": "iso4026", "size": "M4-0.7"}),
    ('1/4-20 x 1.5" socket head cap screw', "screw.socket_head", {"standard": "asme_b18.3", "size": "1/4-20",
                                                                  "length": 38.1}),
    ("#10-24 x 1.25 in pan head", "screw.pan_head", {"standard": "asme_b_18.6.3", "size": "#10-24"}),
    ("M6 nut", "nut.hex", {"standard": "iso4032", "size": "M6-1"}),
    ("DIN 934 M8", "nut.hex", {"standard": "iso4032", "size": "M8-1.25"}),
    ("M6 flange nut", "nut.hex_flange", {"size": "M6-1"}),
    ("M5 heat set insert", "nut.heat_set", {}),
    ("DIN 125 M10", "washer.plain", {"standard": "iso7089", "size": "M10"}),
    ("M6 fender washer", "washer.plain", {"standard": "iso7093", "size": "M6"}),
    ("6204-2RS", "bearing.deep_groove", {"designation": "6204", "seal": "2RS"}),
    ("608ZZ", "bearing.deep_groove", {"designation": "608", "seal": "2Z"}),
    ("7202", "bearing.angular_contact", {"designation": "7202 BECBP"}),
    ("NJ 202", "bearing.cylindrical_roller", {"designation": "NJ 202 ECP"}),
    ("30302", "bearing.tapered_roller", {"designation": "30302 J2"}),
    ("O-ring 210", "seal.o_ring", {"size": "210"}),
    ("o-ring 18.64 x 3.53", "seal.o_ring", {"size": "210"}),
    ("DIN 471 20", "ring.external", {"size": "20"}),
    ("25 mm internal circlip", "ring.internal", {"size": "25"}),
    ("key 6x6x32", "key.parallel", {"length": 32.0, "form": "A"}),
    ("spur gear m2 z20", "gear.spur", {"module": 2.0, "teeth": 20}),
    ("helical gear module 1.5 30 teeth", "gear.helical", {"module": 1.5, "teeth": 30}),
    ("2040 x 500", "vslot.rail", {"profile": "2040", "length": 500.0}),
    ("c-beam 1000 mm", "openbuilds.c_beam_rail", {"length": 1000.0}),
    ("2 in sch 40 pipe x 1000", "pipe.straight", {"nps": "2", "identifier": "40", "material": "steel", "length": 1000.0}),
    ('1/2" type K copper tube', "pipe.straight", {"nps": "1/2", "identifier": "K", "material": "copper"}),
    ("NPS 4 class 300 weld neck flange", "flange.weld_neck", {"nps": "4", "flange_class": 300}),
    ('4" 150# blind flange', "flange.blind", {"nps": "4", "flange_class": 150}),
    ("#40 sprocket 20T", "drive.sprocket", {"chain": "40", "teeth": 20}),
    ("worm wheel m2 z30", "drive.worm_wheel", {"module": 2.0, "teeth": 30}),
    ("worm m1.5 2 start", "drive.worm", {"module": 1.5, "starts": 2}),
    ("NEMA 17", "openbuilds.stepper_motor", {"motor_type": "Nema17"}),
    ("Tr8 lead screw 400 mm", "openbuilds.lead_screw", {"length": 400.0}),
    ("xl gantry plate", "openbuilds.cbeam_gantry_plate_xl", {}),
    ("8 mm lock collar", "openbuilds.lock_collar", {"inside_diameter": "8mm"}),
    ("t-nut m5", "vslot.tnut", {"thread": "M5"}),
])
def test_lookup(text, gen, params):
    hits = lookup(text)
    assert hits, f"no match for {text!r}"
    top = hits[0]
    assert top["generator"] == gen
    for k, v in params.items():
        assert top["params"][k] == v, (k, top["params"])
    part = resolve(top["generator"], top["params"])  # every match builds
    assert part.solid.is_valid


@pytest.mark.parametrize("text", ["M6x21 socket head", "bracket with 4 holes", "1/4-20 x 1\" socket head cap screw",
                                  "", "hello", "NPS 14 weld neck flange"])
def test_no_match_for_non_standard_or_unrelated(text):
    assert lookup(text) == []


def test_t_nut_is_not_a_hex_nut():
    assert [h["generator"] for h in lookup("t-nut m5")] == ["vslot.tnut"]


# ---------------------------------------------------------------- standards tables


def test_every_table_has_its_source():
    csvs = sorted(p.name for p in standards.DATA.glob("*.csv"))
    assert csvs and set(csvs) <= set(standards.sources())
    for name in csvs:
        meta = standards.source(name)
        assert {"title", "standards", "basis", "source", "licence", "units"} <= set(meta), name
        assert standards.table(name), name


def test_tables_keep_identifiers_as_text():
    rows = standards.by("deep_groove_ball_bearings.csv", "designation")
    assert "608" in rows and rows["6204"]["D"] == 47 and isinstance(rows["6204"]["designation"], str)
    holes = standards.by("iso_metric_holes.csv", "size")
    assert holes["M18"]["csk_d"] is None and holes["M6"]["clearance_medium"] == 6.6


def test_modules_read_the_tables():
    from shilpa.catalog.bearings import DEEP_GROOVE
    from shilpa.catalog.fasteners import CLEARANCE, LENGTH_RANGE, PITCH
    from shilpa.contracts.iso_holes import TABLE

    assert DEEP_GROOVE["6204"] == (20, 47, 14, 1.0, 106, 13.5)
    assert PITCH["M8"] == 1.25 and CLEARANCE["M6"] == (6.4, 6.6, 7.0) and LENGTH_RANGE["M5"] == (8, 50)
    assert TABLE["M10"].thread == "M10x1.5" and TABLE["M10"].clearance["coarse"] == 12.0
