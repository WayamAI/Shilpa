"""End to end: request -> product spec -> build -> validate -> router -> exports and renders.

    uv run python evals/build_bicycle.py "medium road bike for a 178 cm rider, 700c"   # offline parser
    uv run python evals/build_bicycle.py --llm "gravel bike for a tall rider"          # LLM planner (Azure)
    uv run python evals/build_bicycle.py --choices '{"use_case": "gravel", "wheel_size": "650b"}'
    uv run python evals/build_bicycle.py                                               # default request
    options: --out DIR (default evals/out/bicycle), --no-freecad, --max-iter N

The request is parsed by ``parse_request_offline`` (rules, no model call) unless ``--llm``
is given. All the work is ``shilpa.product.run_product``; this script only finds FreeCAD
and prints a summary. Writes to the output directory:

    bicycle.step            assembly STEP, one named and coloured child per instance
    bom.csv / bom.json      assembly BOM (part number, quantity, source, generator, volume)
    product_bom.json/.csv   BOM joined with the product tree (make / buy / standard, designation, mass)
    assembly.FCStd          FreeCAD 1.x Assembly with native joints (when FreeCAD is available)
    product_spec.json       the final ProductSpec (skeleton with provenance, tree, assembly, history)
    report.json             the full run_product result: checks, router log, paths, timings
    render_side.png, render_iso.png
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_REQUEST = "medium road bike for a 178 cm rider, 700c"


def freecad_env() -> str | None:
    """Point ``SHILPA_FREECAD_CMD`` at a FreeCAD bundle when it is not set.

    A git worktree has no ``tools/`` of its own, so the main checkout's ``tools/freecad`` (a parent
    directory) is used through the environment variable; nothing is linked or copied.
    """
    if os.getenv("SHILPA_FREECAD_CMD"):
        return os.environ["SHILPA_FREECAD_CMD"]
    for base in (ROOT, *ROOT.parents):
        fc = base / "tools" / "freecad"
        if not fc.is_dir():
            continue
        hits = sorted(fc.glob("*/bin/[Ff]ree[Cc][Aa][Dd][Cc]md.exe")) or sorted(fc.glob("**/[Ff]ree[Cc][Aa][Dd][Cc]md.exe"))
        if hits:
            os.environ["SHILPA_FREECAD_CMD"] = str(hits[0])
            return str(hits[0])
    return None


def run(request: str | dict, out: Path, freecad: bool = True, max_iter: int = 4, planner: str = "offline") -> dict:
    from shilpa.product import run_product

    if freecad:
        freecad_env()
    return run_product(request, out, planner=planner, freecad=freecad or False, max_iter=max_iter,
                       log=lambda m: print("  router", m, flush=True))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("request", nargs="?", default=None)
    ap.add_argument("--choices", help="BicycleChoices JSON instead of request text")
    ap.add_argument("--llm", action="store_true", help="use the LLM product planner (needs Azure OpenAI)")
    ap.add_argument("--out", default=str(ROOT / "evals" / "out" / "bicycle"))
    ap.add_argument("--no-freecad", action="store_true")
    ap.add_argument("--max-iter", type=int, default=4)
    a = ap.parse_args(argv)
    req = json.loads(a.choices) if a.choices else (a.request or DEFAULT_REQUEST)
    r = run(req, Path(a.out), freecad=not a.no_freecad, max_iter=a.max_iter, planner="llm" if a.llm else "offline")
    brief = {k: r.get(k) for k in ("status", "product", "message", "freecad", "timings_s", "exports", "renders")}
    if r.get("checks"):
        brief["checks"] = r["checks"]["summary"]
        brief["changes"] = [f"{h['param']}: {h['old']} -> {h['new']} ({h['level']}, {h['check']})" for h in r["router"]["history"]]
        brief["unresolved"] = r["router"]["unresolved"]
    print(json.dumps(brief, indent=1, default=str))
    return 0 if r["status"] in ("passed", "repaired") else 1


if __name__ == "__main__":
    sys.exit(main())
