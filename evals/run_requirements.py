"""Rescore the 60-task language eval by requirements, not builds (roadmap R1, discipline one and two).

For every task that should build:
  build rate         the agent produced a validated model (what the old headline counted)
  legacy pass        the old scorer: bbox, volume and hole counts against the closed-form oracle
  Pass Rate          every requirement test passes (CADTestBench verdict)
  Requirement Score  fraction of requirement tests passed (a failed build scores 0)
for two suites: hand-authored gold tests (evals/language/gold_tests.json) and tests the
planner model writes from the prompt alone (shilpa/verify/testgen.py). Then both suites
are tested themselves against mutants of the reference parts (mutation score, gate
>= 0.90), plus the 30 corpus fixtures with oracle-derived suites, and gold vs generated
verdicts are compared on real outputs and on mutants.

Run:
  uv run python evals/run_requirements.py --run                     # fresh 60-task language run, then rescore
  uv run python evals/run_requirements.py --report evals/out/language_report_req.json
Options: --no-gen (gold only), --regen (ignore cached generated tests), --workers N, --only L001,L002
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import build123d as bd  # noqa: E402

from shilpa.adapters import build123d_adapter as adapter  # noqa: E402
from shilpa.verify.mutants import evaluate_mutants, make_mutants, mutation_score  # noqa: E402
from shilpa.verify.requirements import aggregate, run_tests  # noqa: E402

HERE = Path(__file__).parent
OUT = HERE / "out"
TASKS = HERE / "language" / "tasks.json"
GOLD = HERE / "language" / "gold_tests.json"
CORPUS = HERE / "corpus"
CORPUS_GOLD = HERE / "corpus_gold_tests.json"
GEN_CACHE = OUT / "generated_tests.json"
SUMMARY_MD = ROOT / "reports" / "R1 requirement scoring.md"


# ------------------------------------------------------------------ generated suites


def _key(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def generated_suites(tasks: list[dict], regen: bool, workers: int = 4) -> dict[str, dict]:
    from shilpa.contracts.errors import ShilpaError
    from shilpa.verify.testgen import generate_tests

    cache = json.loads(GEN_CACHE.read_text(encoding="utf-8")) if GEN_CACHE.exists() and not regen else {}

    def one(t):
        k = _key(t["prompt"])
        if k in cache:  # refusals are cached too; --regen retries them
            return t["id"], cache[k]
        t0 = time.time()
        try:
            res = generate_tests(t["prompt"], prefix=f"{t['id']}-G")
        except ShilpaError as exc:
            res = {"tests": None, "error": f"{exc.code.value}: {exc.info.message}", "usage": {}}
        res["s"] = round(time.time() - t0, 1)
        res["prompt"] = t["prompt"]
        print(f"testgen {t['id']}: {len(res['tests'] or [])} tests {res.get('error') or ''} ({res['s']} s)", flush=True)
        return t["id"], res

    out = {}
    with ThreadPoolExecutor(workers) as pool:
        for tid, res in pool.map(one, tasks):
            out[tid] = res
            cache[_key(res["prompt"]) if "prompt" in res else _key(next(t["prompt"] for t in tasks if t["id"] == tid))] = res
    OUT.mkdir(parents=True, exist_ok=True)
    GEN_CACHE.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    return out


# ------------------------------------------------------------------ per-task work (runs in worker processes)


def _score_task(job: dict) -> dict:
    """Rebuild the agent's recipe, export STEP, run suites on the reimported file, then mutate the reference."""
    tid, recipe, suites, do_mut = job["id"], job["recipe"], job["suites"], job["mutate"]
    work = OUT / "requirements" / tid
    work.mkdir(parents=True, exist_ok=True)
    res: dict = {"id": tid, "suites": {}, "mutation": None}
    step = None
    if recipe is not None:
        b = adapter.build(recipe)
        if b.ok:
            step = work / "model.step"
            bd.export_step(b.shape, str(step))
        else:
            res["rebuild_error"] = b.error.info.message
    for name, tests in suites.items():
        if tests is None:
            res["suites"][name] = None
            continue
        s = run_tests(tests, step)
        res["suites"][name] = s.to_dict()
    if do_mut and recipe is not None and step is not None:
        live = {k: v for k, v in suites.items() if v}
        muts = make_mutants(recipe, seed=int(hashlib.sha256(tid.encode()).hexdigest()[:8], 16))
        ev = evaluate_mutants(recipe, muts, live, work / "mutants")
        for m in ev.get("mutants", []):
            m["task"] = tid
        res["mutation"] = ev
    return res


