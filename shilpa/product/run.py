"""One call from a request (or a spec) to a checked, exported product: ``run_product``.

Flow: request text -> choices (offline rule parser by default, or the LLM
planner) -> ``ProductSpec`` from the template -> build -> product checks ->
rollback router -> exports (STEP, BOM, FreeCAD) and PNG renders. Everything
returned is plain JSON (``json.dumps`` works on it as is).
"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Any, Callable, Literal

from ..contracts.product import ProductSpec

Planner = Literal["offline", "llm"]


def product_bom(spec: ProductSpec, build) -> list[dict]:
    """Assembly BOM lines joined with the product tree: procurement, tree node, standard, designation, mass."""
    from ..validators.assembly import bill_of_materials

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
    return rows


def resolve_request(spec_or_request: Any, planner: Planner = "offline") -> tuple[ProductSpec | None, dict | None]:
    """Turn any accepted input into a ``ProductSpec``; returns ``(None, planner_result)`` when refused."""
    from .templates.bicycle import BicycleChoices, bicycle_spec
    from .templates.gearbox import GearboxChoices, gearbox_spec

    def from_choices(choices):
        return gearbox_spec(choices) if isinstance(choices, GearboxChoices) else bicycle_spec(choices)

    if isinstance(spec_or_request, ProductSpec):
        return spec_or_request, None
    if isinstance(spec_or_request, (BicycleChoices, GearboxChoices)):
        return from_choices(spec_or_request), None
    if isinstance(spec_or_request, dict):
        if "template" in spec_or_request and "assembly" in spec_or_request:
            return ProductSpec.model_validate(spec_or_request), None
        if spec_or_request.get("product_class") == "gearbox":
            return gearbox_spec({k: v for k, v in spec_or_request.items() if k != "product_class"}), None
        return bicycle_spec(spec_or_request), None
    if isinstance(spec_or_request, str):
        from ..agent import product_planner as pp

        # The LLM planner only knows the bicycle template; gearboxes always use the offline parser (no model call).
        use_llm = planner == "llm" and not pp.is_gearbox_request(spec_or_request)
        res = pp.plan_product(spec_or_request) if use_llm else pp.parse_request_offline(spec_or_request)
        info = res.to_dict()
        if not res.supported or res.choices is None:
            return None, info
        return from_choices(res.choices), info
    raise TypeError(f"run_product takes a ProductSpec, a choices or spec dict, or request text; got {type(spec_or_request).__name__}")


def run_product(spec_or_request: Any, out_dir: str | Path, *, planner: Planner = "offline",
                freecad: bool | None = None, renders: bool = True, max_iter: int = 4, steps: int = 9,
                log: Callable[[str], None] | None = None) -> dict:
    """Build, check, repair and export one product. See ``shilpa.product`` for the returned keys."""
    from ..adapters import freecad_adapter
    from ..assembly.export import export_fcstd, export_step, write_bom
    from .render import render
    from .router import run_with_router

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    spec, plan = resolve_request(spec_or_request, planner)
    timings["plan_and_spec"] = round(time.perf_counter() - t0, 2)
    request = spec_or_request if isinstance(spec_or_request, str) else (spec.requirements.text if spec else None)
    if spec is None:
        result = {"status": "unsupported" if not plan["supported"] else "rejected", "message": plan["message"],
                  "request": request, "planner": plan, "spec": None, "placements": {}, "bom": [], "checks": None,
                  "router": None, "exports": {}, "renders": {}, "freecad": None, "timings_s": timings}
        (out / "summary.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
        return result

    t = time.perf_counter()
    routed = run_with_router(spec, max_iter=max_iter, steps=steps, log=log)
    timings["build_check_route"] = round(time.perf_counter() - t, 1)
    timings["router_iterations"] = len(routed.iterations)
    spec, build, report = routed.spec, routed.build, routed.report

    exports: dict[str, str] = {}
    t = time.perf_counter()
    if build.placed:
        exports["step"] = str(export_step(build, out / f"{spec.requirements.product_class}.step"))
        cs, js = write_bom(build, out)
        exports.update(bom_csv=str(cs), bom_json=str(js))
    rows = product_bom(spec, build)
    (out / "product_bom.json").write_text(json.dumps({"product": spec.name, "lines": rows}, indent=1, default=str),
                                          encoding="utf-8")
    with (out / "product_bom.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["part_number"])
        w.writeheader()
        for r in rows:
            w.writerow({**r, "instances": " ".join(r["instances"])})
    exports.update(product_bom_json=str(out / "product_bom.json"), product_bom_csv=str(out / "product_bom.csv"))
    timings["step_bom"] = round(time.perf_counter() - t, 1)

    pngs: dict[str, str] = {}
    if renders and build.placed:
        t = time.perf_counter()
        for view in ("side", "iso"):
            pngs[view] = str(render(build, out / f"render_{view}.png", view, title=f"{spec.name}  ({routed.status})",
                                    ground_z=spec.derived.get("ground_z")))
        timings["render"] = round(time.perf_counter() - t, 1)

    fc = None
    if freecad or (freecad is None and freecad_adapter.available()):
        t = time.perf_counter()
        try:
            res = export_fcstd(build, out, scramble=None)
            if res.get("ok"):
                exports["fcstd"] = str(out / "assembly.FCStd")
            fc = {k: res.get(k) for k in ("ok", "joints", "joints_satisfied", "placements_match", "placement_max_dev",
                                          "error", "ms", "notes")}
        except Exception as exc:  # FreeCAD missing or failed: report it, keep the other exports
            fc = {"ok": False, "error": str(exc)}
        timings["freecad"] = round(time.perf_counter() - t, 1)
    timings["total"] = round(time.perf_counter() - t0, 1)

    exports["spec_json"] = str(out / "product_spec.json")
    exports["report_json"] = str(out / "report.json")
    (out / "product_spec.json").write_text(spec.model_dump_json(indent=1), encoding="utf-8")
    result = {
        "status": routed.status, "passed": report.passed, "request": request, "product": spec.name,
        "template": spec.template, "planner": plan,
        "message": f"{spec.name}: {routed.status}" + (f"; failed {[c.name for c in report.failed]}" if report.failed else ""),
        "spec": spec.model_dump(mode="json"),
        "placements": build.placement_table(),
        "bom": rows,
        "checks": {**report.to_dict(), "summary": report.summary(), "failed": [c.name for c in report.failed],
                   "warnings": [c.name for c in report.warnings]},
        "router": routed.to_dict(),
        "exports": exports, "renders": pngs, "freecad": fc, "timings_s": timings,
    }
    result = json.loads(json.dumps(result, default=str))
    (out / "report.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result
