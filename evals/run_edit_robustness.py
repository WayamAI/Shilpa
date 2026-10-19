"""Edit robustness of selections: heuristic selectors vs persistent named references (IR 1.2).

Every corpus part with a selection (fillet / chamfer edges, shell open faces, hole entry
sides) is edited (lengths x0.75 / 0.9 / 1.1 / 1.3, counts +/-1) and rebuilt twice: as
written, and with each heuristic selector replaced by the named reference that selects
the same entities at nominal size. See shilpa/topology/robustness.py for the scoring.

The corpus mostly fillets base geometry before any cut, where heuristics are safe, so a
few stress probes add treatments after the cuts (chamfered hole entries, a filleted
pocket floor) the way an engineer edits a finished part.

Run:  uv run python evals/run_edit_robustness.py [--only P01,F01] [--out evals/out]
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shilpa.topology.robustness import run  # noqa: E402

CORPUS = Path(__file__).parent / "corpus"


def _probe(fid: str, op: str, size_param: str, size: float, selector: dict) -> callable:
    def make(recipe: dict) -> dict:
        r = copy.deepcopy(recipe)
        r["parameters"][size_param] = size
        body = r["features"][-1]["id"]
        size_key = "radius_ref" if op == "fillet" else "distance_ref"
        r["features"].append({"id": fid, "op": op, "body_ref": body, size_key: size_param, "edges": selector})
        r.pop("output", None)
        r["assertions"] = {"solid_count": 1, "valid_brep": True}
        return r
    return make


# Stress probes: (name, corpus base, transform). Treatments after cuts are where heuristics break.
PROBES = [
    ("P01+entry_chamfer", "P01", _probe("entry_break", "chamfer", "brk", 0.5,
                                        {"curve": "circle", "location": "top", "boundary": "inner", "expected_count": 4})),
    ("F01+entry_chamfer", "F01", _probe("entry_break", "chamfer", "brk", 0.3,
                                        {"curve": "circle", "location": "top", "boundary": "inner", "expected_count": 5})),
    ("P03+entry_chamfer", "P03", _probe("entry_break", "chamfer", "brk", 0.5,
                                        {"curve": "circle", "location": "top", "boundary": "inner", "expected_count": 6})),
    ("P03+exit_chamfer", "P03", _probe("exit_break", "chamfer", "brk", 0.5,
                                       {"curve": "circle", "location": "bottom", "expected_count": 6})),
    ("N06+entry_chamfer", "N06", _probe("entry_break", "chamfer", "brk", 0.3,
                                        {"curve": "circle", "location": "top", "boundary": "inner", "expected_count": 4})),
    ("E01+floor_fillet", "E01", _probe("floor_round", "fillet", "floor_r", 1.0,
                                       {"direction": "perpendicular_z", "location": "between", "boundary": "inner",
                                        "expected_count": 4})),
    ("B02+inner_fillet", "B02", _probe("inner_round", "fillet", "inner_r", 3.0,
                                       {"direction": "perpendicular_z", "location": "between", "curve": "line",
                                        "boundary": "inner", "expected_count": 1})),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--out", default=str(Path(__file__).parent / "out"))
    args = ap.parse_args()
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    cases = []
    for path in sorted(CORPUS.glob("*.json")):
        fx = json.loads(path.read_text(encoding="utf-8"))
        cases.append((fx["id"], fx["recipe"]))
    corpus = dict(cases)
    cases += [(name, make(corpus[base])) for name, base, make in PROBES]

    rows, tot = [], {"feasible": 0, "heuristic_ok": 0, "named_ok": 0, "edits": 0}
    t_all = time.perf_counter()
    for cid, recipe in cases:
        if only and cid not in only and cid.split("+")[0] not in only:
            continue
        t0 = time.perf_counter()
        try:
            r = run(recipe)
        except Exception as exc:  # a probe whose heuristic is wrong at nominal size, etc.
            print(f"SKIP {cid}: {exc}")
            continue
        if not r["selections"]:
            continue
        for k in tot:
            tot[k] += r[k]
        r["id"] = cid
        rows.append(r)
        print(f"{cid:20} edits {r['feasible']:3}/{r['edits']:3} feasible   heuristic {r['heuristic_ok']:3}   named {r['named_ok']:3}"
              f"   ({time.perf_counter() - t0:.1f} s)")
        for o in r["outcomes"]:
            if o["heuristic"] not in ("ok", "infeasible") or o["named"] not in ("ok", "infeasible"):
                print(f"    {o['edit']:18} heuristic={o['heuristic']:15} named={o['named']:15} {'; '.join(o['notes'])[:220]}")
    f = max(tot["feasible"], 1)
    print(f"\n{len(rows)} parts, {tot['feasible']} feasible edits of {tot['edits']}: "
          f"heuristic {tot['heuristic_ok']}/{tot['feasible']} = {tot['heuristic_ok'] / f:.3f}, "
          f"named {tot['named_ok']}/{tot['feasible']} = {tot['named_ok'] / f:.3f}  ({time.perf_counter() - t_all:.0f} s)")
    Path(args.out).mkdir(parents=True, exist_ok=True)
    report = {**tot, "heuristic_score": round(tot["heuristic_ok"] / f, 4), "named_score": round(tot["named_ok"] / f, 4),
              "parts": rows}
    (Path(args.out) / "edit_robustness.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
