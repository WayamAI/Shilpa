"""Hand-authored gold requirement tests for the 60-task language eval (roadmap R1 internal gate).

Every build task gets (1) the tests its fixed expectations already encode, converted
mechanically: valid single solid, bounding box, closed-form volume and holes per
diameter; and (2) hand-written tests for requirements the old scorer ignored: hole
positions and edge offsets, bolt circles and phase, through vs blind, step lengths
and order, wall thickness, fillet and chamfer counts, concentricity and symmetry.
Values come from the prompt text only, never from a recipe.

Also writes gold suites for the 30 corpus fixtures from their analytic oracles.

Run:  uv run python evals/make_requirement_tests.py
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent
TASKS = HERE / "language" / "tasks.json"
OUT = HERE / "language" / "gold_tests.json"
CORPUS = HERE / "corpus"
CORPUS_OUT = HERE / "corpus_gold_tests.json"
IN = 25.4


def T(kind: str, requirement: str, **args) -> dict:
    tol = args.pop("tol", None)
    rel_tol = args.pop("rel_tol", None)
    t = {"kind": kind, "requirement": requirement, "args": args}
    if tol is not None:
        t["tol"] = tol
    if rel_tol is not None:
        t["rel_tol"] = rel_tol
    return t


def hole(d: float, which: str = "all") -> dict:
    return {"type": "hole", "diameter": d, "which": which}


def boss(d: float) -> dict:
    return {"type": "boss", "diameter": d}


def rect4(w: float, h: float, off: float) -> list[list[float]]:
    x, y = w / 2 - off, h / 2 - off
    return [[x, y], [-x, y], [x, -y], [-x, -y]]


def corner_plate(w, h, d, off, req):
    return [T("hole_count", req, count=4, diameter=d, through=True),
            T("hole_edge_offset", req, value=off, diameter=d),
            T("hole_positions", req, points=rect4(w, h, off), diameter=d)]


def bolt_circle(d, n, pcd, req):
    return [T("hole_pattern_circle", req, pcd=pcd, diameter=d, count=n),
            T("hole_count", req, count=n, diameter=d, through=True)]


def tube(od, id_, length, req):
    return [T("cylinder", req, type="boss", diameter=od, length=length, axis="z"),
            T("hole_count", req, count=1, diameter=id_, through=True),
            T("concentric", req, a=hole(id_), b=boss(od))]


# Hand-written extras keyed by task id (ids follow make_language_tasks.py order).
EXTRA: dict[str, list[dict]] = {
    "L001": corner_plate(80, 40, 6, 10, "four 6 mm through holes, 10 mm from each edge"),
    "L002": corner_plate(100, 60, 9, 12, "9 mm hole in each corner, centres 12 mm in from the edges"),
    "L003": [T("hole_positions", "3 by 2 grid at 40 mm pitch, centred", diameter=8.5,
               points=[[x, y] for x in (-40, 0, 40) for y in (-20, 20)]),
             T("hole_distance", "40 mm pitch in both directions", value=40, diameter=8.5, mode="nearest"),
             T("symmetric", "grid centred on the plate", plane="yz"),
             T("symmetric", "grid centred on the plate", plane="xz")],
    "L004": [T("centered", "single 20 mm hole in the centre", a=hole(20)),
             T("hole_count", "single 20 mm hole", count=1, through=True)],
    "L005": [T("edge_radius", "four vertical corner edges rounded to R5", radius=5, count=4, convexity="convex"),
             *corner_plate(90, 70, 5.5, 10, "four 5.5 mm holes 10 mm from the edges")],
    "L006": corner_plate(4 * IN, 2 * IN, 0.25 * IN, 0.5 * IN, "four 1/4 inch holes half an inch in from each edge"),
    "L007": [T("chamfer", "2 mm chamfer on all four top edges", distance=2, count=4),
             T("bbox_extent", "5 thick", axis="z", value=5)],
    "L008": corner_plate(200, 100, 4.5, 8, "4 holes of 4.5 mm, 8 mm from the edges"),
    "L009": [*bolt_circle(11, 6, 90, "six 11 mm holes on a 90 mm bolt circle"),
             T("concentric", "50 mm bore", a=hole(50), b=boss(120)),
             T("hole_count", "50 mm bore", count=1, diameter=50, through=True)],
    "L010": [*bolt_circle(10, 4, 75, "4 bolt holes of 10 mm on a 75 mm PCD"),
             T("hole_count", "no centre bore", count=4)],
    "L011": [*bolt_circle(14, 8, 120, "eight 14 mm holes on a 120 mm bolt circle"),
             T("hole_angular_phase", "first hole at 22.5 degrees", value=22.5, diameter=14),
             T("concentric", "bore 60", a=hole(60), b=boss(150))],
    "L012": [T("cylinder", "120 mm OD disc, 12 mm thick", type="boss", diameter=120, length=12, axis="z"),
             T("cylinder", "60 mm diameter hub 25 mm long", type="boss", diameter=60, length=25, axis="z"),
             T("relative_position", "hub on top of the disc", a=boss(60), b=boss(120), axis="z", relation="gt"),
             T("concentric", "hub coaxial with the disc", a=boss(60), b=boss(120)),
             T("hole_count", "35 mm bore through everything", count=1, diameter=35, through=True),
             T("hole_depth", "35 mm bore through everything", diameter=35, value=37),
             T("concentric", "bore concentric with the hub (convention)", a=hole(35), b=boss(60)),
             T("hole_depth", "bolt holes in the disc", diameter=12, value=12),
             *bolt_circle(12, 4, 90, "four 12 mm bolt holes on a 90 mm PCD")],
    "L013": [*corner_plate(100, 100, 10, 12, "four 10 mm holes 12 mm from the edges"),
             T("centered", "50 mm centre bore", a=hole(50))],
    "L014": tube(20, 10, 12, "Spacer, 20 mm OD, 10 mm ID, 12 mm long"),
    "L015": tube(30, 13, 2.5, "outer 30 mm, inner 13 mm, 2.5 mm thick"),
    "L016": [T("cylinder", "25 mm OD, 30 mm long, 1 mm top chamfer", type="boss", diameter=25, length=29, axis="z"),
             T("hole_count", "16 mm bore", count=1, diameter=16, through=True),
             T("concentric", "16 mm bore", a=hole(16), b=boss(25)),
             T("chamfer", "1 mm chamfer on the top outer edge", distance=1, count=1)],
    "L017": tube(8, 3.2, 15, "8 mm diameter, 15 mm tall, 3.2 mm hole through it"),
    "L018": [T("cylinder", "20 mm diameter for 30 mm", type="boss", diameter=20, length=30, axis="z"),
             T("cylinder", "then 12 mm diameter for 20 mm", type="boss", diameter=12, length=20, axis="z"),
             T("relative_position", "12 mm section follows the 20 mm section", a=boss(12), b=boss(20), axis="z", relation="gt"),
             T("concentric", "coaxial sections", a=boss(12), b=boss(20))],
    "L019": [T("cylinder", "diameter 25 x length 10", type="boss", diameter=25, length=10, axis="z"),
             T("cylinder", "diameter 18 x length 40", type="boss", diameter=18, length=40, axis="z"),
             T("cylinder", "diameter 12 x length 25", type="boss", diameter=12, length=25, axis="z"),
             T("relative_position", "from the bottom up: 25 then 18", a=boss(18), b=boss(25), axis="z", relation="gt"),
             T("relative_position", "from the bottom up: 18 then 12", a=boss(12), b=boss(18), axis="z", relation="gt")],
    "L020": [T("cylinder", "10 mm diameter, 100 long, 1 mm chamfer", type="boss", diameter=10, length=99, axis="z"),
             T("chamfer", "1 mm chamfer at the top end", distance=1, count=1),
             T("hole_count", "solid pin", count=0)],
    "L021": [*tube(30, 20, 80, "30 mm OD, 20 mm ID, 80 mm long"),
             T("hole_depth", "hollow along its length", diameter=20, value=80)],
    "L022": [T("cylinder", "1 inch diameter for 2 inches", type="boss", diameter=IN, length=2 * IN, axis="z"),
             T("cylinder", "0.5 inch diameter for 3 inches", type="boss", diameter=IN / 2, length=3 * IN, axis="z"),
             T("relative_position", "then the 0.5 inch section", a=boss(IN / 2), b=boss(IN), axis="z", relation="gt")],
    "L023": [T("edge_radius", "4 mm fillet on the inside corner", radius=4, count=1, convexity="concave"),
             T("wall_thickness", "6 mm thick", value=6, mode="all"),
             T("hole_count", "no holes", count=0),
             T("face_count", "L bracket: L profile prism plus one fillet face", count=9)],
    "L024": [T("wall_thickness", "both legs 8 mm thick", value=8, mode="all"),
             T("cylinder", "two 8.5 mm holes in the horizontal leg", type="hole", diameter=8.5, count=2, axis="z"),
             T("hole_depth", "holes through the 8 mm horizontal leg", diameter=8.5, value=8),
             T("hole_distance", "50 mm apart", value=50, diameter=8.5)],
    "L025": [T("hole_distance", "two 6.5 mm holes 90 mm apart", value=90, diameter=6.5),
             T("hole_positions", "90 mm apart, centred", points=[[45, 0], [-45, 0]], diameter=6.5),
             T("symmetric", "centred", plane="yz"),
             T("hole_count", "through holes", count=2, through=True)],
    "L026": [T("hole_count", "no holes", count=0), T("wall_thickness", "10 mm thick", value=10, mode="all"),
             T("face_count", "L-shaped: an L profile prism has 8 faces", count=8)],
    "L027": [T("wall_thickness", "3 mm walls and floor", value=3, mode="all"),
             T("symmetric", "box", plane="yz"), T("symmetric", "box", plane="xz"),
             T("face_type_count", "open top: no planar top face spanning the box", surface="plane", axis="z", count=3)],
    "L028": [T("wall_thickness", "2 mm walls, 2 mm floor", value=2, mode="all"),
             T("face_type_count", "open on top", surface="plane", axis="z", count=3)],
    "L029": [T("edge_radius", "outer vertical corners rounded R6", radius=6, count=4, convexity="convex"),
             T("edge_radius", "inner pocket corners R3.5", radius=3.5, count=4, convexity="concave"),
             T("wall_thickness", "walls 2.5 mm", value=2.5),
             T("wall_thickness", "walls 2.5 mm, floor 3 mm", values=[2.5, 3], mode="all")],
    "L030": [T("edge_radius", "5 mm fillets on the four vertical outside edges", radius=5, count=4, convexity="convex"),
             T("wall_thickness", "3 mm walls and base", value=3, mode="all")],
    "L031": [*bolt_circle(6.6, 4, 50, "four 6.6 mm holes on a 50 mm bolt circle"),
             T("centered", "30 mm centre hole", a=hole(30))],
    "L032": [T("hole_count", "blind 10 mm hole", count=1, diameter=10, through=False),
             T("hole_depth", "12 mm deep", diameter=10, value=12),
             T("centered", "in the centre of the top face", a=hole(10)),
             T("relative_position", "from the top face", a=hole(10), b={"type": "solid"}, axis="z", relation="gt")],
    "L033": [T("hole_distance", "5 equally spaced holes at 40 mm pitch", value=40, diameter=9, mode="nearest"),
             T("hole_count", "5 holes", count=5, diameter=9, through=True),
             T("symmetric", "along the centreline", plane="xz"),
             T("symmetric", "row centred on the bar (convention)", plane="yz")],
    "L034": [T("chamfer", "2 mm chamfer on the top edge", distance=2, count=1),
             T("cylinder", "60 mm diameter, 8 thick less chamfer", type="boss", diameter=60, length=6, axis="z")],
}
EXTRA["L035"] = EXTRA["L001"]
EXTRA["L036"] = EXTRA["L015"]


def converted(task: dict) -> list[dict]:
    g = task["expect"]["geometry"]
    out = [T("valid_solid", "a valid single solid"),
           T("bbox", "overall size", values=g["bbox"]),
           T("volume", "closed-form volume of the requested part", value=g["volume"])]
    holes = g.get("holes") or {}
    for d, n in holes.items():
        out.append(T("hole_count", f"{n} x {float(d):g} mm holes", count=n, diameter=float(d)))
    return out


def number(tests: list[dict], prefix: str) -> list[dict]:
    return [{"id": f"{prefix}-{i:02d}", **t} for i, t in enumerate(tests, 1)]


# Requirements the corpus descriptions state but the analytic oracles never checked (found by mutation).
CORPUS_EXTRA: dict[str, list[dict]] = {
    "B01": [T("face_count", "L bracket profile", count=8)],
    "B03": [T("face_count", "L bracket profile with one inner fillet", count=9)],
    "F01": [T("concentric", "bore concentric with the flange", a=hole(40), b=boss(100))],
    "F02": [T("concentric", "bore concentric with the flange", a=hole(60), b=boss(150))],
    "F03": [T("concentric", "bore concentric with the hub", a=hole(35), b=boss(60)),
            T("concentric", "hub concentric with the disc", a=boss(60), b=boss(120))],
    "F04": [T("concentric", "bore concentric with the flange", a=hole(30), b=boss(80))],
    "F05": [T("centered", "50 bore centred in the square flange", a=hole(50))],
    "S02": [T("concentric", "bore concentric with the spacer", a=hole(12.5), b=boss(30))],
    "S04": [T("concentric", "bore concentric with the washer", a=hole(25), b=boss(50))],
    "S05": [T("concentric", "bore concentric with the spacer", a=hole(20), b=boss(40))],
}


def corpus_gold(fx: dict) -> list[dict]:
    o = fx["oracle"]
    out = [T("valid_solid", "valid solid"), T("solid_count", "one solid", count=o.get("solid_count", 1)),
           T("bbox", "overall size", values=o["bbox"]), T("volume", "analytic volume", value=o["volume"], rel_tol=1e-5)]
    for d, n in (o.get("holes") or {}).items():
        out.append(T("hole_count", f"{n} x {float(d):g} holes", count=n, diameter=float(d)))
    if "hole_centers" in o:
        hc = o["hole_centers"]
        out.append(T("hole_positions", "hole centres", diameter=hc["diameter"], points=hc["centers"]))
    return out


def main() -> None:
    tasks = json.loads(TASKS.read_text(encoding="utf-8"))
    gold = {}
    for t in tasks:
        if t["expect"]["outcome"] != "build":
            continue
        assert t["id"] in EXTRA, f"no hand-written tests for {t['id']}"
        gold[t["id"]] = {"prompt": t["prompt"], "tests": number(converted(t) + EXTRA[t["id"]], t["id"])}
    OUT.write_text(json.dumps(gold, indent=1), encoding="utf-8")
    n = sum(len(v["tests"]) for v in gold.values())
    print(f"wrote {n} gold tests for {len(gold)} build tasks to {OUT}")

    corpus = {}
    for path in sorted(CORPUS.glob("*.json")):
        fx = json.loads(path.read_text(encoding="utf-8"))
        base = corpus_gold(fx)
        corpus[fx["id"]] = {"description": fx["description"], "oracle_tests": number(base, fx["id"]),
                            "tests": number(base + CORPUS_EXTRA.get(fx["id"], []), fx["id"])}
    CORPUS_OUT.write_text(json.dumps(corpus, indent=1), encoding="utf-8")
    print(f"wrote corpus gold suites for {len(corpus)} fixtures to {CORPUS_OUT}")


if __name__ == "__main__":
    main()
