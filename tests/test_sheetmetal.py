"""Sheet-metal sub-IR: folded solid, flat pattern and checks against closed-form oracles.

Notation: T thickness, R inner bend radius, K K-factor, BA = angle * (R + K*T),
s = (R + T) * tan(angle/2) the outer setback (R + T at 90 degrees).
"""

import math

import build123d as bd
import ezdxf
import pytest

from shilpa.contracts.errors import ErrorCode, ShilpaError
from shilpa.sheetmetal import (
    Cutout,
    EdgeFlange,
    Hem,
    KFactorRow,
    PolyOutline,
    RectOutline,
    SheetMetalSpec,
    build,
    din6935_k,
)
from shilpa.sheetmetal.checks import check, refold

T, R, K = 2.0, 3.0, 0.4
BA90 = math.pi / 2 * (R + K * T)
S90 = R + T
SECTOR90 = math.pi / 2 * (R + T / 2) * T  # folded bend volume per mm of bend width
EXACT = 1e-6
VOL = 1e-6  # relative


def spec(**kw) -> SheetMetalSpec:
    return SheetMetalSpec(thickness=T, bend_radius=R, k_factor=K, **kw)


def bbox(shape):
    bb = shape.bounding_box()
    return (bb.size.X, bb.size.Y, bb.size.Z)


def assert_close(actual, expected, tol=EXACT):
    for a, e in zip(actual, expected):
        assert abs(a - e) < tol, (actual, expected)


def assert_passes(part):
    report = check(part)
    assert report.passed, [(c.name, c.actual, c.note) for c in report.checks if not c.passed]
    return report


# ---------------------------------------------------------------- oracles


def test_l_bracket():
    W, D, H = 100.0, 50.0, 30.0
    part = build(spec(base=RectOutline(width=W, depth=D), flanges=[EdgeFlange(id="leg", edge="base.north", length=H)]))
    straight = H - S90
    assert_close(part.flat_size(), (W, D + BA90 + straight))
    assert abs(part.flat.area - W * (D + BA90 + straight)) < 1e-6
    assert_close(bbox(part.solid), (W, D + R + T, H))
    vol = W * T * (D + straight) + SECTOR90 * W
    assert abs(part.solid.volume - vol) < VOL * vol
    # Volume = flat area * T exactly when K = 1/2; otherwise off by (1/2 - K) * angle * T^2 * width.
    assert abs(part.solid.volume - (part.flat.area * T + (0.5 - K) * math.pi / 2 * T * T * W)) < VOL * vol
    report = assert_passes(part)
    assert report.stats["bends"] == 1
    row = part.meta()["bend_table"][0]
    assert row["angle"] == 90 and row["radius"] == R and abs(row["allowance"] - BA90) < 1e-6 and row["direction"] == "up"


def test_u_channel_outer_dims_with_flush_flanges():
    W, D, H = 120.0, 60.0, 25.0
    part = build(
        spec(
            base=RectOutline(width=W, depth=D),
            flanges=[EdgeFlange(id=n, edge=f"base.{n}", length=H, position="flush") for n in ("north", "south")],
        )
    )
    # Outer virtual sharps sit on the given outline, so the channel is exactly W x D x H.
    assert_close(bbox(part.solid), (W, D, H))
    assert_close(part.flat_size(), (W, (D - 2 * S90) + 2 * (BA90 + H - S90)))
    assert_passes(part)


def test_down_flange_and_inner_length():
    part = build(
        spec(base=RectOutline(width=80, depth=40), flanges=[EdgeFlange(id="lip", edge="base.east", length=20, direction="down", length_type="inner")])
    )
    straight = 20 - R
    bb = part.solid.bounding_box()
    # A down bend hangs below z = 0: the lip's straight wall starts R below the base and
    # its outer face sits R + T past the edge.
    assert abs(bb.min.Z - (-(R + straight))) < EXACT
    assert abs(bb.max.X - (40 + R + T)) < EXACT
    assert_close(part.flat_size(), (80 + BA90 + straight, 40))
    assert_passes(part)


