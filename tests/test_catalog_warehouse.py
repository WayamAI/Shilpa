"""bd_warehouse-backed standard parts: screws, nuts, washers, bearings, O-rings, circlips, keys.

Every generator is also covered by test_catalog (builds with defaults) and test_ports_validator
(every port sits on its geometry); these check the data, the size/length rules and the fits.
"""

import build123d as bd
import pytest

from shilpa.catalog import list_generators, resolve
from shilpa.catalog.preview import browse
from shilpa.catalog.warehouse import nominal_diameter, standard_label, thread_designation
from shilpa.contracts.errors import ErrorCode, ShilpaError

NEW = ("screw.", "nut.", "washer.", "bearing.", "seal.", "ring.", "key.")


def overlap(a, b) -> float:
    x = a.intersect(b)
    return sum(s.volume for s in x.solids()) if x else 0.0


def test_families_and_counts():
    names = [g["name"] for g in list_generators()]
    assert sum(n.startswith(NEW) for n in names) == 33
    fams = {g["family"] for g in browse()["generators"]}
    assert {"Screws", "Nuts", "Washers", "Bearings", "Seals, circlips and keys"} <= fams and "Other" not in fams


@pytest.mark.parametrize("size,d,thread", [("M6-1", 6.0, "M6x1"), ("M1.6-0.35", 1.6, "M1.6x0.35"),
                                           ("1/4-20", 6.35, "1/4-20"), ("#10-24", 4.826, "#10-24"),
                                           ("M5-0.8-H4-D7", 5.0, "M5-0.8-H4-D7")])
def test_size_parsing(size, d, thread):
    assert nominal_diameter(size) == pytest.approx(d, abs=1e-3)
    assert thread_designation(size) == thread


def test_standard_labels():
    assert standard_label("iso7380_1") == "ISO 7380-1" and standard_label("din931") == "DIN 931"
    assert standard_label("asme_b_18.6.3") == "ASME B18.6.3" and standard_label("OpenBuilds") == "OpenBuilds"


def test_screw_lengths_are_the_standards():
    s = resolve("screw.socket_head", {"size": "M8-1.25", "length": 25})
    assert s.meta["designation"] == "ISO 4762 M8-1.25 x 25" and 25.0 in s.meta["nominal_lengths"]
    bb = s.solid.bounding_box()
    assert bb.min.Z == pytest.approx(-25, abs=1e-6) and s.ports["thread_axis"].contract["nominal_d"] == 8.0
    with pytest.raises(ShilpaError) as e:
        resolve("screw.socket_head", {"size": "M8-1.25", "length": 26})
    assert e.value.code == ErrorCode.INVALID_PARAMETER and "25, 30" in e.value.info.message


def test_size_must_belong_to_the_standard():
    with pytest.raises(ShilpaError) as e:
        resolve("screw.socket_head", {"standard": "iso4762", "size": "1/4-20"})
    assert e.value.code == ErrorCode.INVALID_PARAMETER and "M6-1" in e.value.info.message
    imperial = resolve("screw.socket_head", {"standard": "asme_b18.3", "size": "1/4-20"})
    assert imperial.ports["thread_axis"].contract["nominal_d"] == pytest.approx(6.35)


def test_countersunk_head_is_flush_at_zero():
    s = resolve("screw.countersunk", {"size": "M5-0.8", "length": 20})
    bb = s.solid.bounding_box()
    assert bb.max.Z == pytest.approx(0, abs=1e-6) and "flush_top" in s.ports and "head_seat" not in s.ports


def test_screw_threads_into_a_hex_nut_without_overlap():
    screw = resolve("screw.hex_head", {"size": "M10-1.5", "length": 40})
    nut = resolve("nut.hex", {"size": "M10-1.5"})
    assert screw.ports["thread_axis"].contract["thread"] == nut.ports["thread_axis"].contract["thread"] == "M10x1.5"
    # Nut seated 25 mm down the shank: the nominal shank meets the simple nut's major-diameter bore.
    assert overlap(screw.solid, nut.solid.moved(bd.Location((0, 0, -25)))) < 0.01


def test_iso_sets_agree_on_thread_designations():
    old = resolve("iso4032_hex_nut", {"size": "M6"})
    new = resolve("screw.socket_head", {"size": "M6-1"})
    assert old.ports["thread_axis"].contract["thread"] == new.ports["thread_axis"].contract["thread"]


def test_bearing_data_from_the_table():
    # bd_warehouse's deep-groove table is the miniature range (bore 3-10 mm); 6200 is its largest.
    b = resolve("bearing.deep_groove", {"size": "M10-30-9"})
    assert b.meta["designation"] == "6200"
    assert (b.meta["d"], b.meta["D"], b.meta["B"]) == (10.0, 30.0, 9.0)
    assert b.meta["dynamic_load_kN"] == pytest.approx(5.4) and b.meta["mass_g"] == pytest.approx(31.0)
    assert b.meta["mass_basis"] == "catalog"
    bb = b.solid.bounding_box()
    assert (bb.size.X, bb.size.Z) == pytest.approx((30, 9), abs=1e-6)
    t = resolve("bearing.tapered_roller", {})
    assert t.meta["standard"] == "ISO 355" and t.meta["B"] > 0


def test_o_ring_carries_its_gland():
    o = resolve("seal.o_ring", {"size": "210"})
    assert o.meta["o_ring_id"] == pytest.approx(18.64) and o.meta["cross_section"] == pytest.approx(3.53)
    assert (o.meta["gland_static_axial_width"], o.meta["gland_static_axial_depth"]) == pytest.approx((4.57, 2.64))
    assert o.meta["gland_dynamic_width"] > o.meta["cross_section"] > o.meta["gland_dynamic_depth"]


def test_parallel_key_for_a_20mm_shaft():
    k = resolve("key.parallel", {"shaft_d": 20, "length": 32})
    assert (k.meta["key_b"], k.meta["key_h"]) == (6.0, 6.0)
    assert (k.meta["shaft_depth_t1"], k.meta["hub_depth_t2"]) == pytest.approx((3.5, 2.8))  # DIN 6885 for 17-22 mm
    assert k.solid.bounding_box().size.X == pytest.approx(32, abs=1e-6)


@pytest.mark.parametrize("gen,fits", [("ring.external", "for_shaft"), ("ring.internal", "for_bore")])
def test_circlips(gen, fits):
    r = resolve(gen, {"size": "20"})
    assert r.ports["ring_axis"].contract[fits] == 20.0 and r.meta["thickness"] > 0
