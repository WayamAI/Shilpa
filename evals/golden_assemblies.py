"""Golden assemblies: recipe-only products with check outcomes fixed before running.

Each case is an ``AssemblySpec`` dict plus the outcome every named check must have
(checks not listed must pass), the static issue codes expected, and the computed
DOF. Geometry is chosen so outcomes follow from closed-form reasoning:

- ``standoff_stack``: plate, four standoffs, top plate; all rigid, DOF 0.
- ``hinge``: lid on a pin-carrying base, revolute 0..100 deg; the lid stays 4 mm
  from the pin axis and only swings away from the base, so the sweep is clean.
- ``shaft_bearings``: a 20 mm shaft revolving in two 20.2 mm bores, 0.1 mm radial gap.
- ``slider_rail``: carriage on a 300 mm rail between two end stops, travel +-120 mm,
  touching each stop exactly at the limit.
- ``press_fit_dowel``: 6.02 mm dowel in a 6 mm hole through 8 mm, overlap about
  1.51 mm^3 (> 1 mm^3 threshold), whitelisted at 2 mm^3.
- ``press_fit_unlisted``: the same without the whitelist entry: a clash.
- ``interfering``: a block sunk 2 mm into its base plate (800 mm^3 overlap).
- ``floating``: a part with no mate, unreachable from ground.
- ``hovering``: a "fixed" block 0.5 mm above its plate (the CADSmith quadcopter lesson).
- ``lid_hits_wall``: the hinge with a wall 6 mm behind the pin; the lid tip reaches
  the wall at about 96.5 deg, so the 100 deg end of the sweep collides.

Run:  uv run python evals/golden_assemblies.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

# ---------------------------------------------------------------- recipe and port helpers


def box(w, d, h, cx=0.0, cy=0.0, name=None, holes=None):
    """Box on XY, x in [cx-w/2, cx+w/2], y likewise, z in [0, h]; optional hole features."""
    feats = [
        {"id": "profile", "op": "centered_rectangle", "plane": "XY", "width_ref": "w", "height_ref": "d",
         "center_x_ref": "cx", "center_y_ref": "cy"},
        {"id": "body", "op": "extrude", "profile_ref": "profile", "distance_ref": "h", "direction": "positive_z"},
    ]
    params = {"w": w, "d": d, "h": h, "cx": cx, "cy": cy}
    if holes:
        for k, hole in enumerate(holes):
            params.update({f"hd{k}": hole["d"], **({f"he{k}": hole["edge"]} if "edge" in hole else {})})
            if hole["kind"] == "corners":
                feats.append({"id": f"h{k}", "op": "corner_hole_pattern", "body_ref": feats[-1]["id"],
                              "diameter_ref": f"hd{k}", "edge_offset_ref": f"he{k}", "mode": "through_all"})
            else:
                feats.append({"id": f"h{k}", "op": "hole", "body_ref": feats[-1]["id"], "diameter_ref": f"hd{k}"})
    return {"name": name, "parameters": params, "features": feats}


def cylinder(d, h, name=None):
    """Cylinder on the Z axis, z in [0, h]."""
    return {"name": name, "parameters": {"d": d, "h": h}, "features": [
        {"id": "profile", "op": "circle", "plane": "XY", "diameter_ref": "d"},
        {"id": "body", "op": "extrude", "profile_ref": "profile", "distance_ref": "h", "direction": "positive_z"},
    ]}


def port(name, origin, z=(0, 0, 1), x=None, **contract):
    if x is None:
        x = (0, 0, 1) if abs(z[2]) < 0.9 else (1, 0, 0)
    return {"name": name, "origin": list(origin), "z": list(z), "x": list(x), "contract": contract}


def inst(iid, recipe=None, ports=(), **kw):
    out = {"id": iid, "source": "recipe", **kw}
    if recipe is not None:
        out["ref"] = {"recipe": recipe, "ports": list(ports)}
    return out


UP, DOWN = (0, 0, 1), (0, 0, -1)


# ---------------------------------------------------------------- cases


def standoff_stack():
    corners = [(-34, -24), (34, -24), (34, 24), (-34, 24)]
    plate_ports = [port(f"s{k + 1}", (x, y, 4), UP, hole_d=3.2) for k, (x, y) in enumerate(corners)]
    plate_ports += [port(f"b{k + 1}", (x, y, 0), DOWN, hole_d=3.2) for k, (x, y) in enumerate(corners)]
    plate = box(80, 60, 4, name="plate", holes=[{"kind": "corners", "d": 3.2, "edge": 6}])
    standoff = cylinder(6, 10, name="standoff")
    so_ports = [port("bottom", (0, 0, 0), DOWN, hole_d=3.2), port("top", (0, 0, 10), UP, hole_d=3.2)]
    instances = [inst("base", plate, plate_ports, grounded=True, part_number="plate", color="steelblue"),
                 inst("so1", standoff, so_ports, part_number="standoff", color="gold")]
    instances += [inst(f"so{k}", copy_of="so1") for k in (2, 3, 4)]
    instances.append(inst("top", copy_of="base", color="lightsteelblue"))
    mates = [{"a": f"base.s{k}", "b": f"so{k}.bottom", "type": "fixed", "intent": "bolted"} for k in (1, 2, 3, 4)]
    mates.append({"a": "so1.top", "b": "top.b1", "type": "fixed", "intent": "bolted"})
    spec = {"name": "standoff_stack", "instances": instances, "mates": mates, "dof": 0,
            "bom": {"plate": 2, "standoff": 4}, "clearances": [{"a": "so3", "b": "top", "min": 0, "max": 0.001}]}
    return spec


def _hinge(wall: bool):
    # Base y spans [-24, 24] (or to 40 with a wall shelf); the pin rests on its top at the back edge.
    base = box(60, 64 if wall else 48, 5, cy=8 if wall else 0, name="hinge_base")
    pin = cylinder(4, 60, name="pin")
    lid = box(60, 40, 3, name="lid")
    axis = (-1, 0, 0)  # lid opens upward when turning positive about -X (see module docstring)
    instances = [
        inst("base", base, [port("pin_seat", (0, 24, 5), UP), port("hinge", (0, 24, 7), axis, (0, 0, 1)),
                            port("wall_seat", (0, 33, 5), UP)], grounded=True, color="dimgray"),
        inst("pin", pin, [port("seat", (0, 2, 30), (0, -1, 0), (0, 0, 1))], color="silver"),
        inst("lid", lid, [port("hinge", (0, 24, 2), axis, (0, 0, 1))], color="orange"),
    ]
    mates = [
        # The pin lies along X, tangent to the base top along its length.
        {"a": "base.pin_seat", "b": "pin.seat", "type": "fixed", "align": "aligned", "angle": 0, "intent": "welded"},
        {"id": "hinge", "a": "base.hinge", "b": "lid.hinge", "type": "revolute", "limits": [0, 100], "intent": "clearance"},
    ]
    if wall:
        instances.append(inst("wall", box(60, 6, 50, name="wall"), [port("foot", (0, 0, 0), DOWN)], color="brown"))
        mates.append({"a": "base.wall_seat", "b": "wall.foot", "type": "fixed", "intent": "welded"})
    return {"name": "lid_hits_wall" if wall else "hinge", "instances": instances, "mates": mates, "dof": 1,
            "clearances": [{"a": "lid", "b": "pin", "min": 1.9}]}


def hinge():
    return _hinge(False)


def lid_hits_wall():
    return _hinge(True)


def shaft_bearings():
    base = box(80, 200, 6, name="base_plate")
    block = box(40, 40, 20, name="bearing_block", holes=[{"kind": "center", "d": 20.2}])
    shaft = {"name": "shaft", "parameters": {"d": 20, "l": 160}, "features": [
        {"id": "body", "op": "stepped_shaft", "sections": [{"diameter_ref": "d", "length_ref": "l"}]}]}
    block_ports = [port("foot", (0, -20, 10), (0, -1, 0), (1, 0, 0)), port("bore", (0, 0, 10), UP, bore_d=20)]
    instances = [
        inst("base", base, [port("left", (0, -60, 6), UP), port("right", (0, 60, 6), UP)], grounded=True),
        inst("block1", block, block_ports, part_number="block", color="darkcyan"),
        inst("block2", copy_of="block1"),
        inst("shaft", shaft, [port("axis", (0, 0, 140), UP, bore_d=20)], color="silver"),
    ]
    mates = [
        {"a": "base.left", "b": "block1.foot", "type": "fixed", "intent": "bolted"},
        {"a": "base.right", "b": "block2.foot", "type": "fixed", "intent": "bolted"},
        {"id": "spin", "a": "block1.bore", "b": "shaft.axis", "type": "revolute", "limits": [0, 360], "intent": "clearance"},
    ]
    clear = [{"a": "shaft", "b": b, "min": 0.05, "max": 0.15} for b in ("block1", "block2")]
    return {"name": "shaft_bearings", "instances": instances, "mates": mates, "dof": 1, "clearances": clear,
            "bom": {"base": 1, "block": 2, "shaft": 1}, "tolerances": {"sweep_steps": 4}}


def slider_rail():
    rail = box(300, 20, 10, name="rail")
    carriage = box(40, 30, 15, name="carriage")
    stop = box(10, 20, 20, name="end_stop")
    along = (1, 0, 0)
    instances = [
        inst("rail", rail, [port("track", (0, 0, 10), along, (0, 0, 1)), port("end_l", (-145, 0, 10), UP),
                            port("end_r", (145, 0, 10), UP)], grounded=True),
        inst("carriage", carriage, [port("shoe", (0, 0, 0), along, (0, 0, 1))], color="tomato"),
        inst("stop_l", stop, [port("foot", (0, 0, 0), DOWN)], part_number="end_stop"),
        inst("stop_r", copy_of="stop_l"),
    ]
    mates = [
        {"id": "travel", "a": "rail.track", "b": "carriage.shoe", "type": "slider", "limits": [-120, 120]},
        {"a": "rail.end_l", "b": "stop_l.foot", "type": "fixed", "intent": "bolted"},
        {"a": "rail.end_r", "b": "stop_r.foot", "type": "fixed", "intent": "bolted"},
    ]
    return {"name": "slider_rail", "instances": instances, "mates": mates, "dof": 1,
            "clearances": [{"a": "carriage", "b": "stop_r", "min": 120, "max": 120.001}], "tolerances": {"sweep_steps": 5}}


def press_fit_dowel(listed: bool = True):
    plate = box(30, 30, 8, name="plate", holes=[{"kind": "center", "d": 6}])
    dowel = cylinder(6.02, 20, name="dowel")
    instances = [inst("plate", plate, [port("bore", (0, 0, 4), UP, fit="H7/p6")], grounded=True),
                 inst("dowel", dowel, [port("mid", (0, 0, 10), UP, fit="H7/p6")])]
    mates = [{"a": "plate.bore", "b": "dowel.mid", "type": "fixed", "align": "aligned", "intent": "press_fit"}]
    spec = {"name": "press_fit_dowel" if listed else "press_fit_unlisted", "instances": instances, "mates": mates, "dof": 0}
    if listed:
        spec["interference_allowed"] = [{"a": "plate", "b": "dowel", "max_volume": 2.0, "reason": "press_fit"}]
    return spec


def _block_on_plate(name, offset, extra=()):
    plate = box(60, 60, 5, name="plate")
    block = box(20, 20, 20, name="block")
    instances = [inst("plate", plate, [port("top", (0, 0, 5), UP)], grounded=True),
                 inst("block", block, [port("foot", (0, 0, 0), DOWN)]), *extra]
    mates = [{"a": "plate.top", "b": "block.foot", "type": "fixed", "offset": offset, "intent": "bolted"}]
    return {"name": name, "instances": instances, "mates": mates, "dof": 0}


def interfering():
    return _block_on_plate("interfering", -2.0)


def floating():
    return _block_on_plate("floating", 0.0, [inst("spare", cylinder(10, 10, name="spare"))])


def hovering():
    return _block_on_plate("hovering", 0.5)


GOLDEN: dict[str, dict] = {
    "standoff_stack": {"spec": standoff_stack, "dof": 0, "fail": [], "issues": []},
    "hinge": {"spec": hinge, "dof": 1, "fail": [], "issues": []},
    "shaft_bearings": {"spec": shaft_bearings, "dof": 1, "fail": [], "issues": []},
    "slider_rail": {"spec": slider_rail, "dof": 1, "fail": [], "issues": []},
    "press_fit_dowel": {"spec": press_fit_dowel, "dof": 0, "fail": [], "issues": []},
    "press_fit_unlisted": {"spec": lambda: press_fit_dowel(False), "dof": 0,
                           "fail": ["interference[dowel+plate]", "interference"], "issues": []},
    "interfering": {"spec": interfering, "dof": 0, "fail": ["interference[block+plate]", "interference"], "issues": []},
    "floating": {"spec": floating, "dof": 0, "fail": ["spec_valid", "all_placed"], "issues": ["unreachable"]},
    "hovering": {"spec": hovering, "dof": 0, "fail": ["contact[plate.top~block.foot]"], "issues": []},
    "lid_hits_wall": {"spec": lid_hits_wall, "dof": 1, "fail": ["sweep[hinge]"], "issues": []},
}


def case(name: str) -> dict:
    return copy.deepcopy(GOLDEN[name]["spec"]())


def run(name: str):
    from shilpa.assembly.build import build_assembly
    from shilpa.validators.assembly import validate_assembly

    build = build_assembly(case(name))
    return build, validate_assembly(build)


def outcome_errors(name: str, report) -> list[str]:
    """Differences between a report and the golden expectation (empty when it matches)."""
    g = GOLDEN[name]
    errs = []
    failed = set(report.failed)
    if failed != set(g["fail"]):
        errs.append(f"failed checks {sorted(failed)} != expected {sorted(g['fail'])}")
    if report.dof["computed"] != g["dof"]:
        errs.append(f"dof {report.dof['computed']} != {g['dof']}")
    return errs


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import time

    bad = 0
    for name in GOLDEN:
        t0 = time.perf_counter()
        build, report = run(name)
        errs = outcome_errors(name, report)
        issues = sorted({i.code for i in build.issues})
        if issues != sorted(GOLDEN[name]["issues"]):
            errs.append(f"issues {issues} != {GOLDEN[name]['issues']}")
        bad += bool(errs)
        print(f"{'ok ' if not errs else 'BAD'} {name:20s} {time.perf_counter() - t0:6.2f}s  failed={report.failed}  {'; '.join(errs)}")
    sys.exit(1 if bad else 0)
