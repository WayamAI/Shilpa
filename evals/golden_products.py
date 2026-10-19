"""Golden products: bicycles and gearboxes with their outcomes fixed before running (roadmap R5 product suite).

Each case is a request (text for the offline parser, or a choices dict) plus what must happen:

* ``status``: the router outcome (``passed`` first time, ``repaired``, ``unresolved``, ``unsupported``);
* ``size`` / ``wheel``: the bicycle template's sizing-table and wheel choice (bicycles only);
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

Gearboxes (``gearbox.spur_single_v1``), outcomes from the sizing rules in the template docstring:

- ``gb_small``: 3:1 at 1 N.m; the bending-sized m1 gears also pass contact, so the first build passes.
- ``gb_10nm``: 3:1 at 10 N.m; contact (Hertz) fails at the standard 10 m face, the router widens it.
- ``gb_4to1_text``: "4:1 gearbox, 20 Nm input at 1500 rpm"; contact needs more than a 16 m face, so the
  module steps up (design), the input 6001 bearing falls short of 10 000 h (62xx, part), then the face widens.
- ``gb_close_bores``: 2:1 hardened at 5 N.m; m1 puts the shafts 25.5 mm apart, closer than the two
  bearing housings allow, so the plates cannot even be built; the router steps the module (design).
- ``gb_motor``: "speed reducer from 1450 rpm to 360 rpm output, 2.2 kW motor, 20k hours": ratio (4.03)
  and torque (14.5 N.m) come from the motor data; contact needs more than a 16 m face, so the module steps up.
- ``gb_overload``: 6:1 at 100 N.m: the 600 N.m output needs a shaft beyond the 40 mm bearings the
  template stocks, so it ends unresolved after the repairs that do exist.
- ``gb_planetary``: "planetary gearbox 10:1" is refused (only single-stage spur).

Run:  uv run python evals/golden_products.py [case ...]     (about 5 minutes for all)
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
    "gb_small": {"request": "3:1 gearbox, 1 Nm input at 1500 rpm", "status": "passed", "first_fail": [], "warnings": [],
                 "changes": []},
    "gb_10nm": {"request": {"product_class": "gearbox", "ratio": 3, "input_torque_nm": 10}, "status": "repaired",
                "first_fail": ["tooth_contact"], "warnings": [], "changes": ["face_width"]},
    "gb_4to1_text": {"request": "4:1 gearbox, 20 Nm input at 1500 rpm", "status": "repaired",
                     "first_fail": ["tooth_contact", "bearing_life_in"], "warnings": [],
                     "changes": ["module", "bearing_series_in", "face_width"]},
    "gb_close_bores": {"request": {"product_class": "gearbox", "ratio": 2, "input_torque_nm": 5,
                                   "gear_material": "hardened_steel", "life_hours": 30000},
                       "status": "repaired", "first_fail": ["bearing_spacing", "tooth_contact"], "warnings": [],
                       "changes": ["module", "face_width"]},
    "gb_motor": {"request": "speed reducer from 1450 rpm to 360 rpm output, 2.2 kW motor, 20k hours",
                 "status": "repaired", "first_fail": ["tooth_contact"], "warnings": [], "changes": ["module"]},
    "gb_overload": {"request": {"product_class": "gearbox", "ratio": 6, "input_torque_nm": 100, "input_rpm": 3000,
                                "life_hours": 20000},
                    "status": "unresolved", "first_fail": ["tooth_contact", "bearing_life_in", "shaft_torsion_out"],
                    "warnings": [], "changes": ["module", "bearing_series_in", "face_width", "shaft_d_in"]},
    "gb_planetary": {"request": "planetary gearbox 10:1", "status": "unsupported"},
}

GEARBOX_KEYS = ("pinion_teeth", "gear_teeth", "module", "face_width", "shaft_d_in", "shaft_d_out", "bearing_in",
                "bearing_out")


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
    summary = {"status": r.status, "first_fail": first,
               "warnings": sorted(c.name for c in final.warnings), "changes": [h.param for h in r.spec.history],
               "failed": [c.name for c in final.failed], "seconds": round(r.seconds, 1)}
    if r.spec.template.startswith("gearbox."):
        summary["checks"] = {k: r.spec.value(k) for k in GEARBOX_KEYS}
    else:
        summary.update(size=r.spec.value("size"), wheel=r.spec.value("wheel_bsd"),
                       checks={c.name: c.actual for c in final.checks
                               if c.name.startswith(("tyre_", "steering", "crank", "toe"))})
    errs = []
    for key in ("status", "size", "wheel"):
        if key in g and summary.get(key) != g[key]:
            errs.append(f"{key} {summary.get(key)!r} != {g[key]!r}")
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
