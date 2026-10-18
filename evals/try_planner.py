"""Live planner smoke test against the configured Azure OpenAI deployment.

Run:  uv run python evals/try_planner.py ["prompt" ...]
"""

import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shilpa.agent import planner  # noqa: E402
from shilpa.agent.llm import Budget  # noqa: E402
from shilpa.contracts.errors import ShilpaError  # noqa: E402
from shilpa.pipeline import execute  # noqa: E402

PROMPTS = [
    "Mounting plate 80 x 40 x 8 mm with four 6 mm through holes, 10 mm from each edge.",
    "A flange, 120 mm outside diameter, 15 mm thick, 50 mm bore, six M10 clearance holes (11 mm) on a 90 mm bolt circle.",
    "L bracket, 60 wide, 50 deep, 50 tall, 6 mm thick, with a 4 mm fillet on the inside corner.",
    "Steel spacer with 20 mm OD and 10 mm ID.",
    "Open-top box 100 by 60 by 40 mm with 3 mm walls and floor.",
    "A turbine blade with a twisted aerofoil profile.",
]


def run(prompt: str) -> None:
    print("=" * 100)
    print("PROMPT:", prompt)
    b = Budget(input_tokens=60000, output_tokens=12000, deadline=time.time() + 600)
    t0 = time.time()
    try:
        req = planner.extract_requirements(prompt, b)
    except ShilpaError as e:
        print("  intake error:", e)
        return
    dims = ", ".join(f"{d['name']}={d['value']}" for d in req["dimensions"])
    print(f"  intake [{time.time()-t0:.1f}s] status={req['status']} family={req['family']} units={req['units']}  {dims}")
    for m in req["missing"]:
        print("   ? ", m["name"], "-", m["question"], "(critical)" if m["critical"] else "")
    if req["status"] != "ready":
        return
    t1 = time.time()
    try:
        recipe = planner.check_recipe(planner.plan_recipe(req, b))
    except ShilpaError as e:
        print("  plan error:", e)
        return
    recipe.pop("_change_summary", None)
    print(f"  plan [{time.time()-t1:.1f}s] ops: {[f['op'] for f in recipe['features']]}")
    res = execute(recipe, Path(tempfile.mkdtemp(prefix="shilpa-live-")))
    m = (res.validation or {}).get("measurement") or {}
    holes = [round(c["diameter"], 3) for c in m.get("cylinders", []) if c["kind"] == "hole"]
    print(f"  build ok={res.ok} bbox={m.get('bbox_size')} volume={m.get('volume')} holes={holes}")
    if not res.ok:
        print("  error:", res.error.message if res.error else "")
        print(json.dumps(recipe, indent=1)[:2500])
    print(f"  tokens in={b.used_input} out={b.used_output}")


if __name__ == "__main__":
    for p in (sys.argv[1:] or PROMPTS):
        run(p)
