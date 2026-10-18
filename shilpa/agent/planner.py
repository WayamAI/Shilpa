"""Planner stages: intake parser, plan builder, repair planner and edit planner.

The model proposes; deterministic code decides. Model output is validated by
pydantic and ``compile_recipe`` before anything reaches a CAD worker, and the
clarification policy below is code, not prompt text (blueprint section 9).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import ValidationError

from ..adapters import CAPABILITIES
from ..contracts.compile import compile_recipe
from ..contracts.errors import ErrorCode, ShilpaError
from .llm import Budget, call_structured, strict_schema
from .schemas import PlanOutput, Requirements, from_recipe, to_recipe

CORPUS = Path(__file__).resolve().parents[2] / "evals" / "corpus"
EXAMPLE_IDS = ("P01", "F03", "B03", "E02", "H03")

IR_GUIDE = """
Shilpa IR 1.0 rules (engineering CAD, millimetres internally, Z up):
- Every dimension is a named parameter. Every numeric feature field is a *_ref string that is either a
  parameter name or a simple expression over parameters using + - * / and parentheses, e.g. "depth / 2 - thickness / 2".
  Bare numbers alone are not allowed in length fields; "thickness / 2" is fine.
- Parameter kinds: length (mm/cm/m/in), angle (deg/rad), count (integers, no unit).
- Feature ids are snake_case, unique, and must not reuse a parameter name. Features may only reference earlier features.
- Sketches: centered_rectangle (width_ref along X, height_ref along Y, optional center_x_ref/center_y_ref,
  corner_radius_ref), circle (diameter_ref, optional centre). Planes XY (default), XZ, YZ.
- extrude: profile_ref (a sketch id), distance_ref, direction positive_z | negative_z | symmetric,
  optional offset_ref to start above Z=0.
