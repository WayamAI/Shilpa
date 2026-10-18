"""R1 readiness scorecard: every available metric in one table, mapped to the roadmap's R1 gates.

Reads the latest results in evals/out (or --results-dir); nothing calls the planner. External
benchmarks that have not been run are listed as "not yet run", never estimated. Gates are the
roadmap's proposals ("A five-level readiness ladder with numeric gates"), not external standards.

Run:  uv run python evals/readiness.py [--refresh-corpus] [--results-dir DIR ...] [--json evals/out/readiness.json]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).parent / "out"


def _latest(dirs: list[Path], pattern: str) -> Path | None:
    found = [p for d in dirs for p in d.glob(pattern) if p.is_file()]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def _load(p: Path | None) -> dict | None:
    return json.loads(p.read_text(encoding="utf-8")) if p else None


def _frac(s: str | None) -> float | None:
    if not s or "/" not in str(s):
        return None
    a, b = str(s).split("/")
    return int(a) / int(b) if int(b) else None


def row(metric, value, gate, status, source, kind="internal") -> dict:
    return {"kind": kind, "metric": metric, "value": value, "gate": gate, "status": status, "source": source}


def _gate(value: float | None, ok: bool | None) -> str:
    if value is None:
        return "no data"
    return "met" if ok else "not met"


def collect(dirs: list[Path]) -> list[dict]:
    rows: list[dict] = []

    # --- external benchmarks (R1 row) -------------------------------------------------------
    from evals.external.cadtestbench import status as ctb_status

    ctb = ctb_status()
    note = f"data {'downloaded' if ctb['downloaded'] else 'not downloaded'}; {ctb['licence']}"
    rows.append(row("CADTestBench Pass Rate, abstract prompts", None, ">= 0.80 (best published 0.81)", "not yet run", note, "external"))
    rows.append(row("CADTestBench Pass Rate, detailed prompts", None, ">= 0.65 (best published 0.625)", "not yet run", note, "external"))
    rows.append(row("CADTestBench invalid rate", None, "< 2%", "not yet run", note, "external"))
    rows.append(row("Text2CAD-Bench L1 / L2 IoU", None, ">= 0.62 / >= 0.50", "not yet run", "benchmark not released", "external"))

    # --- internal suites -----------------------------------------------------------------------
    req_p = _latest(dirs, "requirements_report.json")
    req = _load(req_p)
    if req:
        s = req["summary"]
        src = req_p.name
        rows.append(row("Language eval: build rate (retired headline)", s["build_rate"], "reported only", "info", src))
        rows.append(row("Language eval: requirement Pass Rate, gold tests", s["gold"]["pass_rate"], ">= 0.80 (aligned with CADTestBench abstract gate)",
                        _gate(s["gold"]["pass_rate"], s["gold"]["pass_rate"] >= 0.80), src))
        rows.append(row("Language eval: Requirement Score, gold tests", s["gold"]["requirement_score"], "reported", "info", src))
        if s.get("generated"):
            rows.append(row("Language eval: requirement Pass Rate, model-written tests", s["generated"]["pass_rate"], "reported", "info", src))
        for key, label in (("mutation_language_gold", "Mutation score, gold language suites"),
                           ("mutation_language_generated", "Mutation score, model-written suites"),
                           ("mutation_corpus_gold", "Mutation score, corpus suites"),
                           ("mutation_corpus_oracle", "Mutation score, legacy corpus oracle")):
            m = s.get(key)
            if m and m.get("score") is not None:
                rows.append(row(label, m["score"], ">= 0.90 before trusting a suite", _gate(m["score"], m["score"] >= 0.90), src))
        if s.get("agreement_on_mutants"):
            a = s["agreement_on_mutants"]
            rows.append(row("Gold vs model-written verdict agreement on mutants (kappa)", a["kappa"], "reported", "info", src))
    else:
        rows.append(row("Language eval rescored as requirement Pass Rate", None, ">= 0.80", "not yet run",
                        "run evals/run_requirements.py"))

    lang_p = _latest(dirs, "language_report*.json")
    lang = _load(lang_p)
    if lang:
        s = lang["summary"]
        v = s["g2_supported_completion_all"]["rate"]
        rows.append(row("Language eval G2 supported completion (legacy scorer)", v, "reported", "info", lang_p.name))
        rows.append(row("Language eval unsafe builds (should not build, did)", len(s.get("unsafe_builds", [])), "0",
                        _gate(0, not s.get("unsafe_builds")), lang_p.name))

    corp_p = _latest(dirs, "corpus_report.json")
    corp = _load(corp_p)
    if corp:
        v = corp["passed"] / corp["total"] if corp["total"] else None
        rows.append(row("Golden parts built and oracle-validated", f"{corp['passed']}/{corp['total']}", "30 golden parts, all pass",
                        _gate(v, corp["total"] >= 30 and corp["passed"] == corp["total"]), corp_p.name))
    else:
        rows.append(row("Golden parts built and oracle-validated", None, "30/30", "not yet run", "run evals/run_corpus.py"))

    rows.append(row("Xometry text-to-CAD prompts verified dimensionally", None, "3/3", "not yet run",
                    "prompts not yet in the eval set (xometry.pro/en/articles/text-to-cad-tools-test/)"))

    # --- adjacent evidence (R3 drawings, FreeCAD round trips) reported for context ----------------
    dr_p = _latest(dirs, "drawing_report*.json")
    dr = _load(dr_p)
    if dr:
        s = dr["summary"]
        rows.append(row("Drawing eval end-to-end builds (R3 context)", s.get("end_to_end_build"), ">= 200 drawings, >= 98% dims (R3)",
                        "info", dr_p.name))
        rows.append(row("Drawing eval mean value recall (R3 context)", s.get("mean_value_recall"), ">= 0.98 (R3)",
                        "info", dr_p.name))  # R3 gate; shown for context, not counted toward R1
    fc_p = _latest([d / "freecad" for d in dirs], "report.json")
    fc = _load(fc_p)
    if fc:
        nb, ne = sum(b["ok"] for b in fc["builds"]), sum(e["ok"] for e in fc["edits"])
        rows.append(row("FreeCAD native builds of golden parts (R3 context)", f"{nb}/{len(fc['builds'])}", "every golden part", "info", "freecad/report.json"))
        rows.append(row("FreeCAD reopen-and-edit round trips (R3 context)", f"{ne}/{len(fc['edits'])}", "every golden part (R3)", "info", "freecad/report.json"))
    else:
        rows.append(row("FreeCAD reopen-and-edit round trips", None, "every golden part (R3)", "not yet run", "run evals/run_freecad.py (needs FreeCAD)"))

    # --- disciplines -----------------------------------------------------------------------------
    rows.append(row("VLM judge calibration against engineer labels", None, "advisory only; r and kappa reported", "not yet run", "no judge yet"))
    rows.append(row("Field metrics: first-pass acceptance, edits and minutes to accept", None, "set from pilot baselines", "not yet run",
                    "needs Wayam pilot"))
    return rows


def render(rows: list[dict]) -> str:
    def fmt(v):
        if v is None:
            return "-"
        if isinstance(v, float):
            return f"{v:.3f}"
        return str(v)

    lines = ["# R1 readiness scorecard (simple prismatic and turned parts)", "",
             "| | Metric | Value | Gate | Status | Source |", "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['kind']} | {r['metric']} | {fmt(r['value'])} | {r['gate']} | {r['status']} | {r['source']} |")
    gated = [r for r in rows if r["status"] in ("met", "not met", "not yet run")]
    met = sum(r["status"] == "met" for r in gated)
    lines += ["", f"R1 gates met: {met}/{len(gated)} (gates not yet run count as unmet). "
              "R1 is reached only when every gate, internal and external, is met."]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", action="append", default=[])
    ap.add_argument("--refresh-corpus", action="store_true", help="re-run evals/run_corpus.py first (about 5 s, no network)")
    ap.add_argument("--json", default=str(OUT / "readiness.json"))
    args = ap.parse_args()
    dirs = [Path(d) for d in args.results_dir] or [OUT]
    if args.refresh_corpus:
        subprocess.run([sys.executable, str(Path(__file__).parent / "run_corpus.py"), "--out", str(dirs[0])], cwd=ROOT,
                       check=False, stdout=subprocess.DEVNULL)
    rows = collect(dirs)
    md = render(rows)
    print(md)
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps({"rows": rows}, indent=2), encoding="utf-8")
    (Path(args.json).with_suffix(".md")).write_text(md, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
