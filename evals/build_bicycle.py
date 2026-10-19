"""End to end: prompt -> product spec -> build -> validate -> router -> exports and renders.

    uv run python evals/build_bicycle.py "design a medium road bike for a 178 cm rider with 700c wheels"
    uv run python evals/build_bicycle.py --choices '{"use_case": "gravel", "wheel_size": "650b"}'   # no LLM
    uv run python evals/build_bicycle.py --offline          # default choices, no LLM
    options: --out DIR (default evals/out/bicycle), --no-freecad, --max-iter N

Writes to the output directory:
    bicycle.step            assembly STEP, one named and coloured child per instance
    bom.csv / bom.json      assembly BOM (part number, quantity, source, generator, volume)
    product_bom.json/.csv   BOM joined with the product tree (make / buy / standard, designation, mass)
    assembly.FCStd          FreeCAD 1.x Assembly with native joints (when FreeCAD is available)
    product_spec.json       the final ProductSpec (skeleton with provenance, tree, assembly, history)
    report.json             product checks, assembly checks, router iterations and timings
    render_side.png, render_three_quarter.png
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _freecad_env() -> None:
    """In a git worktree the FreeCAD bundle lives in the main checkout's tools/ folder."""
    if os.getenv("SHILPA_FREECAD_CMD"):
        return
    for base in (ROOT, *ROOT.parents):
        hits = sorted((base / "tools" / "freecad").glob("**/[Ff]ree[Cc][Aa][Dd][Cc]md.exe")) if (base / "tools").exists() else []
        if hits:
            os.environ["SHILPA_FREECAD_CMD"] = str(hits[0])
            return


def product_bom(spec, build) -> list[dict]:
    from shilpa.contracts.assembly import part_number
    from shilpa.validators.assembly import bill_of_materials

    leaf_of = {iid: leaf for leaf in spec.tree.leaves() for iid in leaf.instances}
    rows = []
    for line in bill_of_materials(build):
        leaf = leaf_of.get(line["instances"][0])
        part = build.parts.get(line["instances"][0])
        meta = part.meta if part else {}
        rows.append({
            "part_number": line["part_number"], "quantity": line["quantity"],
            "procurement": leaf.procurement if leaf else None, "tree_node": leaf.id if leaf else None,
            "description": leaf.name if leaf else None, "standard": (leaf.standard if leaf else None) or meta.get("standard"),
            "designation": meta.get("designation") or meta.get("template"), "source": line["source"],
            "generator": line["generator"], "mass_g": meta.get("mass_g"), "volume_mm3": line["volume_mm3"],
            "instances": line["instances"],
        })
    assert all(part_number(spec.assembly, i) for r in rows for i in r["instances"])
    return rows


def run(prompt: str | None, choices: dict | None, out: Path, freecad: bool = True, max_iter: int = 4, steps: int = 9) -> dict:
    from shilpa.assembly.export import export_fcstd, export_step, write_bom
    from shilpa.product.render import render
    from shilpa.product.router import run_with_router
    from shilpa.product.templates.bicycle import BicycleChoices, bicycle_spec

    out.mkdir(parents=True, exist_ok=True)
    timings, summary = {}, {"prompt": prompt}
    t0 = time.perf_counter()
    if choices is None and prompt:
        from shilpa.agent.product_planner import plan_product

        res = plan_product(prompt)
        summary["planner"] = res.to_dict()
        timings["plan"] = round(time.perf_counter() - t0, 1)
        if not res.supported or res.choices is None:
            summary["status"] = "unsupported" if not res.supported else "planner_rejected"
            summary["message"] = res.message
            (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
            print(res.message)
            return summary
        bc = res.choices
    else:
        bc = BicycleChoices.model_validate({**(choices or {}), "text": prompt or ""})
    t = time.perf_counter()
    spec = bicycle_spec(bc)
    timings["spec"] = round(time.perf_counter() - t, 2)

    t = time.perf_counter()
    result = run_with_router(spec, max_iter=max_iter, steps=steps, log=lambda m: print("  router", m))
    timings["build_validate_route"] = round(time.perf_counter() - t, 1)
    spec, build, report = result.spec, result.build, result.report

    t = time.perf_counter()
    paths = {"STEP": str(export_step(build, out / "bicycle.step"))}
    cs, js = write_bom(build, out)
    paths.update(BOM_CSV=str(cs), BOM_JSON=str(js))
    rows = product_bom(spec, build)
    (out / "product_bom.json").write_text(json.dumps({"product": spec.name, "lines": rows}, indent=1, default=str), encoding="utf-8")
    with (out / "product_bom.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        for r in rows:
            w.writerow({**r, "instances": " ".join(r["instances"])})
    paths.update(PRODUCT_BOM_JSON=str(out / "product_bom.json"), PRODUCT_BOM_CSV=str(out / "product_bom.csv"))
    timings["step_bom"] = round(time.perf_counter() - t, 1)

    t = time.perf_counter()
    for view in ("side", "three_quarter"):
        p = render(build, out / f"render_{view}.png", view, title=f"{spec.name}  ({result.status})",
                   ground_z=spec.derived["ground_z"])
        paths[f"PNG_{view}"] = str(p)
    timings["render"] = round(time.perf_counter() - t, 1)

    fc = None
    if freecad:
        _freecad_env()
        t = time.perf_counter()
        try:
            fc = export_fcstd(build, out, scramble=None)
            if fc.get("ok"):
                paths["FCSTD"] = str(out / "assembly.FCStd")
            fc = {k: fc.get(k) for k in ("ok", "joints", "joints_satisfied", "placements_match", "placement_max_dev", "error", "ms", "notes")}
        except Exception as exc:  # FreeCAD missing or failed: report, keep the other exports
            fc = {"ok": False, "error": str(exc)}
        timings["freecad"] = round(time.perf_counter() - t, 1)
    timings["total"] = round(time.perf_counter() - t0, 1)

    (out / "product_spec.json").write_text(spec.model_dump_json(indent=1), encoding="utf-8")
    summary.update(status=result.status, passed=report.passed, product=spec.name, checks=report.summary(),
                   failed=[c.name for c in report.failed], warnings=[c.name for c in report.warnings],
                   router=result.to_dict(), freecad=fc, paths=paths, timings_s=timings,
                   skeleton={k: {"value": p.value, "source": p.source} for k, p in spec.skeleton.items()},
                   derived=spec.derived, requirements_notes=spec.requirements.notes)
    full = {**summary, "report": report.to_dict()}
    (out / "report.json").write_text(json.dumps(full, indent=1, default=str), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt", nargs="?")
    ap.add_argument("--choices", help="BicycleChoices JSON (skips the LLM)")
    ap.add_argument("--offline", action="store_true", help="default choices, no LLM")
    ap.add_argument("--out", default=str(ROOT / "evals" / "out" / "bicycle"))
    ap.add_argument("--no-freecad", action="store_true")
    ap.add_argument("--max-iter", type=int, default=4)
    a = ap.parse_args(argv)
    choices = json.loads(a.choices) if a.choices else ({} if a.offline or not a.prompt else None)
    s = run(a.prompt, choices, Path(a.out), freecad=not a.no_freecad, max_iter=a.max_iter)
    print(json.dumps({k: s.get(k) for k in ("status", "product", "failed", "warnings", "freecad", "timings_s", "paths")},
                     indent=1, default=str))


if __name__ == "__main__":
    main()