@pytest.mark.parametrize("kind", ["square", "circle"])
def test_tray_with_corner_reliefs(kind):
    W, D, H, c = 200.0, 150.0, 40.0, 3.0
    part = build(
        spec(
            base=RectOutline(width=W, depth=D),
            corner_relief={"kind": kind, "size": c},
            flanges=[EdgeFlange(id=n, edge=f"base.{n}", length=H, position="flush") for n in ("north", "south", "east", "west")],
        )
    )
    leg = BA90 + H - S90
    assert_close(bbox(part.solid), (W, D, H))
    assert_close(part.flat_size(), (W - 2 * S90 + 2 * leg, D - 2 * S90 + 2 * leg))
    base = (W - 2 * S90) * (D - 2 * S90) - 4 * (c * c if kind == "square" else math.pi * c * c / 4)
    widths = 2 * (W - 2 * S90 - 2 * c) + 2 * (D - 2 * S90 - 2 * c)
    assert abs(part.flat.area - (base + widths * leg)) < 1e-6
    vol = (base + widths * (H - S90)) * T + widths * SECTOR90
    assert abs(part.solid.volume - vol) < VOL * vol
    for b in part.bends.values():
        assert abs(b.width - (W if b.id in ("north", "south") else D) + 2 * S90 + 2 * c) < EXACT
    assert_passes(part)


@pytest.mark.parametrize("kind,gap", [("open", None), ("closed", None), ("open", 1.0)])
def test_hemmed_edge(kind, gap):
    W, D, L = 90.0, 40.0, 10.0
    part = build(spec(base=RectOutline(width=W, depth=D), hems=[Hem(id="hem", edge="base.north", length=L, kind=kind, gap=gap)]))
    g = gap if gap is not None else (T if kind == "open" else 0.1 * T)
    r = g / 2
    ba = math.pi * (r + K * T)
    assert_close(part.flat_size(), (W, D + ba + L))
    # The fold bulges R + T past the edge and stacks two sheets with the gap between.
    assert_close(bbox(part.solid), (W, D + r + T, 2 * T + g))
    vol = W * T * (D + L) + math.pi * (r + T / 2) * T * W
    assert abs(part.solid.volume - vol) < VOL * vol
    assert_passes(part)


def test_hem_on_flange_and_z_profile():
    part = build(
        spec(
            base=RectOutline(width=60, depth=40),
            flanges=[
                EdgeFlange(id="web", edge="base.north", length=30),
                EdgeFlange(id="top", edge="web.far", length=20, direction="down"),
            ],
            hems=[Hem(id="roll", edge="top.far", length=8)],
        )
    )
    # Flat: base + BA + web straight + BA + top straight + hem BA + hem return.
    hem_ba = math.pi * (T / 2 + K * T)
    assert_close(part.flat_size(), (60, 40 + BA90 + (30 - S90) + BA90 + (20 - S90) + hem_ba + 8))
    assert_passes(part)


def test_enclosure_lid_holes_near_bends_violate_rule():
    """Down-flanged lid; one hole is 3 mm from a bend tangent line (rule: 2T + R = 7)."""
    W, D, H = 120.0, 80.0, 20.0
    x_tangent = W / 2 - S90  # flush flanges trim the base to the bend tangent line
    part = build(
        spec(
            base=RectOutline(width=W, depth=D),
            flanges=[
                EdgeFlange(id=n, edge=f"base.{n}", length=H, position="flush", direction="down")
                for n in ("north", "south", "east", "west")
            ],
            corner_relief={"kind": "square"},
            cutouts=[
                Cutout(id="ok", center=(0, 0), diameter=6),
                Cutout(id="near", center=(x_tangent - 3 - 2, 0), diameter=4),
                Cutout(id="vent", face="north", shape="slot", center=(0, 10), length=20, diameter=4),
                Cutout(id="window", face="south", shape="rect", center=(0, 10), width=10, height=4),
            ],
        )
    )
    assert_close(bbox(part.solid), (W, D, H))
    report = check(part)
    assert not report.passed
    assert report.failed() == ["hole_to_bend:near:east"]
    near = next(c for c in report.checks if c.name == "hole_to_bend:near:east")
    assert abs(near.actual - 3.0) < 1e-6 and abs(near.requested - (2 * T + R)) < 1e-9
    assert report.stats["rule_violations"] == ["hole_to_bend"]
    # Flange cutouts are measured from their own bend: v = 10 minus half of 4 leaves 8 mm.
    for name in ("hole_to_bend:vent:north", "hole_to_bend:window:south"):
        c = next(c for c in report.checks if c.name == name)
        assert c.passed and abs(c.actual - 8.0) < 1e-6
    # Geometry is still a valid single solid with matching flat pattern.
    for name in ("single_valid_solid", "no_folded_overlap", "no_flat_overlap", "constant_thickness", "refold_outer_dims"):
        assert next(c for c in report.checks if c.name == name).passed, name
    ports = part.built_part().ports
    assert {"hole_ok", "hole_near"} <= set(ports) and "hole_vent" not in ports