# ------------------------------------------------------------------ statistics


def kappa(pairs: list[tuple[bool, bool]]) -> dict:
    n = len(pairs)
    if not n:
        return {"n": 0, "agreement": None, "kappa": None}
    agree = sum(a == b for a, b in pairs) / n
    pa, pb = sum(a for a, _ in pairs) / n, sum(b for _, b in pairs) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    k = None if pe >= 1 else (agree - pe) / (1 - pe)
    both = {"both_true": sum(a and b for a, b in pairs), "both_false": sum((not a) and (not b) for a, b in pairs),
            "gold_only": sum(a and not b for a, b in pairs), "gen_only": sum(b and not a for a, b in pairs)}
    return {"n": n, "agreement": round(agree, 4), "kappa": None if k is None else round(k, 4), **both}


class _S:  # minimal SuiteResult view for aggregate()
    def __init__(self, d):
        self.passed, self.score = d["passed"], d["score"]


def suite_stats(rows: list[dict], name: str) -> dict:
    agg = aggregate([_S(r["suites"][name]) if r["suites"].get(name) else None for r in rows])
    by_cat: dict[str, list[int]] = {}
    for r in rows:
        for t in (r["suites"].get(name) or {}).get("results", []):
            c = by_cat.setdefault(t["category"], [0, 0])
            c[0] += t["passed"]
            c[1] += 1
    agg["tests_total"] = sum(len((r["suites"].get(name) or {}).get("results", [])) for r in rows)
    agg["by_category"] = {k: {"passed": a, "total": n, "rate": round(a / n, 4)} for k, (a, n) in sorted(by_cat.items())}
    return agg


