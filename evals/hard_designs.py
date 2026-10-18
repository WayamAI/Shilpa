"""Hard design probes: edge-of-envelope parts with outcomes fixed before running.

Oracles are closed-form. Run through the real stack via run_language's task runner.

Run:  uv run python evals/hard_designs.py
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

# ------------------------------------------------------------------ must refuse (no operation exists)
refuse("X07", "keyway needs a side-cut slot", "Stepped shaft Ø25 x 40 then Ø20 x 60 with a 6 mm wide, 3.5 mm deep keyway along the Ø20 section.")
refuse("X08", "gusset rib needs a triangular profile", "L bracket 80 wide, 60 deep, 60 tall, 6 mm thick, with a 45° triangular gusset rib 6 mm thick in the middle of the inside corner.")
refuse("X09", "cross hole is not along Z", "Shaft Ø20 x 80 mm with a Ø6 cross hole drilled straight through the diameter, 10 mm from the top end.")
refuse("X10", "two separate parts in one request", "Make an L bracket 60 x 50 x 50 x 6 mm and, as a separate loose part, a washer OD 20 ID 10 thickness 2.")

# ------------------------------------------------------------------ judgement: standard reference with no dimensions given
no_build("X11", "standard flange: dimensions come from a standard table, which must not be silently invented",
         "4 inch ASME B16.5 class 150 slip-on flange.")
no_build("X12", "impossible: hub larger than the flange", "Hub flange Ø80 x 10 disc with a Ø100 hub 20 tall on top and a Ø30 bore.")


def main() -> int:
    procs, var = start_stack(8769, workers=5, coordinators=3)
    base = "http://127.0.0.1:8769"
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