def test_overlapping_flanges_fail():
    """Two flush flanges each extended 6 mm into the shared corner collide when folded."""
    part = build(
        spec(
            base=RectOutline(width=100, depth=80),
            flanges=[
                EdgeFlange(id="n", edge="base.north", length=30, position="flush", offset_start=-6, offset_end=-6),
                EdgeFlange(id="e", edge="base.east", length=30, position="flush", offset_start=-6, offset_end=-6),
            ],
        )
    )
    report = check(part)
    assert not report.passed
    assert {"no_folded_overlap", "no_flat_overlap", "constant_thickness"} <= set(report.failed())
    flat = next(c for c in report.checks if c.name == "no_flat_overlap")
    assert abs(flat.actual - 36.0) < 1e-6  # the two 6 mm extensions overlap 6 x 6 in the flat


def test_short_flange_violates_min_length():
    part = build(spec(base=RectOutline(width=50, depth=50), flanges=[EdgeFlange(id="stub", edge="base.west", length=2.0, length_type="flat")]))
    report = check(part)
    c = next(c for c in report.checks if c.name == "min_flange_length:stub")
    assert not c.passed and abs(c.actual - (2 + R + T)) < 1e-9 and abs(c.requested - (2.5 * T + R)) < 1e-9


def test_partial_flange_with_reliefs_and_polygon_base():
    pts = [(0, 0), (120, 0), (100, 60), (20, 60)]  # trapezoid, CCW
    part = build(
        SheetMetalSpec(
            thickness=1.5,
            bend_radius=1.5,
            material="aluminium",
            base=PolyOutline(points=pts),
            relief={"kind": "obround"},
            flanges=[
                EdgeFlange(id="front", edge="base.edge_0", length=25, offset_start=20, offset_end=20, position="flush"),
                EdgeFlange(id="slant", edge="base.edge_1", length=15, angle=60),
            ],
            cutouts=[Cutout(id="m4", face="front", center=(0, 12), diameter=4.5)],
        )
    )
    assert abs(part.bends["front"].width - 80) < EXACT
    rep = assert_passes(part)
    assert rep.stats["walls"] == 3
    meta = part.meta()
    assert meta["mass_kg"] == pytest.approx(part.solid.volume * 2700e-9)
    k = din6935_k(1.5, 1.5)
    assert abs(part.bends["front"].k - k) < 1e-12 and abs(k - 0.325) < 1e-12


def test_flange_on_a_flange_side_edge():
    """A tab bent off the side of the north wall wraps the corner outside the east wall."""
    part = build(
        spec(
            base=RectOutline(width=80, depth=60),
            flanges=[
                EdgeFlange(id="n", edge="base.north", length=30, position="flush"),
                EdgeFlange(id="e", edge="base.east", length=30, position="flush", offset_start=4, offset_end=4),
                EdgeFlange(id="tab", edge="n.side_a", length=10, length_type="flat", offset_start=1, offset_end=1),
            ],
        )
    )
    assert "tab" in part.walls
    assert abs(part.solid.bounding_box().max.X - (40 + R + T)) < EXACT
    assert_passes(part)


# ---------------------------------------------------------------- independence of the refold check


def test_refold_rejects_a_mismatched_flat_pattern():
    a = build(spec(base=RectOutline(width=60, depth=40), flanges=[EdgeFlange(id="leg", edge="base.north", length=30)]))
    b = build(spec(base=RectOutline(width=60, depth=40), flanges=[EdgeFlange(id="leg", edge="base.north", length=32)]))
    a.flat = b.flat  # flat pattern 2 mm too long for the folded part
    names = {c.name: c.passed for c in refold(a)}
    assert names["refold_points_on_solid"] is False or names["refold_outer_dims"] is False


