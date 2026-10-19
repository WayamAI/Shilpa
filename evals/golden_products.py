"""Golden products: bicycle variants with their outcomes fixed before running (roadmap R5 product suite).

Each case is a request (text for the offline parser, or a choices dict) plus what must happen:

* ``status``: the router outcome (``passed`` first time, ``repaired``, ``unresolved``, ``unsupported``);
* ``size`` / ``wheel``: the template's sizing-table and wheel choice;
* ``first_fail``: checks that must fail on the first build (empty: the first build passes);
* ``warnings``: warning-level checks expected on the final build (exact set);
* ``changes``: skeleton keys the router must change (exact set, order free).

Cases:

- ``xs_650b``: XS road frame on 650b wheels; passes as built.
- ``s_road``: 163 cm rider -> S, 700c; passes, with toe overlap reported as a warning (as on many
  small road bikes with 28 mm tyres).
- ``m_road_text``: "medium road bike for 178 cm rider, 700c" -> M (asked for) though the table says L.
- ``l_gravel``: 180 cm gravel rider -> L gravel geometry, 40 mm tyres.
- ``xl_road``: XL road frame.
- ``xxl_2m``: "bike for a 2 m rider" -> XXL.
- ``s_gravel_650b_45``: "650b gravel bike small rider 45 mm tyres".
- ``bad_road_50mm``: 50 mm tyres on an M road frame designed for 32 mm. The first build must fail
  tyre clearance at the fork crown and the chainstays; the router must design the frameset around a
  50 mm tyre (longer fork, wider stays), go 1x and lengthen the chainstays, then pass.
- ``drone``: "design a drone" is refused as an unsupported product class (no build).

Run:  uv run python evals/golden_products.py [case ...]     (about 3 minutes for all)
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GOLDEN: dict[str, dict] = {
    "xs_650b": {"request": {"frame_size": "XS", "wheel_size": "650b"}, "status": "passed", "size": "XS", "wheel": 584,
                "first_fail": [], "warnings": [], "changes": []},
    "s_road": {"request": {"rider_height_cm": 163}, "status": "passed", "size": "S", "wheel": 622,
               "first_fail": [], "warnings": ["toe_overlap"], "changes": []},
    "m_road_text": {"request": "medium road bike for 178 cm rider, 700c", "status": "passed", "size": "M", "wheel": 622,
                    "first_fail": [], "warnings": [], "changes": []},
    "l_gravel": {"request": {"use_case": "gravel", "rider_height_cm": 180}, "status": "passed", "size": "L", "wheel": 622,
                 "first_fail": [], "warnings": [], "changes": []},
    "xl_road": {"request": {"frame_size": "XL"}, "status": "passed", "size": "XL", "wheel": 622,
                "first_fail": [], "warnings": [], "changes": []},
    "xxl_2m": {"request": "bike for a 2 m rider", "status": "passed", "size": "XXL", "wheel": 622,
               "first_fail": [], "warnings": [], "changes": []},
    "s_gravel_650b_45": {"request": "650b gravel bike small rider 45 mm tyres", "status": "passed", "size": "S", "wheel": 584,
                         "first_fail": [], "warnings": [], "changes": []},
    "bad_road_50mm": {"request": {"frame_size": "M", "tyre_width_mm": 50}, "status": "repaired", "size": "M", "wheel": 622,
                      "first_fail": ["tyre_clearance[front_tyre~fork]", "tyre_clearance[rear_tyre~frame]"],
                      "warnings": ["toe_overlap"],
                      "changes": ["max_tyre_width", "chainrings", "chainline", "chainstay_length"]},
    "drone": {"request": "design a drone", "status": "unsupported"},
}


def run_case(name: str) -> tuple[dict, list[str]]:
    """Run one case through the router (no exports); returns a summary and the differences from golden."""
    from shilpa.product.router import run_with_router
    from shilpa.product.run import resolve_request

    g = GOLDEN[name]
    spec, plan = resolve_request(g["request"])
    if spec is None:
        status = "unsupported" if not plan["supported"] else "rejected"
        errs = [] if status == g["status"] else [f"status {status} != {g['status']}"]
        return {"status": status, "message": plan["message"]}, errs
    r = run_with_router(spec)
    first = r.iterations[0]["failed"]
    final = r.report
    summary = {"status": r.status, "size": r.spec.value("size"), "wheel": r.spec.value("wheel_bsd"), "first_fail": first,
               "warnings": sorted(c.name for c in final.warnings), "changes": [h.param for h in r.spec.history],
               "failed": [c.name for c in final.failed], "seconds": round(r.seconds, 1),
               "checks": {c.name: c.actual for c in final.checks if c.name.startswith(("tyre_", "steering", "crank", "toe"))}}
    errs = []
    for key in ("status", "size", "wheel"):
        if summary[key] != g[key]:
            errs.append(f"{key} {summary[key]!r} != {g[key]!r}")
    product_first = [c for c in first if not c.startswith("assembly")]
    if not set(g["first_fail"]) <= set(product_first) or (not g["first_fail"] and first):
        errs.append(f"first build failed {first}, expected {g['first_fail']}")
    if set(summary["warnings"]) != set(g["warnings"]):
        errs.append(f"warnings {summary['warnings']} != {g['warnings']}")
    if set(summary["changes"]) != set(g["changes"]):
        errs.append(f"router changed {summary['changes']}, expected {g['changes']}")
    return summary, errs


if __name__ == "__main__":
    names = sys.argv[1:] or list(GOLDEN)
    bad = 0
    t_all = time.perf_counter()
    for name in names:
        t0 = time.perf_counter()
        summary, errs = run_case(name)
        bad += bool(errs)
        print(f"{'ok ' if not errs else 'BAD'} {name:18s} {time.perf_counter() - t0:6.1f}s  {summary.get('status')}  "
              f"changes={summary.get('changes', [])} warnings={summary.get('warnings', [])}  {'; '.join(errs)}", flush=True)
        if "checks" in summary:
            print("      " + ", ".join(f"{k}={v}" for k, v in summary["checks"].items()), flush=True)
    print(f"{len(names) - bad}/{len(names)} golden products match ({time.perf_counter() - t_all:.0f} s)")
    sys.exit(1 if bad else 0)
