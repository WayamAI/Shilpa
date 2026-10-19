"""Edge selectors: "outer" / "inner" circles are decided by the curved face they border, not the bounding box.

The fixture is the plan most models wrote for "shaft 200 long, 20 dia, 16 dia step 10 long, 1 mm chamfers
both ends" in the model screen (evals/screen_models.py): sensible, but the old bounding-box rule called the
16 mm step's end circle "inner" because it lies inside the 20 mm box, so the selector matched nothing.
"""

import json
from pathlib import Path

import build123d as bd

from shilpa.adapters.build123d_adapter import build, select_edges
from shilpa.contracts.ir import EdgeSelector

RECIPE = json.loads((Path(__file__).parent / "fixtures" / "stepped_shaft_chamfers.json").read_text(encoding="utf-8"))


def test_stepped_shaft_chamfers_build():
    res = build(RECIPE)
    assert res.ok, res.error
    bb = res.shape.bounding_box()
    assert (round(bb.size.X, 6), round(bb.size.Z, 6)) == (20.0, 200.0)


def test_bore_edges_are_inner_and_the_rim_outer():
    disc = bd.Solid.make_cylinder(30, 10).cut(bd.Solid.make_cylinder(10, 10))
    part = bd.Part(disc.wrapped)
    sel = dict(direction="perpendicular_z", location="top", curve="circle", expected_count=1)
    outer = select_edges(part, EdgeSelector(boundary="outer", **sel))
    inner = select_edges(part, EdgeSelector(boundary="inner", **sel))
    assert [round(e.radius, 6) for e in outer] == [30.0] and [round(e.radius, 6) for e in inner] == [10.0]


def test_smaller_step_end_is_outer():
    shaft = bd.Solid.make_cylinder(10, 190, bd.Plane.XY.offset(10)).fuse(bd.Solid.make_cylinder(8, 10)).clean()
    part = bd.Part(shaft.wrapped)
    edges = select_edges(part, EdgeSelector(direction="perpendicular_z", location="bottom", curve="circle",
                                            boundary="outer", expected_count=1))
    assert [round(e.radius, 6) for e in edges] == [8.0]