# ------------------------------------------------------------------ main


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", action="store_true", help="run evals/run_language.py first (calls the planner)")
    g.add_argument("--report", help="existing language_report*.json to rescore")
    ap.add_argument("--no-gen", action="store_true")
    ap.add_argument("--regen", action="store_true")
    ap.add_argument("--no-mutants", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--only", default="")
    ap.add_argument("--port", type=int, default=8791)
    ap.add_argument("--tag", default="req")
    args = ap.parse_args()
    t_start = time.time()

    if args.run:
        cmd = [sys.executable, str(HERE / "run_language.py"), "--tag", args.tag, "--port", str(args.port)]
        if args.only:
            cmd += ["--only", args.only]
        print("running", " ".join(cmd), flush=True)
        subprocess.run(cmd, cwd=ROOT, check=True)
        report_path = OUT / f"language_report_{args.tag}.json"
    else:
        report_path = Path(args.report)
    lang = json.loads(report_path.read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in lang["tasks"]}

    tasks = [t for t in json.loads(TASKS.read_text(encoding="utf-8")) if t["expect"]["outcome"] == "build"]
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    if only:
        tasks = [t for t in tasks if t["id"] in only]
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    gen = {} if args.no_gen else generated_suites(tasks, args.regen)

    jobs = []
    for t in tasks:
        rec = by_id.get(t["id"], {})
        built = rec.get("outcome") == "build"
        suites = {"gold": gold[t["id"]]["tests"],
                  # Ablation: without the single global volume number, do the per-requirement tests still kill?
                  "gold_no_volume": [x for x in gold[t["id"]]["tests"] if x["kind"] not in ("volume", "mass")]}
        if not args.no_gen:
            suites["generated"] = (gen.get(t["id"]) or {}).get("tests")
        jobs.append({"id": t["id"], "recipe": rec.get("recipe") if built else None, "suites": suites,
                     # The reference for mutation must be a part the closed-form oracle accepted.
                     "mutate": built and rec.get("passed") and not args.no_mutants})
    corpus_jobs = []
    if not args.no_mutants and not only:
        cg = json.loads(CORPUS_GOLD.read_text(encoding="utf-8"))
        for path in sorted(CORPUS.glob("*.json")):
            fx = json.loads(path.read_text(encoding="utf-8"))
            corpus_jobs.append({"id": fx["id"], "recipe": fx["recipe"], "suites": {"oracle": cg[fx["id"]]["oracle_tests"], "gold": cg[fx["id"]]["tests"]}, "mutate": True})

    print(f"scoring {len(jobs)} language tasks and {len(corpus_jobs)} corpus fixtures on {args.workers} workers", flush=True)
    with ProcessPoolExecutor(args.workers) as pool:
        results = list(pool.map(_score_task, jobs + corpus_jobs))
    rows, corpus_rows = results[: len(jobs)], results[len(jobs):]

    task_rows = []
    for t, r in zip(tasks, rows):
        rec = by_id.get(t["id"], {})
        row = {"id": t["id"], "category": t["category"], "split": t["split"], "prompt": t["prompt"],
               "outcome": rec.get("outcome"), "built": rec.get("outcome") == "build", "legacy_pass": bool(rec.get("passed")),
               "suites": r["suites"], "rebuild_error": r.get("rebuild_error")}
        if not args.no_gen:
            gi = gen.get(t["id"]) or {}
            row["testgen"] = {"error": gi.get("error"), "problems": gi.get("problems"), "notes": gi.get("notes"),
                              "usage": gi.get("usage"), "n_tests": len(gi.get("tests") or [])}
        row["mutation"] = r["mutation"]
        task_rows.append(row)
        g_ = r["suites"]["gold"]
        gs = r["suites"].get("generated")
        print(f"{t['id']} {row['outcome'] or '-':10} legacy={'P' if row['legacy_pass'] else 'F'} "
              f"gold={'P' if g_ and g_['passed'] else 'F'} {g_['score'] if g_ else 0:.2f}"
              + ("" if args.no_gen else f"  gen={'P' if gs and gs['passed'] else 'F'} {gs['score'] if gs else 0:.2f}"))

    n = len(task_rows)
    summary: dict = {
        "language_report": str(report_path),
        "tasks_expected_to_build": n,
        "build_rate": round(sum(r["built"] for r in task_rows) / n, 4) if n else None,
        "legacy_pass_rate": round(sum(r["legacy_pass"] for r in task_rows) / n, 4) if n else None,
        "gold": suite_stats(task_rows, "gold"),
    }
    if not args.no_gen:
        summary["generated"] = suite_stats(task_rows, "generated")
        summary["testgen"] = {
            "suites": sum(1 for r in task_rows if r["testgen"]["n_tests"]),
            "errors": {r["id"]: r["testgen"]["error"] for r in task_rows if r["testgen"]["error"]},
            "tests_total": sum(r["testgen"]["n_tests"] for r in task_rows),
            "dropped_invalid": sum(len(r["testgen"]["problems"] or []) for r in task_rows),
            "input_tokens": sum((r["testgen"]["usage"] or {}).get("input_tokens", 0) for r in task_rows),
            "output_tokens": sum((r["testgen"]["usage"] or {}).get("output_tokens", 0) for r in task_rows),
        }
        built = [r for r in task_rows if r["built"] and r["suites"].get("generated")]
        summary["agreement_on_outputs"] = kappa([(r["suites"]["gold"]["passed"], r["suites"]["generated"]["passed"]) for r in built])
        summary["generated_fails_where_gold_passes"] = [r["id"] for r in built if r["suites"]["gold"]["passed"] and not r["suites"]["generated"]["passed"]]

    lang_evals = [r["mutation"] for r in task_rows if r["mutation"]]
    if lang_evals:
        summary["mutation_language_gold"] = mutation_score(lang_evals, "gold")
        summary["mutation_language_gold"]["survivors"] = [f"{m['task']}: {m['description']}" for e in lang_evals for m in e["mutants"]
                                                          if m["status"] == "evaluated" and not m["killed"].get("gold")]
        summary["mutation_language_gold_no_volume"] = mutation_score(lang_evals, "gold_no_volume")
        summary["reference_fails"] = {"gold": [r["id"] for r in task_rows if r["mutation"] and not r["mutation"]["reference_passes"].get("gold", True)]}
        if not args.no_gen:
            # Score generated suites only where they accept the correct reference; a suite that rejects
            # the reference would "kill" everything and inflate the score.
            ok = [r["mutation"] for r in task_rows if r["mutation"] and r["mutation"]["reference_passes"].get("generated")]
            summary["mutation_language_generated"] = mutation_score(ok, "generated")
            summary["mutation_language_generated"]["survivors"] = [f"{m['task']}: {m['description']}" for e in ok for m in e["mutants"]
                                                                   if m["status"] == "evaluated" and not m["killed"].get("generated")]
            summary["mutation_language_generated"]["suites_scored"] = len(ok)
            summary["reference_fails"]["generated"] = [r["id"] for r in task_rows if r["mutation"] and "generated" in r["mutation"]["reference_passes"]
                                                       and not r["mutation"]["reference_passes"]["generated"]]
            pairs = [(m["killed"]["gold"], m["killed"]["generated"]) for e in ok for m in e["mutants"]
                     if m["status"] == "evaluated" and "generated" in m["killed"]]
            summary["agreement_on_mutants"] = kappa(pairs)
    if corpus_rows:
        cev = [r["mutation"] for r in corpus_rows if r["mutation"]]
        for e, r in zip(cev, corpus_rows):
            for m in e["mutants"]:
                m["task"] = r["id"]
        summary["corpus_gold_on_reference"] = aggregate([_S(r["suites"]["gold"]) for r in corpus_rows])
        summary["mutation_corpus_gold"] = mutation_score(cev, "gold")
        summary["mutation_corpus_gold"]["survivors"] = [f"{m['task']}: {m['description']}" for e in cev for m in e["mutants"]
                                                        if m["status"] == "evaluated" and not m["killed"].get("gold")]
        summary["mutation_corpus_oracle"] = mutation_score(cev, "oracle")
    summary["elapsed_s"] = round(time.time() - t_start, 1)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "requirements_report.json").write_text(json.dumps({"summary": summary, "tasks": task_rows, "corpus": corpus_rows},
                                                             indent=1, default=str), encoding="utf-8")
    md = markdown(summary)
    (OUT / "requirements_summary.md").write_text(md, encoding="utf-8")
    if not only:
        SUMMARY_MD.write_text(md, encoding="utf-8")
    print("\n" + md)
    print(f"report: {OUT / 'requirements_report.json'}")
    return 0


