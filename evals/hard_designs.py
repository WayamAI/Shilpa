"""Hard design probes: edge-of-envelope parts with outcomes fixed before running.

Oracles are closed-form. Run through the real stack via run_language's task runner.

Run:  uv run python evals/hard_designs.py [port]
"""

from __future__ import annotations

import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_language import HEADERS, run_task, start_stack, stop_stack  # noqa: E402

PI = math.pi
IN = 25.4


def c(d):
    return PI * d * d / 4


def ring_chamfer(r, ch):
    return 2 * PI * (r - ch / 3) * ch * ch / 2


def concave_fillet_ring(r_corner, f):
    """Material added by a concave fillet of radius f around a circular junction of radius r_corner (Pappus)."""
    area = f * f * (1 - PI / 4)
    centroid = f * (10 - 3 * PI) / (12 - 3 * PI)  # distance of the fillet region's centroid from the corner
    return 2 * PI * (r_corner + centroid) * area


TASKS = []


def build(id, why, prompt, bbox, volume, holes=None):
    g = {"bbox": [round(v, 6) for v in bbox], "volume": round(volume, 6)}
    if holes:
        g["holes"] = {str(round(k, 4)): v for k, v in holes.items()}
    TASKS.append({"id": id, "category": "hard_build", "split": "hard", "why": why, "prompt": prompt, "expect": {"outcome": "build", "geometry": g}})


def refuse(id, why, prompt):
    TASKS.append({"id": id, "category": "hard_refuse", "split": "hard", "why": why, "prompt": prompt, "expect": {"outcome": "unsupported"}})


def no_build(id, why, prompt):
    TASKS.append({"id": id, "category": "hard_judgement", "split": "hard", "why": why, "prompt": prompt, "expect": {"outcome": "no_build", "why": why}})


# ------------------------------------------------------------------ hard but buildable
outer = (150 * 100 - (4 - PI) * 36) * 40
build("X01", "internal bosses: union of offset cylinders on the pocket floor, positioned from inner walls",
      "Electronics enclosure 150 x 100 x 40 mm, open top, 2.5 mm walls, 3 mm floor, R6 rounded outer vertical corners and "
      "sharp inner corners. Add four Ø8 mm solid mounting bosses, 10 mm tall, standing on the inside floor, each centred "
      "15 mm in from the two nearest inner walls.",
      (150, 100, 40), outer - 145 * 95 * 37 + 4 * c(8) * 10)

build("X02", "four different hole features plus corner rounds on one plate",
      "Base plate 200 x 120 x 10 mm with R8 rounded vertical corners. Four Ø9 through holes 12 mm from the edges, a Ø40 "
      "through bore in the centre, and six Ø6.6 through holes equally spaced on a Ø70 bolt circle around the bore, first hole on +X.",
      (200, 120, 10), (200 * 120 - (4 - PI) * 64 - 4 * c(9) - c(40) - 6 * c(6.6)) * 10, {9: 4, 40: 1, 6.6: 6})

hub_v = c(160) * 14 + c(80) * 30 - c(50) * 44 - 8 * c(11) * 14 + concave_fillet_ring(40, 3) - ring_chamfer(40, 2)
build("X03", "fillet and chamfer on circular edges that share z-levels with bolt holes and the bore (selector stress)",
      "Hub flange: Ø160 x 14 mm disc, a Ø80 hub 30 mm tall on top, a Ø50 bore through everything, eight Ø11 through holes "
      "on a Ø125 bolt circle in the disc, an R3 fillet where the hub meets the disc, and a 2 mm x 45° chamfer on the top outer edge of the hub.",
      (160, 160, 44), hub_v, {11: 8, 50: 1})

build("X04", "holes in a pocket floor: only buildable if holes are drilled before the pocket",
      "Plate 100 x 60 x 8 mm with a 40 x 20 mm rectangular pocket 4 mm deep in the centre of the top face, and four Ø5 "
      "through holes in the pocket floor, each 5 mm in from the pocket's sides at its corners.",
      (100, 60, 8), 100 * 60 * 8 - 40 * 20 * 4 - 4 * c(5) * 4, {5: 4})

build("X05", "imperial flange with fractional sizes",
      "Flange, 6 inch OD, 3/4 inch thick, 2-1/2 inch bore, four 1/2 inch bolt holes on a 4-3/4 inch bolt circle.",
      (6 * IN, 6 * IN, 0.75 * IN), (c(6 * IN) - c(2.5 * IN) - 4 * c(0.5 * IN)) * 0.75 * IN, {0.5 * IN: 4, 2.5 * IN: 1})

build("X06", "redundant but consistent dimensions must not be flagged as a conflict",
      "Plate 100 x 50 x 10 mm with four Ø6 through holes 10 mm from each edge; hole spacing is 80 mm along the length and 30 mm across.",
      (100, 50, 10), 100 * 50 * 10 - 4 * c(6) * 10, {6: 4})

def bicylinder(r, big, n=4000):
    """Common volume of perpendicular cylinders with intersecting axes, the thinner passing fully through."""
    f = lambda t: r * r * math.cos(t) ** 2 * math.sqrt(big * big - (r * math.sin(t)) ** 2)  # noqa: E731
    h = (PI / 2) / n
    return 8 * h / 3 * (f(0) + f(PI / 2) + sum((4 if i % 2 else 2) * f(i * h) for i in range(1, n)))


# IR 1.1 made the cross hole buildable: a through hole entering the shaft's curved side.
build("X09", "cross hole enters a curved face: hole from x_max through a round shaft",
      "Shaft Ø20 x 80 mm with a Ø6 cross hole drilled straight through the diameter, 10 mm from the top end.",
      (20, 20, 80), c(20) * 80 - bicylinder(3, 10), {6: 1})


