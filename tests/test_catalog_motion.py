"""Gears (py_gearworks) and 20-series V-slot (bd_vslot): dimensions, meshing and fit."""

import math

import build123d as bd
import pytest

from shilpa.assembly.build import build_assembly
from shilpa.catalog import list_generators, resolve
from shilpa.catalog.gears import center_distance, mesh_layout
from shilpa.contracts.errors import ErrorCode, ShilpaError


def overlap(a, b) -> float:
    x = a.intersect(b)
    return sum(s.volume for s in x.solids()) if x else 0.0


def placed(part, layout, rotate=True):
    rot = layout["rotation_deg"] if rotate else 0.0
    return part.solid.moved(bd.Location(layout["offset"]) * bd.Rotation(0, 0, rot))


def test_new_generators_registered():
    names = {g["name"] for g in list_generators()}
    assert {"gear.spur", "gear.helical", "gear.ring", "gear.bevel", "gear.rack",
            "vslot.rail", "vslot.wheel", "vslot.tnut"} <= names


# ---------------------------------------------------------------- gears


@pytest.mark.parametrize("m,z", [(1.0, 24), (2.0, 20), (3.0, 37)])
def test_spur_dimensions(m, z):
    g = resolve("gear.spur", {"module": m, "teeth": z, "face_width": 12})
    bb = g.solid.bounding_box()
    assert g.meta["pitch_d"] == pytest.approx(m * z, abs=1e-6)
    assert g.meta["tip_d"] == pytest.approx(m * (z + 2), abs=0.05)  # standard addendum
    assert bb.max.X == pytest.approx(m * (z + 2) / 2, abs=0.05)  # a tooth tip sits on +X (odd z misses -X)
    assert bb.min.Z == pytest.approx(-6, abs=1e-6) and bb.max.Z == pytest.approx(6, abs=1e-6)
    assert g.ports["bore_axis"].contract["bore_d"] == g.meta["bore_d"]


def test_ring_gear_od_and_internal_contract():
    r = resolve("gear.ring", {"teeth": 60, "module": 2, "rim": 2.5})
    assert r.meta["od"] == pytest.approx(2 * 60 + 2 * 2 * 2.5, abs=0.01)
    assert r.meta["internal"] is True and r.ports["outer"].contract["od"] == r.meta["od"]


def test_bore_must_leave_a_web():
    with pytest.raises(ShilpaError) as e:
        resolve("gear.spur", {"teeth": 12, "module": 1, "bore_d": 9})
    assert e.value.code == ErrorCode.INVALID_PARAMETER


@pytest.mark.parametrize("za,zb,direction", [(20, 30, (1, 0)), (17, 40, (0, 1)), (24, 24, (1, 1))])
def test_spur_pair_meshes_without_overlap(za, zb, direction):
    a = resolve("gear.spur", {"teeth": za})
    b = resolve("gear.spur", {"teeth": zb})
    lay = mesh_layout(a, b, direction)
    assert lay["center_distance"] == pytest.approx(center_distance(2.0, za, zb), abs=1e-6)
    assert overlap(a.solid, placed(b, lay)) < 0.01


def test_wrong_phase_clashes():
    a, b = resolve("gear.spur", {"teeth": 20}), resolve("gear.spur", {"teeth": 30})
    lay = mesh_layout(a, b)
    assert overlap(a.solid, placed(b, lay, rotate=False)) > 50  # mm3: teeth tip-to-tip


def test_spur_inside_ring():
    ring, pinion = resolve("gear.ring", {"teeth": 60}), resolve("gear.spur", {"teeth": 20})
    lay = mesh_layout(ring, pinion)
    assert lay["center_distance"] == pytest.approx(center_distance(2.0, 60, 20, internal=True))
    assert overlap(ring.solid, placed(pinion, lay)) < 0.01


def test_helical_pair_needs_opposite_hands():
    a = resolve("gear.helical", {"teeth": 20, "hand": "right"})
    b = resolve("gear.helical", {"teeth": 30, "hand": "left"})
    lay = mesh_layout(a, b)
    assert lay["center_distance"] == pytest.approx(2.0 * 50 / 2 / math.cos(math.radians(20)), abs=1e-4)
    assert overlap(a.solid, placed(b, lay)) < 0.05
    with pytest.raises(ShilpaError) as e:
        mesh_layout(a, resolve("gear.helical", {"teeth": 30, "hand": "right"}))
    assert e.value.code == ErrorCode.INVALID_PARAMETER


@pytest.mark.parametrize("pa,pb", [({"module": 2}, {"module": 3}), ({"pressure_angle": 20}, {"pressure_angle": 25})])
def test_mismatched_pairs_rejected(pa, pb):
    with pytest.raises(ShilpaError) as e:
        mesh_layout(resolve("gear.spur", pa), resolve("gear.spur", pb))
    assert e.value.code == ErrorCode.INVALID_PARAMETER


def test_bevel_cone_angle_and_back_face():
    g = resolve("gear.bevel", {"teeth": 15, "mate_teeth": 30})
    assert g.meta["pitch_cone_angle"] == pytest.approx(math.degrees(math.atan2(15, 30)), abs=1e-4)
    assert g.solid.bounding_box().min.Z == pytest.approx(0, abs=1e-6)


def test_rack_pitch_and_backing():
    r = resolve("gear.rack", {"teeth": 20, "module": 2, "backing": 8})
    bb = r.solid.bounding_box()
    assert r.meta["linear_pitch"] == pytest.approx(2 * math.pi, abs=1e-4)
    assert bb.min.X == pytest.approx(r.ports["back"].origin[0], abs=1e-6)
    assert abs(bb.min.Y + bb.max.Y) < 1e-6 and abs(bb.min.Z + bb.max.Z) < 1e-6