def test_bend_allowance_check_uses_the_k_table():
    rows = [KFactorRow(material="steel", rt_min=1.0, rt_max=2.0, k=0.42)]
    s = SheetMetalSpec(thickness=T, bend_radius=R, k_table=rows, base=RectOutline(width=40, depth=40), flanges=[EdgeFlange(id="f", edge="base.south", length=20)])
    part = build(s)
    assert part.bends["f"].k == 0.42  # R/T = 1.5 falls in the row
    assert_passes(part)
    assert SheetMetalSpec(thickness=T, bend_radius=20, k_table=rows, base=RectOutline(width=1, depth=1)).k_for(20) == 0.5


def test_din6935_k():
    assert din6935_k(1, 1) == pytest.approx(0.325)
    assert din6935_k(10, 1) == 0.5
    assert din6935_k(0.05, 1) == 0.2


# ---------------------------------------------------------------- outputs and errors


def test_exports_and_built_part(tmp_path):
    part = build(
        spec(
            name="bracket",
            base=RectOutline(width=70, depth=40),
            flanges=[EdgeFlange(id="a", edge="base.north", length=20), EdgeFlange(id="b", edge="base.south", length=20, direction="down")],
            cutouts=[Cutout(id="m5", center=(10, 0), diameter=5.5)],
        )
    )
    step = part.export_step(tmp_path / "p.step")
    back = bd.import_step(str(step))
    assert abs(back.volume - part.solid.volume) < 1e-5 * part.solid.volume
    dxf = part.export_dxf(tmp_path / "p.dxf")
    doc = ezdxf.readfile(str(dxf))
    msp = doc.modelspace()
    bend_lines = [e for e in msp if e.dxf.layer == "BEND"]
    assert len(bend_lines) == 2 and all(abs(e.dxf.start.distance(e.dxf.end) - 70) < 1e-6 for e in bend_lines)
    assert len([e for e in msp if e.dxf.layer == "BEND_EXTENT"]) == 4
    assert any(e.dxftype() == "CIRCLE" and e.dxf.layer == "OUTLINE" for e in msp)

    bp = part.built_part()
    assert bp.source == "sheet_metal" and bp.name == "bracket"
    hole = bp.port("hole_m5")
    assert hole.contract["diameter"] == 5.5 and hole.z == (0.0, 0.0, -1.0)
    assert_close(hole.origin, (10, 0, 0))
    top = bp.port("a_top")
    assert abs(top.z[1] + 1) < 1e-9  # the up flange's top (inner) face looks back over the base
    assert {"flat_size", "bend_table", "mass_kg", "outer_size"} <= set(bp.meta)
    assert bp.meta["mass_kg"] == pytest.approx(part.solid.volume * 7850e-9)


def test_bad_references_raise():
    with pytest.raises(ShilpaError) as e:
        build(spec(base=RectOutline(width=10, depth=10), flanges=[EdgeFlange(id="f", edge="base.top", length=5)]))
    assert e.value.code == ErrorCode.UNKNOWN_REFERENCE
    with pytest.raises(ShilpaError) as e:
        build(spec(base=RectOutline(width=10, depth=10), flanges=[EdgeFlange(id="f", edge="g.far", length=5)]))
    assert e.value.code == ErrorCode.UNKNOWN_REFERENCE
    with pytest.raises(ShilpaError):
        build(
            spec(
                base=RectOutline(width=10, depth=10),
                flanges=[EdgeFlange(id="f", edge="base.north", length=5), EdgeFlange(id="g", edge="f.near", length=5)],
            )
        )
    with pytest.raises(ValueError):
        PolyOutline(points=[(0, 0), (0, 10), (10, 0)])  # clockwise


def test_cutout_crossing_the_wall_edge_is_flagged():
    part = build(spec(base=RectOutline(width=40, depth=40), cutouts=[Cutout(id="edge", center=(20, 0), diameter=6)]))
    report = check(part)
    assert report.failed() == ["cutout_inside_wall:edge"]