- stepped_shaft: coaxial cylinders along +Z from Z=0, sections [{diameter_ref, length_ref}], optional bore_diameter_ref.
- hole, corner_hole_pattern (inset edge_offset_ref from each side of the body's XY extent),
  linear_hole_pattern (count_x/count_y/pitch_x/pitch_y, centred on center_x/center_y),
  polar_hole_pattern (count_ref, pitch_diameter_ref, optional start_angle_ref):
  holes are drilled straight down (-Z) from the TOP face (highest Z) of body_ref; mode through_all or blind with depth_ref.
  The hole footprint must lie on that top face, so drill holes in a lower plate BEFORE uniting taller bodies onto it.
- pocket: rectangular cavity cut down from the top face (width_ref, height_ref, depth_ref, optional corner_radius_ref);
  it must leave walls and a floor.
- boolean: union | cut | intersect of target_ref and tool_ref bodies (union bodies must touch).
- fillet / chamfer: body_ref, radius_ref or distance_ref, and a semantic edge selector
  {direction: parallel_z|perpendicular_z|any, location: top|bottom|between|any, curve: line|circle|any,
   boundary: outer|inner|any, expected_count}. "outer" means the edge lies on the body's bounding box.
  expected_count must equal the number of edges you intend to treat, or the build fails.
- The last body feature is the output. Set expected_bbox_refs to refs for overall X, Y, Z size when you can.
- Never invent a critical engineering dimension. Non-critical assumptions (e.g. a small edge break) must be
  listed in assumptions with a reason and the parameter source set to "assumed".
- Only use the operations above. If the part needs anything else, do not approximate it with a different shape.
""".strip()


@lru_cache(maxsize=1)
def _examples() -> str:
    out = []
    for fid in EXAMPLE_IDS:
        p = CORPUS / f"{fid}.json"
        if p.exists():
            fx = json.loads(p.read_text(encoding="utf-8"))
            out.append(f"Example - {fx['description']}:\n{json.dumps(from_recipe(fx['recipe']), separators=(',', ':'))}")
    return "\n\n".join(out)


@lru_cache(maxsize=None)
def _schema(model_name: str) -> dict:
    model = {"requirements": Requirements, "plan": PlanOutput}[model_name]
    return strict_schema(model.model_json_schema())


# ---------------------------------------------------------------- stage 1


INTAKE_SYSTEM = f"""You are the intake parser for Shilpa, an engineering CAD agent.
Read the engineer's request and extract typed requirements. Do not design the part yet.

Supported engineering families right now: mounting plates, simple brackets, spacers/washers, stepped shafts,
flanges (with bolt circles and hubs), and prismatic open enclosures. Classify anything else as family "other";
freeform or organic shapes, textured props and concept art are task_class "visual_asset" or "unsupported".

For each dimension, record the exact words that state it as evidence. If a value is not stated, set value null
and add it to missing with a short question. A dimension is critical if the geometry is undefined without it
(overall sizes, thickness, hole diameters and positions or spacing, counts). Never fill a critical value with a guess.
Small edge breaks or fillet radii that were not requested may be omitted rather than assumed.
Record contradictory statements in conflicts. If units are not stated, set units null.

Operations Shilpa can build:
{IR_GUIDE}
"""


def extract_requirements(prompt: str, budget: Budget) -> dict:
    data = call_structured(system=INTAKE_SYSTEM, user=prompt, schema_name="requirements", schema=_schema("requirements"),
                           budget=budget, max_output_tokens=2500, purpose="intake")
    try:
        req = Requirements.model_validate(data).model_dump()
    except ValidationError as exc:
        raise ShilpaError(ErrorCode.INVALID_SCHEMA, f"intake output does not match the schema: {exc.errors()[0]['msg']}")
    return apply_clarification_policy(req)


def apply_clarification_policy(req: dict) -> dict:
    """Deterministic decision on whether generation may start (blueprint section 9, T022-T026)."""
    if req["task_class"] != "engineering_cad":
        req["status"] = "unsupported"
        req["status_reason"] = req.get("unsupported_reason") or f"{req['task_class']} is not available in this release"
        return req
    stated = {d["name"] for d in req["dimensions"] if d["value"] is not None}
    missing = [m for m in req["missing"] if m["name"] not in stated]
    for d in req["dimensions"]:
        if d["value"] is None and d["critical"] and d["name"] not in {m["name"] for m in missing}:
            missing.append({"name": d["name"], "question": f"What is the {d['name'].replace('_', ' ')}?", "critical": True})
    req["missing"] = missing
    if req["units"] is None:
        req["units"] = "mm"
        req["units_source"] = "project default"
    else:
        req["units_source"] = "user"
    if req["conflicts"]:
        req["status"] = "needs_clarification"
        req["status_reason"] = "conflicting dimensions"
    elif any(m["critical"] for m in missing):
        req["status"] = "needs_clarification"
        req["status_reason"] = "missing critical dimensions"
    else:
        req["status"] = "ready"
        req["status_reason"] = None
    return req


def answer_clarifications(req: dict, answers: dict[str, float], resolved_conflicts: bool = False) -> dict:
    by_name = {d["name"]: d for d in req["dimensions"]}
    for name, value in answers.items():
        if name in by_name:
            by_name[name].update(value=float(value), source="user", evidence="answered in clarification")
        else:
            m = next((m for m in req["missing"] if m["name"] == name), None)
            req["dimensions"].append({"name": name, "value": float(value), "unit": None, "kind": "length", "critical": bool(m and m["critical"]),
                                      "source": "user", "evidence": "answered in clarification"})
    req["missing"] = [m for m in req["missing"] if m["name"] not in answers]
    if resolved_conflicts:
        req["conflicts"] = []
    return apply_clarification_policy(req)


# ---------------------------------------------------------------- stage 2


PLAN_SYSTEM = f"""You are the plan builder for Shilpa, an engineering CAD agent.
Turn confirmed requirements into a Shilpa IR recipe using only the supported operations.
Use the requirement dimension names as parameter names wherever possible so later edits are by name.
Use the stated units. Prefer the simplest feature sequence that matches the requirements exactly.

{IR_GUIDE}

{{examples}}
"""


def _plan_call(user: str, budget: Budget, purpose: str) -> dict:
    system = PLAN_SYSTEM.replace("{examples}", _examples())
    data = call_structured(system=system, user=user, schema_name="recipe_plan", schema=_schema("plan"),
                           budget=budget, max_output_tokens=4000, purpose=purpose)
    try:
        plan = PlanOutput.model_validate(data).model_dump()
    except ValidationError as exc:
        raise ShilpaError(ErrorCode.INVALID_SCHEMA, f"planner output does not match the plan schema: {exc.errors()[0]['msg']}")
    recipe = to_recipe(plan)
    recipe["_change_summary"] = plan.get("change_summary")
    return recipe


def check_recipe(recipe: dict) -> dict:
    """Static capability and schema check. Raises ShilpaError; returns the clean recipe."""
    summary = recipe.pop("_change_summary", None)
    compiled = compile_recipe(recipe, CAPABILITIES)
    clean = compiled.recipe.model_dump(mode="json", exclude_none=True)
    if summary:
        clean["_change_summary"] = summary
    return clean


def plan_recipe(requirements: dict, budget: Budget) -> dict:
    req = {k: requirements[k] for k in ("family", "summary", "units", "dimensions", "features") if k in requirements}
    return _plan_call("Confirmed requirements:\n" + json.dumps(req, indent=1), budget, "plan")


def repair_recipe(recipe: dict, error: dict, feature_results: list | None, budget: Budget) -> dict:
    user = (
        "This recipe failed. Return a corrected full recipe that keeps every user-specified dimension unchanged. "
        "Change only what is needed to fix the failure. If the failure cannot be fixed without changing a "
        "user dimension, keep the dimension and fix the feature sequence instead.\n\n"
        f"Recipe:\n{json.dumps(from_recipe(recipe), separators=(',', ':'))}\n\n"
        f"Failure:\n{json.dumps(error, separators=(',', ':'))}\n\n"
        f"Feature results:\n{json.dumps(feature_results or [], separators=(',', ':'), default=str)[:3000]}"
    )
    return _plan_call(user, budget, "repair")


def edit_recipe(recipe: dict, instruction: str, budget: Budget) -> dict:
    user = (
        "Apply the engineer's edit to this recipe and return the full updated recipe. Keep parameter names and "
        "feature ids stable for everything that does not change. Prefer changing parameter values over "
        "restructuring features. Do not invent new critical dimensions; if the edit needs one that was not given, "
        "keep the recipe unchanged and explain in change_summary what is missing. Describe the change in change_summary.\n\n"
        f"Current recipe:\n{json.dumps(from_recipe(recipe), separators=(',', ':'))}\n\n"
        f"Edit request: {instruction}"
    )
    return _plan_call(user, budget, "edit")


def apply_parameter_edit(recipe: dict, changes: dict[str, float]) -> dict:
    """Deterministic parameter edit: no model call, keeps all other recipe content."""
    out = json.loads(json.dumps(recipe))
    for name, value in changes.items():
        if name not in out["parameters"]:
            raise ShilpaError(ErrorCode.UNKNOWN_REFERENCE, f"unknown parameter {name!r}", field=name)
        cur = out["parameters"][name]
        if isinstance(cur, dict):
            if cur.get("expr") is not None:
                raise ShilpaError(ErrorCode.INVALID_PARAMETER, f"{name} is derived from an expression and cannot be set directly", field=name)
            cur.update(value=float(value), source="user")
        else:
            out["parameters"][name] = float(value)
    return out