# ---------------------------------------------------------------- V-slot


@pytest.mark.parametrize("profile,w,h,slots", [("2020", 20, 20, 4), ("2040", 40, 20, 6), ("4040", 40, 40, 8),
                                               ("2080", 80, 20, 10), ("c_beam", 80, 40, 14)])
def test_rail_section(profile, w, h, slots):
    r = resolve("vslot.rail", {"profile": profile, "length": 300})
    bb = r.solid.bounding_box()
    assert (bb.size.X, bb.size.Y, bb.size.Z) == pytest.approx((w, h, 300), abs=1e-6)
    assert abs(bb.min.X + bb.max.X) < 1e-6 and abs(bb.min.Y + bb.max.Y) < 1e-6 and bb.min.Z == pytest.approx(0)
    assert sum(n.startswith("slot_") for n in r.ports) == slots


def test_2020_mass_per_metre():
    # OpenBuilds lists 2020 V-slot at about 0.5 kg/m; the modelled section is within 10 %.
    r = resolve("vslot.rail", {"profile": "2020", "length": 1000})
    assert 450 <= r.meta["mass_g"] <= 550


def test_tnut_seats_in_slot_without_overlap():
    rail = resolve("vslot.rail", {"profile": "2020", "length": 100})
    nut = resolve("vslot.tnut", {"thread": "M5"})
    slot = rail.ports["slot_xp_0"]
    lip = slot.contract["lip_thickness"]
    # Nut +Z along the slot's outward normal, seat one lip thickness inside the rail face.
    loc = bd.Location((slot.origin[0] - lip, slot.origin[1], slot.origin[2]), (0, 90, 0))
    assert overlap(rail.solid, nut.solid.moved(loc)) < 0.01
    # Pushed 0.5 mm further out, the wings run into the lips.
    loc_out = bd.Location((slot.origin[0] - lip + 0.5, slot.origin[1], slot.origin[2]), (0, 90, 0))
    assert overlap(rail.solid, nut.solid.moved(loc_out)) > 1


def test_wheel_takes_625_bearings():
    w = resolve("vslot.wheel", {})
    b625 = 16.0  # 625 bearing outside diameter
    assert w.ports["bore_axis"].contract["bore_d"] == pytest.approx(b625)
    assert w.meta["mass_basis"] == "geometry" and w.meta["mass_g"] > 0


# ---------------------------------------------------------------- in assemblies


def gear_pair(a_params, b_params, layout=None, gen_a="gear.spur", gen_b="gear.spur"):
    if layout is None:
        layout = mesh_layout(resolve(gen_a, a_params), resolve(gen_b, b_params))
    return {"instances": [
        {"id": "g1", "source": "catalog", "ref": {"generator": gen_a, "params": a_params}, "grounded": True},
        {"id": "g2", "source": "catalog", "ref": {"generator": gen_b, "params": b_params}},
    ], "mates": [{"a": "g1.mesh", "b": "g2.mesh", "type": "fixed", "align": "aligned",
                  "xy": list(layout["offset"][:2]), "angle": layout["rotation_deg"]}]}


def test_gear_pair_assembly_meshes():
    from shilpa.validators.assembly import validate_assembly

    b = build_assembly(gear_pair({"teeth": 20}, {"teeth": 30}))
    assert b.ok, b.issues
    r = validate_assembly(b)
    assert r.passed, r.failed


def test_gear_pair_assembly_out_of_phase_clashes():
    from shilpa.validators.assembly import validate_assembly

    lay = {"offset": (50.0, 0.0, 0.0), "rotation_deg": 0.0}
    r = validate_assembly(build_assembly(gear_pair({"teeth": 20}, {"teeth": 30}, lay)))
    assert "interference" in " ".join(r.failed)


@pytest.mark.parametrize("pb,gen_b,why", [({"teeth": 30, "module": 3}, "gear.spur", "module"),
                                          ({"teeth": 30}, "gear.helical", "helix_angle")])
def test_gear_pair_contract_rejects_non_meshing(pb, gen_b, why):
    lay = {"offset": (60.0, 0.0, 0.0), "rotation_deg": 0.0}
    issues = build_assembly(gear_pair({"teeth": 20}, pb, lay, gen_b=gen_b)).issues
    assert [i.code for i in issues] == ["port_contract_mismatch"] and why in issues[0].message


def test_helical_same_hand_rejected_in_assembly():
    lay = {"offset": (60.0, 0.0, 0.0), "rotation_deg": 0.0}
    spec = gear_pair({"teeth": 20}, {"teeth": 30}, lay, gen_a="gear.helical", gen_b="gear.helical")
    issues = build_assembly(spec).issues
    assert [i.code for i in issues] == ["port_contract_mismatch"] and "mesh_hand" in issues[0].message


def test_tnut_in_rail_assembly():
    from shilpa.validators.assembly import validate_assembly

    spec = {"instances": [
        {"id": "rail", "source": "catalog", "ref": {"generator": "vslot.rail", "params": {"length": 100}},
         "grounded": True},
        {"id": "nut", "source": "catalog", "ref": {"generator": "vslot.tnut", "params": {"thread": "M5"}}},
    ], "mates": [{"a": "rail.slot_xp_0", "b": "nut.seat", "type": "fixed", "align": "aligned",
                  "offset": -1.8}]}
    b = build_assembly(spec)
    assert b.ok, b.issues
    r = validate_assembly(b)
    assert r.passed, r.failed
