"""FreeCAD adapter acceptance (backlog B030/B031, workbook T070).

1. Build all 30 golden recipes as native FreeCAD documents. Each must pass the analytic
   oracle and match the build123d solid (volume and bounding box).
2. Edit round trip: open selected FCStd files, change a parameter in the Params sheet,
   recompute, save, reopen, and compare with a fresh build123d build of the edited recipe.

Run:  uv run python evals/run_freecad.py [--only P01,F03] [--skip-edits]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shilpa.adapters import freecad_adapter  # noqa: E402
from shilpa.agent.planner import apply_parameter_edit  # noqa: E402
from shilpa.contracts.errors import ShilpaError  # noqa: E402
from shilpa.pipeline import execute  # noqa: E402
from shilpa.validators import geometry  # noqa: E402

CORPUS = Path(__file__).parent / "corpus"
OUT = Path(__file__).parent / "out" / "freecad"

# (fixture, parameter, new value): a dimension an engineer would plausibly change in FreeCAD.
EDITS = [
    ("P01", "width", 100.0),        # corner holes must follow the new edge (bbox-driven expressions)
    ("P04", "corner_radius", 8.0),  # fillet radius
    ("P03", "pitch_x", 45.0),       # linear pattern pitch
    ("F01", "pitch_diameter", 76.0),
    ("F03", "hub_length", 30.0),    # hub pad and the through bore
    ("B03", "height", 60.0),        # L bracket leg, with inner fillet
    ("B04", "thickness", 12.0),
    ("H02", "l2", 50.0),            # revolution profile
    ("E02", "wall", 3.0),           # pocket with rounded inner corners
    ("E04", "top_chamfer", 2.0),
    # IR 1.1 operations
    ("N01", "groove_depth", 8.0),   # revolved profile vertex expressions
    ("N02", "bend_radius", 50.0),   # sweep spine with a tangent arc
    ("N04", "wall", 4.0),           # Thickness on a ruled loft
    ("N07", "port_z", 8.0),         # tapped side hole position
    ("N08", "half_length", 36.0),   # mirrored whole shape
    ("N09", "spokes", 8.0),         # polar pattern occurrences
    ("N10", "pitch", 28.0),         # linear pattern spacing and the matching hole row
    ("N12", "module", 2.5),         # 160-segment gear outline scales with the module
    ("N13", "cross_x", 14.0),       # intersecting side drillings
    ("N14", "slot_y", 18.0),        # mirrored cut tool
    ("N15", "sweep", 120.0),        # partial revolve angle
]


def build_one(fx: dict) -> dict:
    recipe = {**fx["recipe"], "exports": ["STEP", "FCSTD"]}
    t0 = time.perf_counter()
    res = execute(recipe, OUT / fx["id"], oracle=fx["oracle"])
    checks = (res.validation or {}).get("checks", [])
    failed = [f"{c['name']}: {c.get('note') or c.get('actual')}" for c in checks if not c["passed"]]
    fc = [c for c in checks if c["name"].startswith("freecad")]
    return {"id": fx["id"], "ok": res.ok and bool(fc), "s": round(time.perf_counter() - t0, 1),
            "failed": failed or ([res.error.message] if res.error else []), "freecad_checks": len(fc)}


def edit_one(fid: str, param: str, value: float) -> dict:
    fx = json.loads((CORPUS / f"{fid}.json").read_text(encoding="utf-8"))
    src = OUT / fid / "model.FCStd"
    out = OUT / f"{fid}_edit"
    if not src.exists():
        return {"id": fid, "ok": False, "failed": ["source FCStd missing"]}
    t0 = time.perf_counter()
    try:
        res = freecad_adapter.edit_fcstd(src, {param: value}, out)
    except ShilpaError as exc:  # e.g. a FreeCAD timeout: report it as a failed row, keep going
        return {"id": fid, "edit": f"{param} = {value:g}", "ok": False, "failed": [exc.info.message]}
    if not res.get("ok"):
        return {"id": fid, "ok": False, "failed": [json.dumps(res.get("error"))[:400]]}
    # Reference: build123d build of the same edit, independently validated.
    ref = execute({**apply_parameter_edit(fx["recipe"], {param: value}), "exports": ["STEP"]}, out / "reference")
    if not ref.ok:
        return {"id": fid, "ok": False, "failed": [f"reference build failed: {ref.error.message}"]}
    want = ref.validation["measurement"]
    got = geometry.measure(__import__("build123d").import_step(str(out / "edited.step")))
    rel = abs(got.volume - want["volume"]) / want["volume"]
    bbox_ok = all(abs(a - b) <= geometry.DIM_TOL for a, b in zip(got.bbox_size, want["bbox_size"]))
    holes_ok = geometry.hole_groups(got) == {float(k): v for k, v in _holes(want).items()}
    failed = []
    if rel > 1e-6:
        failed.append(f"volume {got.volume:.4f} != {want['volume']:.4f}")
    if not bbox_ok:
        failed.append(f"bbox {got.bbox_size} != {want['bbox_size']}")
    if not holes_ok:
        failed.append(f"holes {geometry.hole_groups(got)} != {_holes(want)}")
    if not res.get("reopen_ok"):
        failed.append("reopened document did not recompute cleanly")
    return {"id": fid, "edit": f"{param} = {value:g}", "ok": not failed, "failed": failed, "volume": got.volume,
            "s": round(time.perf_counter() - t0, 1)}


def _holes(m: dict) -> dict:
    out: dict[float, set] = {}
    for c in m["cylinders"]:
        if c["kind"] == "hole":
            out.setdefault(round(c["diameter"], 4), set()).add((tuple(c["axis"]), tuple(c["center"])))
    return {d: len(s) for d, s in out.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--skip-edits", action="store_true")
    ap.add_argument("--jobs", type=int, default=4)
    args = ap.parse_args()
    if not freecad_adapter.available():
        print("FreeCAD not found (tools/freecad or SHILPA_FREECAD_CMD)")
        return 2
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    fixtures = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(CORPUS.glob("*.json"))]
    fixtures = [f for f in fixtures if not only or f["id"] in only]
    t0 = time.time()
    with ThreadPoolExecutor(args.jobs) as pool:
        builds = list(pool.map(build_one, fixtures))
    for b in builds:
        print(f"{'PASS' if b['ok'] else 'FAIL'}  build {b['id']:4} {b['s']:5.1f}s  " + "; ".join(b["failed"])[:300])
    edits = []
    if not args.skip_edits:
        todo = [e for e in EDITS if not only or e[0] in only]
        with ThreadPoolExecutor(args.jobs) as pool:
            edits = list(pool.map(lambda e: edit_one(*e), todo))
        for e in edits:
            print(f"{'PASS' if e['ok'] else 'FAIL'}  edit  {e['id']:4} {e.get('edit', ''):24} " + "; ".join(e["failed"])[:300])
    nb, ne = sum(b["ok"] for b in builds), sum(e["ok"] for e in edits)
    print(f"\nnative builds {nb}/{len(builds)}, edit round trips {ne}/{len(edits)}  ({time.time() - t0:.0f} s)")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.json").write_text(json.dumps({"builds": builds, "edits": edits}, indent=2), encoding="utf-8")
    return 0 if nb == len(builds) and ne == len(edits) else 1


if __name__ == "__main__":
    sys.exit(main())
