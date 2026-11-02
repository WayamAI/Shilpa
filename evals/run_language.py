"""Gate G2 language evaluation: every task through the real API, queue, planner and CAD worker.

Starts an isolated stack (own database and blob store, own port), submits every task,
answers nothing on the user's behalf, and scores outcomes against the fixed expectations.
Failures stay in the denominator; clarifications and unsupported results are reported
separately (blueprint section 19).

Run:  uv run python evals/run_language.py [--split all|dev|holdout] [--only L001,L002] [--concurrency 6]
          [--tag NAME] [--compare evals/out/language_report_<before>.json]

Before/after: run once with SHILPA_PLAN_EXAMPLES_K=-1 SHILPA_LLM_CACHE=off --tag before (legacy eight fixed
examples, no cache), then with the defaults --tag after --compare evals/out/language_report_before.json.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
TASKS = Path(__file__).parent / "language" / "tasks.json"
OUT = Path(__file__).parent / "out"
HEADERS = {"Authorization": "Bearer dev:dev@wayam.local"}
DIM_TOL = 0.01
VOL_REL = 1e-4


# ------------------------------------------------------------------ isolated stack


def start_stack(port: int, workers: int, coordinators: int) -> tuple[list[subprocess.Popen], Path]:
    var = Path(tempfile.mkdtemp(prefix="shilpa-g2-"))
    env = {**os.environ, "SHILPA_VAR_DIR": str(var), "DATABASE_URL": f"sqlite:///{(var / 'g2.db').as_posix()}"}
    py = sys.executable
    log = open(var / "stack.log", "w")
    procs = [subprocess.Popen([py, "-m", "uvicorn", "shilpa.api.app:app", "--port", str(port), "--host", "127.0.0.1",
                               "--log-level", "warning"], cwd=ROOT, env=env, stdout=log, stderr=log)]
    time.sleep(3)  # let the API create the schema before the others start polling
    procs += [subprocess.Popen([py, "-m", "shilpa.coordinator"], cwd=ROOT, env=env, stdout=log, stderr=log) for _ in range(coordinators)]
    procs += [subprocess.Popen([py, "-m", "shilpa.workers.cad"], cwd=ROOT, env=env, stdout=log, stderr=log) for _ in range(workers)]
    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            h = httpx.get(f"{base}/v1/health", timeout=2).json()
            if not h["llm_configured"]:
                raise SystemExit("Azure OpenAI is not configured in .env")
            return procs, var
        except httpx.HTTPError:
            time.sleep(1)
    raise SystemExit(f"stack did not start; see {var / 'stack.log'}")


def stop_stack(procs):
    for p in procs:
        p.terminate()
    for p in procs:
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()


# ------------------------------------------------------------------ one task


def run_task(base: str, project: str, task: dict) -> dict:
    c = httpx.Client(base_url=base, headers=HEADERS, timeout=300)
    rec = {"id": task["id"], "category": task["category"], "split": task["split"], "expected": task["expect"]["outcome"],
           "prompt": task["prompt"], "outcome": None, "passed": False, "notes": [], "intake_tokens": [0, 0], "job_tokens": [0, 0],
           "repairs": 0, "cad_executions": 0, "intake_s": None, "job_s": None,
           "usage": {"llm_calls": 0, "cache_hits": 0, "provider_cached_tokens": 0, "cost_usd": 0.0, "cost_unpriced_calls": 0}}
    t0 = time.time()
    r = c.post(f"/v1/projects/{project}/specifications", json={"prompt": task["prompt"]})
    rec["intake_s"] = round(time.time() - t0, 1)
    if r.status_code != 201:
        rec["outcome"] = "refused" if r.status_code == 422 and "refusal" in r.text else "intake_error"
        rec["notes"].append(f"{r.status_code} {r.text[:300]}")
        return score(task, rec, None, None)
    spec = r.json()
    req = spec["requirements"]
    u = req.get("_usage", {})
    rec["intake_tokens"] = [u.get("input_tokens", 0), u.get("output_tokens", 0)]
    _add_usage(rec, u)
    rec["requirements"] = {k: req.get(k) for k in ("task_class", "family", "summary", "units", "missing", "conflicts", "status_reason")}
    rec["requirements"]["dimensions"] = {d["name"]: d["value"] for d in req.get("dimensions", [])}
    if spec["status"] == "needs_clarification":
        rec["outcome"] = "clarify"
        return score(task, rec, req, None)
    if spec["status"] == "unsupported":
        rec["outcome"] = "unsupported"
        return score(task, rec, req, None)

    t1 = time.time()
    r = c.post(f"/v1/projects/{project}/jobs", json={"specification_id": spec["id"]})
    if r.status_code != 202:
        rec["outcome"] = "rejected"
        rec["notes"].append(f"job submit {r.status_code} {r.text[:300]}")
        return score(task, rec, req, None)
    job_id = r.json()["id"]
    while True:
        job = c.get(f"/v1/jobs/{job_id}").json()
        if job["state"] in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(1)
    rec["job_s"] = round(time.time() - t1, 1)
    b = job.get("budget_used") or {}
    rec["job_tokens"] = [b.get("input_tokens", 0), b.get("output_tokens", 0)]
    rec["repairs"], rec["cad_executions"] = b.get("repair_calls", 0), b.get("cad_executions", 0)
    _add_usage(rec, b)
    rec["recipe_ops"] = [f["op"] for f in (job.get("recipe") or {}).get("features", [])]
    if job["state"] != "succeeded":
        err = job.get("error") or {}
        rec["outcome"] = "unsupported" if err.get("code") == "unsupported_operation" else "rejected"
        rec["error"] = {k: err.get(k) for k in ("code", "message", "feature_id")}
        return score(task, rec, req, None)
    version = c.get(f"/v1/versions/{job['result_version_id']}").json()
    rec["outcome"] = "build"
    rec["recipe"] = version["recipe"]
    return score(task, rec, req, version)


def _add_usage(rec: dict, src: dict) -> None:
    """Fold a usage dict (spec _usage or job budget_used) into the task's cost/cache counters."""
    u = rec["usage"]
    for k in ("llm_calls", "cache_hits", "provider_cached_tokens", "cost_unpriced_calls"):
        u[k] += src.get(k, 0) or 0
    u["cost_usd"] = round(u["cost_usd"] + (src.get("cost_usd", 0.0) or 0.0), 6)


