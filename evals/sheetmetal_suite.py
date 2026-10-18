"""Sheet-metal suite (roadmap R2, first cut of the 100-task internal suite).

Generates seeded parametric variants across part families, builds each through
``shilpa.sheetmetal``, runs every check and compares against outcomes fixed
before running: closed-form flat size and outer size where the family has one,
and the exact set of rule violations a variant was designed to trigger.

"Unfold success" counts variants that built and passed every geometry and
consistency check (single solid, no overlaps, constant thickness, bend allowance,
refold, volume from flat) plus the flat-size oracle. The R2 gate is >= 95%.

Run:  uv run python evals/sheetmetal_suite.py [--n 20] [--seed 7] [--out evals/out/sheetmetal]
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shilpa.contracts.errors import ShilpaError  # noqa: E402
from shilpa.sheetmetal import Cutout, EdgeFlange, Hem, PolyOutline, RectOutline, SheetMetalSpec, build  # noqa: E402
from shilpa.sheetmetal.checks import check  # noqa: E402

GEOMETRY_CHECKS = (
    "single_valid_solid",
    "no_folded_overlap",
    "no_flat_overlap",
    "constant_thickness",
    "bend_allowance",
    "refold_points_on_solid",
    "refold_outer_dims",
    "volume_from_flat",
)
RULES = ("min_flange_length", "hole_to_bend", "cutout_inside_wall")
TOL = 1e-6


def _stock(rng: random.Random) -> dict:
    t = rng.choice([0.8, 1.0, 1.5, 2.0, 3.0])
    return {
        "material": rng.choice(["steel", "aluminium", "stainless"]),
        "thickness": t,
        "bend_radius": round(t * rng.choice([0.5, 1.0, 1.5, 2.0]), 3),
    }


def _leg(rng: random.Random, st: dict, lo: float, hi: float, angle: float = 90.0) -> float:
    """Outer flange length in [lo, hi], raised if needed to clear the 2.5T + R rule."""
    t, r = st["thickness"], st["bend_radius"]
    return max(rng.uniform(lo, hi), (r + t) * math.tan(math.radians(angle) / 2) + 2 * t)


def _ba(s: SheetMetalSpec, angle: float, r: float) -> float:
    return math.radians(angle) * (r + s.k_for(r) * s.thickness)


# Each family returns (spec, oracle) with oracle = {"flat": (x, y) | None,
# "outer": (x, y, z) | None, "violations": set of check-name prefixes, "negative": bool}.


def l_bracket(rng, i):
    st = _stock(rng)
    w, d, h = rng.uniform(40, 150), rng.uniform(30, 90), _leg(rng, st, 15, 60)
    s = SheetMetalSpec(name=f"l_{i}", **st, base=RectOutline(width=w, depth=d), flanges=[EdgeFlange(id="leg", edge="base.north", length=h)])
    T, R = s.thickness, s.bend_radius
    return s, {"flat": (w, d + _ba(s, 90, R) + h - (R + T)), "outer": (w, d + R + T, h), "violations": set()}


def u_channel(rng, i):
    st = _stock(rng)
    w, d, h = rng.uniform(60, 200), rng.uniform(30, 80), _leg(rng, st, 15, 50)
    s = SheetMetalSpec(
        name=f"u_{i}", **st, base=RectOutline(width=w, depth=d),
        flanges=[EdgeFlange(id=n, edge=f"base.{n}", length=h, position="flush") for n in ("north", "south")],
    )
    sb = s.bend_radius + s.thickness
    return s, {"flat": (w, d - 2 * sb + 2 * (_ba(s, 90, s.bend_radius) + h - sb)), "outer": (w, d, h), "violations": set()}


def z_profile(rng, i):
    st = _stock(rng)
    w, d, h, lip = rng.uniform(40, 120), rng.uniform(25, 60), _leg(rng, st, 20, 50), _leg(rng, st, 12, 30)
    s = SheetMetalSpec(
        name=f"z_{i}", **st, base=RectOutline(width=w, depth=d),
        flanges=[EdgeFlange(id="web", edge="base.north", length=h), EdgeFlange(id="lip", edge="web.far", length=lip, direction="down")],
    )
    T, R = s.thickness, s.bend_radius
    ba = _ba(s, 90, R)
    return s, {"flat": (w, d + ba + (h - R - T) + ba + (lip - R - T)), "outer": None, "violations": set()}


def tray(rng, i):
    st = _stock(rng)
    w, d, h = rng.uniform(80, 250), rng.uniform(60, 180), _leg(rng, st, 15, 60)
    s = SheetMetalSpec(
        name=f"tray_{i}", **st, base=RectOutline(width=w, depth=d),
        corner_relief={"kind": rng.choice(["square", "circle"])},
        flanges=[EdgeFlange(id=n, edge=f"base.{n}", length=h, position="flush") for n in ("north", "south", "east", "west")],
    )
    sb = s.bend_radius + s.thickness
    leg = _ba(s, 90, s.bend_radius) + h - sb
    return s, {"flat": (w - 2 * sb + 2 * leg, d - 2 * sb + 2 * leg), "outer": (w, d, h), "violations": set()}


def lid(rng, i):
    """Down-flanged lid with mounting holes; every other lid puts its holes too close to a bend."""
    st = _stock(rng)
    T, R = st["thickness"], st["bend_radius"]
    w, d, h = rng.uniform(100, 220), rng.uniform(70, 150), _leg(rng, st, 18, 40)
    sb = R + T
    rule = 2 * T + R
    hole = 3.5
    near = (i // len(FAMILIES)) % 2 == 1
    gap = rule * (0.5 if near else 1.5)  # hole edge to bend tangent line
    cut = [Cutout(id=f"m{k}", center=(sx * (w / 2 - sb - gap - hole / 2), sy * (d / 2 - sb - rule * 2 - hole)), diameter=hole)
           for k, (sx, sy) in enumerate([(1, 1), (-1, 1), (-1, -1), (1, -1)])]
    s = SheetMetalSpec(
        name=f"lid_{i}", **st, base=RectOutline(width=w, depth=d), corner_relief={"kind": "square"},
        flanges=[EdgeFlange(id=n, edge=f"base.{n}", length=h, position="flush", direction="down") for n in ("north", "south", "east", "west")],
        cutouts=cut,
    )
    return s, {"flat": None, "outer": (w, d, h), "violations": {"hole_to_bend"} if near else set()}


def hemmed_panel(rng, i):
    st = _stock(rng)
    w, d = rng.uniform(60, 200), rng.uniform(40, 120)
    kind = rng.choice(["open", "closed"])
    T = st["thickness"]
    length = rng.uniform(4 * T, 8 * T)
    s = SheetMetalSpec(name=f"hem_{i}", **st, base=RectOutline(width=w, depth=d), hems=[Hem(id="hem", edge="base.north", length=length, kind=kind)])
    g = T if kind == "open" else 0.1 * T
    return s, {"flat": (w, d + _ba(s, 180, g / 2) + length), "outer": (w, d + g / 2 + T, 2 * T + g), "violations": set()}


def hexagon(rng, i):
    """Flanges on all six edges. Angles stay <= 90 so walls lean apart at the open
    corners; past 90 adjacent walls lean together and genuinely collide."""
    st = _stock(rng)
    rr = rng.uniform(40, 90)
    pts = [(rr * math.cos(math.radians(60 * k)), rr * math.sin(math.radians(60 * k))) for k in range(6)]
    h = _leg(rng, st, 15, 35)
    s = SheetMetalSpec(
        name=f"hex_{i}", **st, base=PolyOutline(points=pts),
        flanges=[EdgeFlange(id=f"f{k}", edge=f"base.edge_{k}", length=h, angle=rng.choice([90, 75, 60])) for k in range(6)],
        cutouts=[Cutout(id="bore", center=(0, 0), diameter=rr / 2)],
    )
    return s, {"flat": None, "outer": None, "violations": set()}


def partial_flange(rng, i):
    st = _stock(rng)
    w, d = rng.uniform(80, 160), rng.uniform(40, 90)
    inset = rng.uniform(10, w / 4)
    lip_angle = rng.choice([45, 60, 90])
    s = SheetMetalSpec(
        name=f"tab_{i}", **st, base=RectOutline(width=w, depth=d), relief={"kind": rng.choice(["rect", "obround"])},
        flanges=[
            EdgeFlange(id="tab", edge="base.north", length=_leg(rng, st, 15, 40), offset_start=inset, offset_end=inset, position=rng.choice(["flush", "outside"])),
            EdgeFlange(id="lip", edge="base.south", length=_leg(rng, st, 10, 25, lip_angle), direction="down", angle=lip_angle),
        ],
    )
    return s, {"flat": None, "outer": None, "violations": set()}


def short_flange(rng, i):
    """Designed violation: a flange shorter than 2.5T + R."""
    st = _stock(rng)
    T, R = st["thickness"], st["bend_radius"]
    s = SheetMetalSpec(
        name=f"short_{i}", **st, base=RectOutline(width=60, depth=40),
        flanges=[EdgeFlange(id="stub", edge="base.east", length=T, length_type="flat")],
    )
    return s, {"flat": (60 + _ba(s, 90, R) + T, 40), "outer": None, "violations": {"min_flange_length"}}


def overlap(rng, i):
    """Negative control: corner-extended flanges collide; must be caught, not unfolded."""
    st = _stock(rng)
    e = st["bend_radius"] + st["thickness"] + rng.uniform(1, 4)
    s = SheetMetalSpec(
        name=f"clash_{i}", **st, base=RectOutline(width=100, depth=80),
        flanges=[
            EdgeFlange(id="n", edge="base.north", length=30, position="flush", offset_start=-e, offset_end=-e),
            EdgeFlange(id="e", edge="base.east", length=30, position="flush", offset_start=-e, offset_end=-e),
        ],
    )
    return s, {"flat": None, "outer": None, "violations": set(), "negative": True}


FAMILIES = [l_bracket, u_channel, z_profile, tray, lid, hemmed_panel, hexagon, partial_flange, short_flange, overlap]


def run_one(fn, rng, i, out: Path | None) -> dict:
    spec, oracle = fn(rng, i)
    row = {"id": spec.name, "family": fn.__name__, "negative": oracle.get("negative", False)}
    t0 = time.perf_counter()
    try:
        part = build(spec)
        report = check(part)
    except ShilpaError as exc:
        row.update(built=False, error=str(exc), ms=round((time.perf_counter() - t0) * 1000))
        return row
    failed = report.failed()
    prefixes = {n.split(":")[0] for n in failed}
    geometry_failed = sorted(p for p in prefixes if p in GEOMETRY_CHECKS)
    violations = {p for p in prefixes if p in RULES}
    flat_ok = oracle["flat"] is None or all(abs(a - b) < TOL for a, b in zip(part.flat_size(), oracle["flat"]))
    bb = part.solid.bounding_box()
    outer_ok = oracle["outer"] is None or all(abs(a - b) < TOL for a, b in zip((bb.size.X, bb.size.Y, bb.size.Z), oracle["outer"]))
    unfold_ok = not geometry_failed and flat_ok and outer_ok
    if row["negative"]:
        expected = bool(geometry_failed)  # the clash must be detected
    else:
        expected = unfold_ok and violations == oracle["violations"]
    row.update(
        built=True,
        unfold_ok=unfold_ok,
        flat_oracle=flat_ok,
        outer_oracle=outer_ok,
        geometry_failed=geometry_failed,
        violations=sorted(violations),
        expected_violations=sorted(oracle["violations"]),
        as_expected=expected,
        flat_size=[round(v, 4) for v in part.flat_size()],
        bends=len(part.bends),
        ms=round((time.perf_counter() - t0) * 1000),
    )
    if out is not None and unfold_ok:
        out.mkdir(parents=True, exist_ok=True)
        part.export_step(out / f"{spec.name}.step")
        part.export_dxf(out / f"{spec.name}.dxf")
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="", help="write STEP/DXF and results.json here")
    args = ap.parse_args()
    rng = random.Random(args.seed)
    out = Path(args.out) if args.out else None

    rows = []
    t_all = time.perf_counter()
    for i in range(args.n):
        row = run_one(FAMILIES[i % len(FAMILIES)], rng, i, out)
        rows.append(row)
        tag = "OK  " if row.get("as_expected") else "MISS"
        detail = row.get("error") or f"geom_fail={row['geometry_failed']} rules={row['violations']} flat={row['flat_size']}"
        print(f"{tag} {row['id']:10} {row['family']:15} {row['ms']:5d} ms  {detail}")

    positives = [r for r in rows if not r["negative"]]
    negatives = [r for r in rows if r["negative"]]
    unfold = sum(1 for r in positives if r.get("unfold_ok"))
    rule_counts = Counter(v for r in rows for v in r.get("violations", []))
    summary = {
        "variants": len(rows),
        "built": sum(1 for r in rows if r.get("built")),
        "unfold_success": f"{unfold}/{len(positives)}",
        "unfold_success_rate": round(unfold / len(positives), 4) if positives else None,
        "negatives_caught": f"{sum(1 for r in negatives if r.get('as_expected'))}/{len(negatives)}",
        "as_expected": f"{sum(1 for r in rows if r.get('as_expected'))}/{len(rows)}",
        "rule_violations": dict(rule_counts),
        "seconds": round(time.perf_counter() - t_all, 2),
    }
    print(json.dumps(summary, indent=2))
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        (out / "results.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=2), encoding="utf-8")
    return 0 if all(r.get("as_expected") for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
