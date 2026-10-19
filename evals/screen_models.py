"""Screen every Ollama Cloud model on Shilpa's real planner steps (intake, plan, build, validate).

Each model runs in its own process (``OLLAMA_MODEL`` set before import) over the same small
task set: five parts that must build to the right size, one request that must ask for a
missing dimension, and one that must be refused as unsupported. A task passes only on the
expected outcome (and, for builds, a valid solid of the expected bounding box). Reports
pass count, repairs, time and tokens per model.

Run:  uv run python evals/screen_models.py [model ...]   (default: every model the key lists)
      uv run python evals/screen_models.py --one MODEL   (internal: one model, JSON on stdout)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).parent / "out"

TASKS = [
    ("plate", "Mounting plate 80 x 40 x 8 mm with four 6 mm through holes, 10 mm from each edge.", "build", (8, 40, 80)),
    ("flange", "A flange, 120 mm outside diameter, 15 mm thick, 50 mm bore, six M10 clearance holes (11 mm) on a 90 mm "
               "bolt circle.", "build", (15, 120, 120)),
    ("bracket", "L bracket, 60 wide, 50 deep, 50 tall, 6 mm thick, with a 4 mm fillet on the inside corner.", "build",
     (50, 50, 60)),
    ("box", "Open-top box 100 by 60 by 40 mm with 3 mm walls and floor.", "build", (40, 60, 100)),
    ("shaft", "Shaft 200 mm long, 20 mm diameter, with a 16 mm diameter step 10 mm long at one end and 1 mm chamfers on "
              "both ends.", "build", (20, 20, 200)),
    ("spacer", "Steel spacer with 20 mm OD and 10 mm ID.", "clarify", None),
    ("blade", "A turbine blade with a twisted aerofoil profile.", "unsupported", None),
]


def run_one() -> dict:
    sys.path.insert(0, str(ROOT))
    from shilpa.agent import planner
    from shilpa.agent.llm import Budget
    from shilpa.contracts.errors import ShilpaError
    from shilpa.pipeline import execute
    from shilpa.settings import settings

    rows = []
    for name, prompt, expect, bbox in TASKS:
        b = Budget(input_tokens=80000, output_tokens=16000, deadline=time.time() + 300)
        t0 = time.time()
        row = {"task": name, "expect": expect, "outcome": None, "passed": False, "note": ""}
        try:
            req = planner.extract_requirements(prompt, b)
            status = req["status"]
            if status == "unsupported":
                row["outcome"] = "unsupported"
            elif status != "ready":
                row["outcome"] = "clarify"
            else:
                recipe = planner.check_recipe(planner.plan_recipe(req, b))
                recipe.pop("_change_summary", None)
                res = execute(recipe, Path(tempfile.mkdtemp(prefix="shilpa-screen-")))
                m = (res.validation or {}).get("measurement") or {}
                got = tuple(sorted(round(x, 1) for x in (m.get("bbox_size") or [])))
                row["outcome"] = "build" if res.ok else "build_failed"
                row["bbox"] = got
                if res.ok and bbox and not all(abs(a - e) <= 0.5 for a, e in zip(got, bbox)):
                    row["outcome"], row["note"] = "wrong_size", f"bbox {got} != {bbox}"
                if not res.ok and res.error:
                    row["note"] = res.error.message[:160]
        except ShilpaError as e:
            row["outcome"], row["note"] = f"error:{e.code.value}", e.info.message[:160]
        except Exception as e:  # noqa: BLE001 - a screen reports every failure
            row["outcome"], row["note"] = "crash", f"{type(e).__name__}: {str(e)[:160]}"
        row["passed"] = row["outcome"] == expect
        row["seconds"] = round(time.time() - t0, 1)
        row["tokens_in"], row["tokens_out"] = b.used_input, b.used_output
        row["repairs"] = sum("(repair)" in c["purpose"] for c in b.calls)
        rows.append(row)
    return {"model": settings.ollama_model, "rows": rows}


def screen(model: str) -> dict:
    env = {**os.environ, "SHILPA_LLM": "on", "SHILPA_LLM_PROVIDER": "ollama", "OLLAMA_MODEL": model,
           "OLLAMA_TIMEOUT_S": "180"}
    t0 = time.time()
    p = subprocess.run([sys.executable, __file__, "--one"], env=env, capture_output=True, text=True, timeout=3600)
    try:
        data = json.loads(p.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {"model": model, "rows": [], "error": (p.stderr or p.stdout)[-400:], "seconds": round(time.time() - t0)}
    data["seconds"] = round(time.time() - t0)
    return data


def models() -> list[str]:
    import httpx
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    r = httpx.get("https://ollama.com/api/tags", headers={"Authorization": f"Bearer {os.environ['OLLAMA_API_KEY']}"},
                  timeout=30)
    return [m["name"] for m in r.json()["models"]]


def main() -> int:
    if sys.argv[1:2] == ["--one"]:
        print(json.dumps(run_one(), default=str))
        return 0
    names = sys.argv[1:] or models()
    print(f"screening {len(names)} models x {len(TASKS)} tasks", flush=True)
    results = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for res in pool.map(screen, names):
            rows = res["rows"]
            passed = sum(r["passed"] for r in rows)
            secs = sum(r["seconds"] for r in rows)
            tin, tout = sum(r["tokens_in"] for r in rows), sum(r["tokens_out"] for r in rows)
            reps = sum(r["repairs"] for r in rows)
            res["summary"] = {"passed": passed, "of": len(TASKS), "task_seconds": round(secs, 1), "tokens_in": tin,
                              "tokens_out": tout, "repairs": reps}
            fails = [f"{r['task']}={r['outcome']}" for r in rows if not r["passed"]]
            print(f"{res['model']:28} {passed}/{len(TASKS)}  {secs:6.1f}s  in={tin:6d} out={tout:5d} repairs={reps}  "
                  f"{'; '.join(fails) or ''}{res.get('error', '')[:120]}", flush=True)
            results.append(res)
    OUT.mkdir(exist_ok=True)
    path = OUT / f"model_screen_{time.strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    print(f"report: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