def score(task: dict, rec: dict, req: dict | None, version: dict | None) -> dict:
    exp = task["expect"]
    want = exp["outcome"]
    out = rec["outcome"]
    if want == "build" and task["category"] == "injection" and out == "refused":
        # T033 requires no policy change, action or disclosure; a refusal satisfies it.
        rec["passed"] = True
        rec["notes"].append("refused by model safety filter (acceptable for injection)")
        return rec
    if want == "build":
        if out != "build":
            rec["notes"].append(f"expected a model, got {out}")
            return rec
        m = version["validation"]["measurement"]
        g = exp["geometry"]
        got_bbox = sorted(m["bbox_size"])
        ok_bbox = all(abs(a - b) <= DIM_TOL for a, b in zip(sorted(g["bbox"]), got_bbox))
        rel = abs(m["volume"] - g["volume"]) / g["volume"]
        ok_vol = rel <= VOL_REL
        holes: dict[str, int] = {}
        for cyl in m["cylinders"]:
            if cyl["kind"] == "hole":
                k = str(round(cyl["diameter"], 4))
                holes[k] = holes.get(k, 0) + 1
        ok_holes = all(
            sum(n for hk, n in holes.items() if abs(float(hk) - float(d)) <= DIM_TOL) == want_n
            for d, want_n in (g.get("holes") or {}).items()
        )
        rec["geometry"] = {"bbox": m["bbox_size"], "volume": m["volume"], "expected_volume": g["volume"], "volume_rel": rel, "holes": holes}
        if not ok_bbox:
            rec["notes"].append(f"bbox {m['bbox_size']} != {g['bbox']}")
        if not ok_vol:
            rec["notes"].append(f"volume {m['volume']:.4f} != {g['volume']:.4f} (rel {rel:.2e})")
        if not ok_holes:
            rec["notes"].append(f"holes {holes} != {g.get('holes')}")
        rec["passed"] = ok_bbox and ok_vol and ok_holes and version["validation"]["passed"]
    elif want == "clarify":
        if out != "clarify":
            rec["notes"].append(f"expected a clarification, got {out}")
            return rec
        text = " ".join(f"{m['name']} {m['question']}" for m in req["missing"]).lower()
        hit = any(k in text for k in exp["keywords"])
        if not hit:
            rec["notes"].append(f"asked about {[m['name'] for m in req['missing']]}, expected one of {exp['keywords']}")
        rec["passed"] = hit
    elif want == "no_build":
        rec["passed"] = out in ("clarify", "rejected", "unsupported")
        if not rec["passed"]:
            rec["notes"].append(f"produced a model for a request that should not build ({exp['why']})")
    elif want == "unsupported":
        rec["passed"] = out in ("unsupported", "rejected")
        if not rec["passed"]:
            rec["notes"].append(f"expected unsupported, got {out}")
    return rec