def pappus(pts):
    a = cx = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        k = x0 * y1 - x1 * y0
        a += k / 2
        cx += (x0 + x1) * k
    return 2 * PI * (cx / (6 * a)) * abs(a)


csk_d, csk_D = 6.6, 13.44  # M6: ISO 273 medium clearance, ISO 10642 head
csk_h = (csk_D - csk_d) / 2
build("X13", "revolved half-section with a V groove (profile + revolve)",
      "V-belt pulley: 100 mm outside diameter, 24 mm wide, 15 mm bore. One V groove centred in the width, 16 mm wide at "
      "the rim, 9 mm wide at the bottom and 11 mm deep.",
      (100, 100, 24), pappus([(7.5, 0), (50, 0), (50, 4), (39, 7.5), (39, 16.5), (50, 20), (50, 24), (7.5, 24)]), {15: 1})
build("X14", "ISO countersink lookup from a screw size",
      "Mounting plate 120 x 80 x 10 mm with four M6 countersunk holes 12 mm from each edge and a 40 mm through bore in the centre.",
      (120, 80, 10), 120 * 80 * 10 - c(40) * 10 - 4 * (c(csk_d) * (10 - csk_h) + PI * csk_h / 12 * (csk_D ** 2 + csk_D * csk_d + csk_d ** 2)),
      {6.6: 4, 40: 1})
build("X15", "swept ring section along a smooth path with a bend radius",
      "Bent tube, 25 mm OD with a 2 mm wall: 80 mm straight up, then a 90 degree bend on a 50 mm centreline radius, then 120 mm straight.",
      (182.5, 25, 142.5), (c(25) - c(21)) * (80 + PI * 50 / 2 + 120))
build("X16", "shell with rounded corners (inner corner radius follows)",
      "Electronics enclosure 150 x 100 x 50 mm with R10 rounded vertical corners, shelled to 2 mm walls, open at the top.",
      (150, 100, 50), (150 * 100 - (4 - PI) * 100) * 50 - (146 * 96 - (4 - PI) * 64) * 48)
build("X17", "helical sweep with free length as the overall length",
      "Compression spring: 1.5 mm wire, 16 mm mean coil diameter, 6 mm pitch, 30 mm long.",
      (17.5, 17.5, 30), c(1.5) * 2 * PI * 8 * (28.5 / 6))
build("X18", "intersecting drillings from two faces (manifold)",
      "Manifold block 80 x 50 x 50 mm. A 12 mm bore runs right through along the 80 mm length at mid-height and mid-width, "
      "and a 10 mm hole is drilled through from the top at the centre so the two passages intersect.",
      (80, 50, 50), 80 * 50 * 50 - c(12) * 80 - c(10) * 50 + bicylinder(5, 6))

# ------------------------------------------------------------------ must refuse (no operation exists)
refuse("X07", "keyway needs a side-cut slot", "Stepped shaft Ø25 x 40 then Ø20 x 60 with a 6 mm wide, 3.5 mm deep keyway along the Ø20 section.")
refuse("X10", "two separate parts in one request", "Make an L bracket 60 x 50 x 50 x 6 mm and, as a separate loose part, a washer OD 20 ID 10 thickness 2.")
refuse("X19", "gear teeth: the planner must not invent involute geometry (the IR can hold it; see corpus N12)",
       "Spur gear, module 2, 20 teeth, 20 degree pressure angle, 10 mm face width, 10 mm bore.")

# ------------------------------------------------------------------ judgement: standard reference with no dimensions given
no_build("X11", "standard flange: dimensions come from a standard table, which must not be silently invented",
         "4 inch ASME B16.5 class 150 slip-on flange.")
no_build("X12", "impossible: hub larger than the flange", "Hub flange Ø80 x 10 disc with a Ø100 hub 20 tall on top and a Ø30 bore.")
no_build("X08", "a profile can make the gusset, but its leg size is not given and must be asked",
         "L bracket 80 wide, 60 deep, 60 tall, 6 mm thick, with a 45° triangular gusset rib 6 mm thick in the middle of the inside corner.")


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8769  # pick a free port when other stacks are running
    procs, var = start_stack(port, workers=5, coordinators=3)
    base = f"http://127.0.0.1:{port}"
    try:
        project = httpx.post(f"{base}/v1/projects", json={"name": "Hard designs"}, headers=HEADERS).json()["id"]
        with ThreadPoolExecutor(5) as pool:
            rows = list(pool.map(lambda t: run_task(base, project, t), TASKS))
    finally:
        stop_stack(procs)
    for t, r in zip(TASKS, rows):
        print(f"{'PASS' if r['passed'] else 'FAIL'} {r['id']} exp={r['expected']:11} got={r['outcome']:12} | {t['why']}")
        detail = "; ".join(r["notes"]) or ""
        if r.get("error"):
            detail += f" [{r['error'].get('code')}: {(r['error'].get('message') or '')[:160]}]"
        if r["outcome"] == "clarify":
            detail += " asked: " + "; ".join(m["question"] for m in (r.get("requirements") or {}).get("missing", []))[:220]
        if r["outcome"] == "unsupported":
            detail += f" reason: {(r.get('requirements') or {}).get('status_reason') or ''}"[:200]
        if detail:
            print("      " + detail)
        if r.get("recipe_ops"):
            print("      ops: " + " ".join(r["recipe_ops"]))
    out = Path(__file__).parent / "out" / "hard_designs.json"
    out.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    print(f"\n{sum(r['passed'] for r in rows)}/{len(rows)} as expected   report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
