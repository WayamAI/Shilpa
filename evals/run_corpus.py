"""Build every golden recipe and report measured geometry (blueprint section 4.1, gate G1).

Run:  uv run python evals/run_corpus.py [--only P01,F03] [--out evals/out]
Exit code is non-zero unless every fixture passes.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shilpa.pipeline import execute  # noqa: E402

CORPUS = Path(__file__).parent / "corpus"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--out", default=str(Path(__file__).parent / "out"))
    args = ap.parse_args()
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    files = sorted(CORPUS.glob("*.json"))
    if not files:
        print("no fixtures; run evals/make_corpus.py first")
        return 2

    rows, passed = [], 0
    t_all = time.perf_counter()
    for path in files:
        fx = json.loads(path.read_text(encoding="utf-8"))
        if only and fx["id"] not in only:
            continue
        t0 = time.perf_counter()
        res = execute(fx["recipe"], Path(args.out) / fx["id"], oracle=fx["oracle"])
        ms = (time.perf_counter() - t0) * 1000
        m = (res.validation or {}).get("measurement") or {}
        failed = [c["name"] for c in (res.validation or {}).get("checks", []) if not c["passed"]]
        status = "PASS" if res.ok else "FAIL"
        passed += res.ok
        rows.append({
            "id": fx["id"], "family": fx["family"], "status": status, "ms": round(ms),
            "solids": m.get("solid_count"), "bbox": m.get("bbox_size"), "volume": m.get("volume"),
            "expected_volume": fx["oracle"]["volume"],
            "error": None if res.ok else (res.error.message if res.error else ", ".join(failed)),
            "exports": [a.format for a in res.artifacts],
        })
        bbox = "x".join(f"{v:g}" for v in m.get("bbox_size", [])) or "-"
        vol = f"{m['volume']:.4f}" if m.get("volume") is not None else "-"
        print(f"{status}  {fx['id']:4} {fx['family']:9} {bbox:>16}  V={vol:>14}  (oracle {fx['oracle']['volume']:.4f})  {ms:6.0f} ms"
              + ("" if res.ok else f"\n      -> {rows[-1]['error']}"))

    total = len(rows)
    elapsed = time.perf_counter() - t_all
    print(f"\n{passed}/{total} fixtures passed in {elapsed:.1f} s")
    report = {"passed": passed, "total": total, "elapsed_s": round(elapsed, 2), "fixtures": rows}
    Path(args.out).mkdir(parents=True, exist_ok=True)
    (Path(args.out) / "corpus_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if passed == total and total > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
