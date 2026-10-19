"""A repair may not change how stated dimensions reach the geometry (planner.check_repair).

The fixtures are two real repairs from the model evaluation (evals/screen_models.py, G2 holdout and
dev runs): both built, and both changed the request to do it.
"""

import copy
import json
from pathlib import Path

import pytest

from shilpa.agent.planner import check_repair
from shilpa.contracts.errors import ErrorCode, ShilpaError

CASES = json.loads((Path(__file__).parent / "fixtures" / "unsafe_repairs.json").read_text(encoding="utf-8"))


def test_holes_moved_inward_is_caught():
    """L051: 50 mm plate, R10 corners, 8 mm holes 5 mm from the edges. The repair moved the holes inward."""
    with pytest.raises(ShilpaError) as e:
        check_repair(CASES["L051"]["original"], CASES["L051"]["repaired"])
    assert e.value.code == ErrorCode.REQUIREMENT_NOT_MET and "mount_holes.edge_offset" in e.value.info.message


def test_shell_flipped_outward_is_caught():
    """L050: 50 x 50 open box with 30 mm walls. The repair grew the walls outward (a 110 x 110 box)."""
    with pytest.raises(ShilpaError) as e:
        check_repair(CASES["L050"]["original"], CASES["L050"]["repaired"])
    assert "direction was inward" in e.value.info.message


def test_a_repair_that_keeps_the_stated_values_passes():
    original = CASES["L051"]["original"]
    fixed = copy.deepcopy(original)
    # A legitimate repair: change something no stated value drives (the hole fit), keep every stated size.
    for f in fixed["features"]:
        if f["op"] == "corner_hole_pattern":
            f["fit"] = "fine"
    check_repair(original, fixed)
    check_repair(original, copy.deepcopy(original))


def test_restructured_plans_are_left_to_the_coverage_check():
    """Features the repair replaces (new id or op) are not compared; check_requirements still covers them."""
    original = CASES["L051"]["original"]
    renamed = copy.deepcopy(original)
    for f in renamed["features"]:
        if f["id"] == "mount_holes":
            f["id"] = "holes"
    check_repair(original, renamed)