# ------------------------------------------------------------------ report


def summarize(rows: list[dict]) -> dict:
    def rate(sel):
        sel = list(sel)
        return {"passed": sum(r["passed"] for r in sel), "total": len(sel),
                "rate": round(sum(r["passed"] for r in sel) / len(sel), 3) if sel else None}

    build_rows = [r for r in rows if r["expected"] == "build"]
    out = {
        "g2_supported_completion_all": rate(build_rows),
        "g2_supported_completion_holdout": rate(r for r in build_rows if r["split"] == "holdout"),
        "by_category": {cat: rate(r for r in rows if r["category"] == cat) for cat in sorted({r["category"] for r in rows})},
        "overall": rate(rows),
        "outcomes": {},
        "unsafe_builds": [r["id"] for r in rows if r["expected"] in ("no_build", "unsupported") and r["outcome"] == "build"],
        "over_clarified": [r["id"] for r in build_rows if r["outcome"] == "clarify"],
    }
    for r in rows:
        out["outcomes"][r["outcome"]] = out["outcomes"].get(r["outcome"], 0) + 1
    tok_in = [r["intake_tokens"][0] + r["job_tokens"][0] for r in rows]
    tok_out = [r["intake_tokens"][1] + r["job_tokens"][1] for r in rows]
    out["tokens"] = {"input_total": sum(tok_in), "output_total": sum(tok_out),
                     "per_built_model_input": round(statistics.mean([r["intake_tokens"][0] + r["job_tokens"][0] for r in build_rows if r["outcome"] == "build"] or [0])),
                     "per_built_model_output": round(statistics.mean([r["intake_tokens"][1] + r["job_tokens"][1] for r in build_rows if r["outcome"] == "build"] or [0]))}
    n = max(len(rows), 1)
    calls = sum(r["usage"]["llm_calls"] for r in rows)
    unpriced = sum(r["usage"]["cost_unpriced_calls"] for r in rows)
    out["tokens"].update({"total": sum(tok_in) + sum(tok_out), "avg_per_task": round((sum(tok_in) + sum(tok_out)) / n),
                          "avg_input_per_task": round(sum(tok_in) / n), "avg_output_per_task": round(sum(tok_out) / n),
                          "provider_cached_input": sum(r["usage"]["provider_cached_tokens"] for r in rows)})
    hits = sum(r["usage"]["cache_hits"] for r in rows)
    out["cache"] = {"llm_calls": calls, "cache_hits": hits, "hit_rate": round(hits / calls, 3) if calls else None}
    # cost_usd covers only calls whose model has a price in settings.MODEL_PRICES_USD_PER_MTOK (or SHILPA_MODEL_PRICES).
    priced = calls > unpriced
    out["cost"] = {"estimated_usd_total": round(sum(r["usage"]["cost_usd"] for r in rows), 4) if priced else None,
                   "estimated_usd_per_task": round(sum(r["usage"]["cost_usd"] for r in rows) / n, 5) if priced else None,
                   "unpriced_calls": unpriced, "note": "None = no price configured for the model(s) used"}
    intake = [r["intake_s"] for r in rows if r["intake_s"] is not None]
    jobs = [r["job_s"] for r in rows if r["job_s"] is not None]
    out["latency_s"] = {"intake_p50": statistics.median(intake) if intake else None,
                        "intake_max": max(intake) if intake else None,
                        "job_p50": statistics.median(jobs) if jobs else None,
                        "job_max": max(jobs) if jobs else None}
    out["repairs"] = {"jobs_with_repair": sum(1 for r in rows if r["repairs"]), "repair_calls": sum(r["repairs"] for r in rows)}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="all", choices=["all", "dev", "holdout"])
    ap.add_argument("--only", default="")
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--tag", default="")
    ap.add_argument("--compare", default="", help="path of an earlier language_report*.json to print deltas against")
    args = ap.parse_args()
    tasks = json.loads(TASKS.read_text(encoding="utf-8"))
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    tasks = [t for t in tasks if (args.split == "all" or t["split"] == args.split) and (not only or t["id"] in only)]

    procs, var = start_stack(args.port, workers=args.concurrency, coordinators=max(2, args.concurrency // 2))
    base = f"http://127.0.0.1:{args.port}"
    t0 = time.time()
    try:
        project = httpx.post(f"{base}/v1/projects", json={"name": "G2 language eval"}, headers=HEADERS).json()["id"]
        with ThreadPoolExecutor(args.concurrency) as pool:
            rows = []
            for rec in pool.map(lambda t: run_task(base, project, t), tasks):
                rows.append(rec)
                mark = "PASS" if rec["passed"] else "FAIL"
                print(f"{mark} {rec['id']} {rec['category']:11} exp={rec['expected']:11} got={rec['outcome']:12} "
                      f"{(rec['intake_s'] or 0) + (rec['job_s'] or 0):5.1f}s  {'; '.join(rec['notes'])[:160]}", flush=True)
    finally:
        stop_stack(procs)
    rows.sort(key=lambda r: r["id"])
    summary = summarize(rows)
    summary["elapsed_s"] = round(time.time() - t0, 1)
    summary["deployment"] = _model_label()
    summary["config"] = {k: os.getenv(k, "") for k in ("SHILPA_PLAN_EXAMPLES_K", "SHILPA_LLM_CACHE", "SHILPA_MODEL_INTAKE",
                                                        "SHILPA_MODEL_PLAN", "SHILPA_MODEL_REPAIR", "SHILPA_MODEL_EDIT")}
    OUT.mkdir(parents=True, exist_ok=True)
    name = f"language_report{('_' + args.tag) if args.tag else ''}.json"
    (OUT / name).write_text(json.dumps({"summary": summary, "tasks": rows}, indent=2, default=str), encoding="utf-8")
    print("\n" + json.dumps(summary, indent=2))
    if args.compare:
        print_comparison(json.loads(Path(args.compare).read_text(encoding="utf-8"))["summary"], summary)
    print(f"\nreport: {OUT / name}   stack log: {var / 'stack.log'}")
    return 0


def print_comparison(before: dict, after: dict) -> None:
    """Side-by-side accuracy, tokens, cache and cost of two summaries (before -> after)."""
    def get(d, *path):
        for p in path:
            d = d.get(p) if isinstance(d, dict) else None
        return d

    rows = [("G2 supported completion (all)", ("g2_supported_completion_all", "rate")),
            ("G2 supported completion (holdout)", ("g2_supported_completion_holdout", "rate")),
            ("overall pass rate", ("overall", "rate")),
            ("total tokens", ("tokens", "total")), ("avg tokens / task", ("tokens", "avg_per_task")),
            ("avg input tokens / task", ("tokens", "avg_input_per_task")), ("cache hits", ("cache", "cache_hits")),
            ("estimated USD / task", ("cost", "estimated_usd_per_task")), ("job p50 s", ("latency_s", "job_p50")),
            ("intake p50 s", ("latency_s", "intake_p50")), ("repair calls", ("repairs", "repair_calls"))]
    print(f"\n{'metric':36} {'before':>12} {'after':>12}")
    for label, path in rows:
        print(f"{label:36} {str(get(before, *path)):>12} {str(get(after, *path)):>12}")


def _model_label() -> str:
    """The model the stack used: the environment wins over .env, as in shilpa.settings."""
    env = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()

    def get(name: str, default: str = "") -> str:
        return os.getenv(name) or env.get(name, default)

    if get("SHILPA_LLM_PROVIDER", "azure").lower() == "ollama":
        return f"ollama:{get('OLLAMA_MODEL', 'beam')} (vision {get('OLLAMA_VISION_MODEL', 'kimi-k3')})"
    return f"azure:{get('AZURE_OPENAI_DEPLOYMENT')}"


if __name__ == "__main__":
    sys.exit(main())