def _pct(x) -> str:
    return "-" if x is None else f"{100 * x:.1f}%"


def markdown(s: dict) -> str:
    L = ["# R1 requirement scoring", "",
         f"Language report rescored: `{Path(s['language_report']).name}`; {s['tasks_expected_to_build']} tasks that should build "
         "(the clarify/conflict/unsupported tasks keep their outcome scoring in run_language.py).", "",
         "| Metric | Gold suite | Generated suite |", "|---|---|---|",
         f"| Build rate (old headline) | {_pct(s['build_rate'])} | |",
         f"| Legacy pass (bbox + volume + hole counts) | {_pct(s['legacy_pass_rate'])} | |"]
    gen = s.get("generated") or {}
    L.append(f"| **Pass Rate** (all tests pass) | {_pct(s['gold']['pass_rate'])} | {_pct(gen.get('pass_rate'))} |")
    L.append(f"| **Requirement Score** (mean fraction passed) | {_pct(s['gold']['requirement_score'])} | {_pct(gen.get('requirement_score'))} |")
    L.append(f"| Tests | {s['gold']['tests_total']} | {gen.get('tests_total', '-')} |")
    mg, mx = s.get("mutation_language_gold"), s.get("mutation_language_generated")
    if mg:
        L.append(f"| Mutation score, language references (gate >= 90%) | {_pct(mg['score'])} ({mg['killed']}/{mg['evaluated']}) | "
                 + (f"{_pct(mx['score'])} ({mx['killed']}/{mx['evaluated']}, {mx['suites_scored']} suites)" if mx else "-") + " |")
    mv = s.get("mutation_language_gold_no_volume")
    if mv:
        L.append(f"| Mutation score, language references, gold without volume tests (ablation) | {_pct(mv['score'])} ({mv['killed']}/{mv['evaluated']}) | |")
    mc = s.get("mutation_corpus_gold")
    if mc:
        mo = s["mutation_corpus_oracle"]
        L.append(f"| Mutation score, 30 corpus parts: legacy analytic oracle only | {_pct(mo['score'])} ({mo['killed']}/{mo['evaluated']}) | |")
        L.append(f"| Mutation score, 30 corpus parts: oracle + requirement tests | {_pct(mc['score'])} ({mc['killed']}/{mc['evaluated']}) | |")
    L.append("")
    if s.get("agreement_on_outputs"):
        a, b = s["agreement_on_outputs"], s.get("agreement_on_mutants") or {}
        L += [f"Gold vs generated verdicts: agreement {_pct(a['agreement'])} on the agent's outputs (n={a['n']}, kappa {a['kappa']}); "
              f"{_pct(b.get('agreement'))} on mutants (n={b.get('n')}, kappa {b.get('kappa')}).", ""]
        if s.get("generated_fails_where_gold_passes"):
            L += [f"Generated suites rejecting a part the gold suite accepts: {', '.join(s['generated_fails_where_gold_passes'])}.", ""]
    for name, key in (("Gold", "gold"), ("Generated", "generated")):
        if key == "generated" and s.get("generated") and s.get("mutation_language_generated"):
            pass
        if s.get(key):
            cats = ", ".join(f"{k} {v['passed']}/{v['total']}" for k, v in s[key]["by_category"].items())
            L.append(f"{name} tests passed by category: {cats}.")
    L.append("")
    for label, key in (("gold (language)", "mutation_language_gold"), ("generated (language)", "mutation_language_generated"),
                       ("legacy oracle (corpus)", "mutation_corpus_oracle"), ("gold (corpus)", "mutation_corpus_gold")):
        m = s.get(key)
        if m:
            ops = ", ".join(f"{k} {v['killed']}/{v['evaluated']}" for k, v in m["by_operator"].items())
            L.append(f"Mutants, {label}: {ops}; {m['equivalent']} equivalent and {m['stillborn']} stillborn excluded. "
                     f"Survivors: {len(m['survivors'])}.")
    L += ["", "Reading these numbers:",
          "- A task that should build but produced no geometry (clarification, refusal) scores 0 on both suites. The legacy scorer "
          "accepts a refusal on the injection task; requirement scoring does not, because no part exists.",
          "- Gold suites were strengthened once after the first mutation pass exposed gaps (bore concentricity, row centring, "
          "L-profile face count, per-wall thickness). Their mutation scores are therefore partly in-sample; the generated suites "
          "were never tuned against these mutants.",
          "- Mutants are excluded when they fail to build (the adapter's own preconditions reject them) or are congruent to the "
          "reference in the canonical frame. Mirror mutants of these parts are all equivalent. A rotated bolt circle is only "
          "generated when the recipe states a start angle; when the prompt itself does not, surviving it is correct.",
          "- Kappa is degenerate when one verdict dominates (all outputs pass, nearly all mutants are killed); read the raw "
          "agreement and the gold_only / gen_only counts in the JSON instead.",
          "", f"Elapsed {s['elapsed_s']} s. Full data: `evals/out/requirements_report.json`."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    sys.exit(main())
