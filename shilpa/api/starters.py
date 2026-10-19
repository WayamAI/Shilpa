"""Reference starters that need no planner: the golden assemblies and sheet-metal examples.

The golden assemblies come straight from ``evals/golden_assemblies.py`` (their check
outcomes are fixed there before running), so the studio picker and the eval gate
always agree. The sheet-metal examples are small, hand-checked specs: four that
pass every rule and one built to break the hole-to-bend rule.
"""

from __future__ import annotations

import importlib.util
from functools import lru_cache
from types import ModuleType

from ..settings import ROOT

GOLDEN_FILE = ROOT / "evals" / "golden_assemblies.py"

ASSEMBLY_TEXT = {
    "standoff_stack": ("Standoff stack", "Two plates on four standoffs, all bolted; DOF 0."),
    "hinge": ("Hinge", "A lid on a pin-carrying base, revolute 0 to 100 degrees; the sweep is clean."),
    "shaft_bearings": ("Shaft in two bearings", "A 20 mm shaft spinning in two 20.2 mm bores, 0.1 mm radial gap."),
    "slider_rail": ("Slider on a rail", "A carriage travelling +-120 mm between two end stops."),
    "press_fit_dowel": ("Press-fit dowel", "A 6.02 mm dowel in a 6 mm hole, overlap whitelisted as a press fit."),
    "press_fit_unlisted": ("Press fit, not whitelisted", "The same dowel without the allowance: reported as a clash."),
    "interfering": ("Interfering block", "A block sunk 2 mm into its plate: an 800 mm3 interference."),
    "floating": ("Floating part", "A part with no mate, unreachable from the ground."),
    "hovering": ("Hovering block", "A fixed block 0.5 mm above its plate: the contact check fails."),
    "lid_hits_wall": ("Lid hits wall", "The hinge with a wall behind the pin; the lid reaches it near 96.5 degrees."),
}


@lru_cache(maxsize=1)
def _golden() -> ModuleType | None:
    if not GOLDEN_FILE.exists():
        return None
    spec = importlib.util.spec_from_file_location("shilpa_golden_assemblies", GOLDEN_FILE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def assembly_starters() -> list[dict]:
    mod = _golden()
    if mod is None:
        return []
    out = []
    for name, g in mod.GOLDEN.items():
        title, text = ASSEMBLY_TEXT.get(name, (name.replace("_", " ").capitalize(), ""))
        out.append({"id": name, "kind": "assembly", "title": title, "description": text,
                    "expected": {"fail": list(g["fail"]), "dof": g["dof"]}, "spec": mod.case(name)})
    return out


def _rect(width, depth):
    return {"kind": "rect", "width": width, "depth": depth}


SHEET_METAL = [
    {"id": "l_bracket", "title": "L bracket", "description": "2 mm steel, 100 x 50 base, 30 mm leg, two mounting holes.",
     "expected": {"passed": True},
     "spec": {"name": "l_bracket", "material": "steel", "thickness": 2.0, "bend_radius": 2.0, "base": _rect(100, 50),
              "flanges": [{"id": "leg", "edge": "base.north", "length": 30}],
              "cutouts": [{"id": "m1", "center": [-30, -8], "diameter": 6.5}, {"id": "m2", "center": [30, -8], "diameter": 6.5}]}},
    {"id": "u_channel", "title": "U channel", "description": "1.5 mm aluminium, 120 x 40 web, two 25 mm walls.",
     "expected": {"passed": True},
     "spec": {"name": "u_channel", "material": "aluminium", "thickness": 1.5, "bend_radius": 1.5, "base": _rect(120, 40),
              "flanges": [{"id": "wall_n", "edge": "base.north", "length": 25}, {"id": "wall_s", "edge": "base.south", "length": 25}]}},
    {"id": "enclosure_tray", "title": "Enclosure tray",
     "description": "1 mm steel tray, 160 x 100, four 30 mm walls with square corner reliefs and vent holes.",
     "expected": {"passed": True},
     "spec": {"name": "enclosure_tray", "material": "steel", "thickness": 1.0, "bend_radius": 1.0, "base": _rect(160, 100),
              "flanges": [{"id": f"wall_{e}", "edge": f"base.{e}", "length": 30} for e in ("north", "east", "south", "west")],
              "corner_relief": {"kind": "square"},
              "cutouts": [{"id": f"vent{k}", "center": [-45 + 30 * k, 0], "diameter": 8} for k in range(4)]}},
    {"id": "hemmed_panel", "title": "Hemmed panel", "description": "1 mm stainless panel with a safety hem and a 20 mm return flange.",
     "expected": {"passed": True},
     "spec": {"name": "hemmed_panel", "material": "stainless", "thickness": 1.0, "bend_radius": 1.0, "base": _rect(200, 80),
              "hems": [{"id": "hem", "edge": "base.north", "length": 8, "kind": "closed"}],
              "flanges": [{"id": "return", "edge": "base.south", "length": 20}]}},
    {"id": "hole_near_bend", "title": "Hole too close to a bend",
     "description": "An L bracket whose holes sit 3 mm from the bend: the hole-to-bend rule fails.",
     "expected": {"passed": False, "fail": ["hole_to_bend"]},
     "spec": {"name": "hole_near_bend", "material": "steel", "thickness": 2.0, "bend_radius": 2.0, "base": _rect(100, 50),
              "flanges": [{"id": "leg", "edge": "base.north", "length": 30}],
              "cutouts": [{"id": "m1", "center": [-30, 19], "diameter": 6}, {"id": "m2", "center": [30, 19], "diameter": 6}]}},
]


def sheet_metal_starters() -> list[dict]:
    import copy

    return [{**copy.deepcopy(x), "kind": "sheet_metal"} for x in SHEET_METAL]
