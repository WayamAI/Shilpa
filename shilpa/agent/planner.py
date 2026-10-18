"""Planner stages: intake parser, plan builder, repair planner and edit planner.

The model proposes; deterministic code decides. Model output is validated by
pydantic and ``compile_recipe`` before anything reaches a CAD worker, and the
clarification policy below is code, not prompt text (blueprint section 9).
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

from pydantic import ValidationError

from ..adapters import CAPABILITIES
from ..contracts.compile import ANGLE_TO_DEG, LENGTH_TO_MM, compile_recipe
from ..contracts.errors import ErrorCode, ShilpaError
from .llm import Budget, call_structured, strict_schema
from .schemas import PlanOutput, Requirements, from_recipe, to_recipe

log = logging.getLogger("shilpa.planner")
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
   boundary: outer|inner|any, diameter_ref, expected_count}. "outer" means the edge lies on the body's bounding box.
  diameter_ref keeps only circular edges of that diameter: use it to pick one circle among several at the same height
  (for example the hub-to-disc junction "hub_diameter" while bolt holes and the bore also have circles there).
  expected_count must equal the number of edges you intend to treat, or the build fails.
- The last body feature is the output. Set expected_bbox_refs to refs for overall X, Y, Z size when you can.
- Never invent a critical engineering dimension. Non-critical assumptions (e.g. a small edge break) must be
  listed in assumptions with a reason and the parameter source set to "assumed".
- Only use the operations above. If the part needs anything else, do not approximate it with a different shape.
- Do not model shop notes such as "break sharp edges" or "deburr"; model only dimensioned features.
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
Record contradictory statements in conflicts. If units are not stated, set units null; never ask about units.

Apply these standard engineering conventions instead of asking, and list each one you apply in assumptions:
- Holes, bores and bolt holes go through the full part unless a depth is stated.
- A distance of a hole "from the edge" is measured from the edge to the hole centre.
- Features are centred and symmetric on the part unless a position is stated (e.g. two holes "90 mm apart" are centred).
- "Corner" holes are four holes, one per corner, at the stated edge distance.
- Bolt circles and other features are concentric with the part; the first bolt hole sits on +X unless an angle is stated.
- A grid or row of holes is centred on the part.
- An L bracket's vertical leg stands at the back edge of the base, full width; "height" is the overall height.
- Stepped shafts are listed from the bottom up; a box is open at the top with the stated wall and floor thickness.
- Chamfers are 45 degrees with the stated leg size; "rounded corners" on a plate mean its vertical edges.
Shilpa makes one connected part per request. If the request asks for two or more separate parts, set task_class
"unsupported" and say they should be requested one at a time.

If any requested feature cannot be built with the operations listed below (for example engraved text or logos,
threads, gear teeth, springs, spheres, freeform or organic surfaces), set task_class "unsupported", name the feature
in unsupported_reason, and do not ask questions about it.

Only ask about a value that no convention supplies and without which the geometry is undefined
(for example a missing thickness, hole diameter, overall size, or a bolt circle diameter).

Operations Shilpa can build:
{IR_GUIDE}
"""


def extract_requirements(prompt: str, budget: Budget) -> dict:
    for attempt in (1, 2):
        try:
            data = call_structured(system=INTAKE_SYSTEM, user=prompt, schema_name="requirements", schema=_schema("requirements"),
                                   budget=budget, max_output_tokens=2500, purpose="intake")
            break
        except ShilpaError as exc:
            # One retry for a slow model call, inside the same budget; other errors are final.
            if exc.code != ErrorCode.MODEL_TIMEOUT or attempt == 2:
                raise
    try:
        req = Requirements.model_validate(data).model_dump()
    except ValidationError as exc:
        raise ShilpaError(ErrorCode.INVALID_SCHEMA, f"intake output does not match the schema: {exc.errors()[0]['msg']}")
    return apply_clarification_policy(req)


def _dim(req: dict, *keys: str, exclude: tuple[str, ...] = ()) -> tuple[str, float] | None:
    for d in req.get("dimensions", []):
        n = d["name"].lower()
        if d.get("value") and d.get("kind") == "length" and any(k in n for k in keys) and not any(x in n for x in exclude):
            return d["name"], float(d["value"])
    return None


def relational_conflicts(req: dict) -> list[str]:
    """Geometric relations every supported family must satisfy, checked in code (shared by text and drawing intake)."""
    out = []
    od = _dim(req, "outer_diameter", "outside_diameter", "flange_diameter", "disc_diameter", exclude=("hub", "boss"))
    hub = _dim(req, "hub_diameter")
    bore = _dim(req, "bore", "inner_diameter", "inside_diameter")
    pcd = _dim(req, "pitch", "pcd", "bolt_circle")
    if od and hub and hub[1] >= od[1]:
        out.append(f"{hub[0]} {hub[1]:g} is not smaller than {od[0]} {od[1]:g}")
    if od and bore and bore[1] >= od[1]:
        out.append(f"{bore[0]} {bore[1]:g} is not smaller than {od[0]} {od[1]:g}")
    if hub and bore and bore[1] >= hub[1]:
        out.append(f"{bore[0]} {bore[1]:g} is not smaller than {hub[0]} {hub[1]:g}")
    if od and pcd and "diameter" in pcd[0] and pcd[1] >= od[1]:
        out.append(f"{pcd[0]} {pcd[1]:g} is not inside {od[0]} {od[1]:g}")
    return out


def apply_clarification_policy(req: dict) -> dict:
    """Deterministic decision on whether generation may start (blueprint section 9, T022-T026)."""
    known = {c["description"] for c in req.get("conflicts", [])}
    for msg in relational_conflicts(req):
        if msg not in known:
            req.setdefault("conflicts", []).append({"description": msg, "fields": []})
    if req["task_class"] != "engineering_cad":
        req["status"] = "unsupported"
        req["status_reason"] = req.get("unsupported_reason") or f"{req['task_class']} is not available in this release"
        return req
    stated = {d["name"] for d in req["dimensions"] if d["value"] is not None}
    # Units follow the explicit project-default policy (T023); they are never a blocking question.
    missing = [m for m in req["missing"] if m["name"] not in stated and "unit" not in m["name"].lower()]
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


def _plan_call(user: str, budget: Budget, purpose: str, feedback: str | None = None) -> dict:
    system = PLAN_SYSTEM.replace("{examples}", _examples())
    if feedback:
        user += f"\n\nYour previous answer was rejected: {feedback}\nReturn a corrected answer."
    data = call_structured(system=system, user=user, schema_name="recipe_plan", schema=_schema("plan"),
                           budget=budget, max_output_tokens=8000, purpose=purpose)
    data = _normalize_plan(data)
    try:
        plan = PlanOutput.model_validate(data).model_dump()
    except ValidationError as exc:
        msg = _explain_plan_error(exc, data)
        log.warning("planner output rejected: %s", msg)
        raise ShilpaError(ErrorCode.INVALID_SCHEMA, f"planner output does not match the plan schema: {msg}")
    recipe = to_recipe(plan)
    recipe["_change_summary"] = plan.get("change_summary")
    return recipe


def _normalize_plan(data: dict) -> dict:
    """Deterministic clean-up of constraints strict mode cannot express (empty optional refs become null)."""
    def walk(node):
        if isinstance(node, dict):
            return {k: (None if k.endswith("_ref") and isinstance(v, str) and not v.strip() else walk(v)) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(data)


def _explain_plan_error(exc: ValidationError, data: dict) -> str:
    """Pick the error from the union member that matches the feature's own op, not the first member tried."""
    feats = data.get("features") or []
    for err in exc.errors():
        loc = err["loc"]
        if len(loc) >= 3 and loc[0] == "features" and isinstance(loc[1], int) and loc[1] < len(feats):
            op = (feats[loc[1]] or {}).get("op")
            member = str(loc[2]).lower()
            if op and op.replace("_", "") in member.replace("_", ""):
                field = ".".join(str(x) for x in loc[3:]) or "feature"
                return f"feature {loc[1]} ({op}) field {field}: {err['msg']} (got {str(err.get('input'))[:80]!r})"
    first = exc.errors()[0]
    return f"{'.'.join(str(x) for x in first['loc'])}: {first['msg']}"


def check_recipe(recipe: dict) -> dict:
    """Static capability and schema check. Raises ShilpaError; returns the clean recipe."""
    summary = recipe.pop("_change_summary", None)
    compiled = compile_recipe(recipe, CAPABILITIES)
    clean = compiled.recipe.model_dump(mode="json", exclude_none=True)
    if summary:
        clean["_change_summary"] = summary
    return clean


def plan_recipe(requirements: dict, budget: Budget, feedback: str | None = None) -> dict:
    req = {k: requirements[k] for k in ("family", "summary", "units", "dimensions", "features", "assumptions") if k in requirements}
    return _plan_call("Confirmed requirements:\n" + json.dumps(req, indent=1), budget, "plan", feedback)


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


def edit_recipe(recipe: dict, instruction: str, budget: Budget, feedback: str | None = None) -> dict:
    user = (
        "Apply the engineer's edit to this recipe and return the full updated recipe. Keep parameter names and "
        "feature ids stable for everything that does not change. Prefer changing parameter values over "
        "restructuring features. Do not invent new critical dimensions; if the edit needs one that was not given, "
        "keep the recipe unchanged and explain in change_summary what is missing. Describe the change in change_summary.\n\n"
        f"Current recipe:\n{json.dumps(from_recipe(recipe), separators=(',', ':'))}\n\n"
        f"Edit request: {instruction}"
    )
    return _plan_call(user, budget, "edit", feedback)


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


def check_requirements(recipe: dict, requirements: dict) -> None:
    """Deterministic coverage check: every stated length and angle must drive the geometry.

    The planner may rename parameters, so values are matched after unit normalisation. A
    stated value that no feature uses means the plan dropped part of the request (for
    example a centre bore); that is repairable, and never published.
    """
    compiled = compile_recipe({k: v for k, v in recipe.items() if not k.startswith("_")}, CAPABILITIES)
    used: set[str] = set()
    for cf in compiled.features:
        for k, v in cf.spec:
            if k.endswith("_ref") and isinstance(v, str):
                used |= _names_in(v)
            elif k == "sections":
                for sec in v:
                    used |= _names_in(sec.diameter_ref) | _names_in(sec.length_ref)
    # Derived parameters carry the names they depend on.
    raw = compiled.recipe.parameters
    frontier = set(used)
    while frontier:
        name = frontier.pop()
        p = raw.get(name)
        if p is not None and not isinstance(p, (int, float)) and p.expr:
            new = _names_in(p.expr) - used
            used |= new
            frontier |= new
    values = [(q.kind, q.value) for k, q in compiled.params.items() if k in used]
    has_chamfer = any(cf.op == "chamfer" for cf in compiled.features)
    # A stated value may also be met by an expression, e.g. overall height = thickness + hub_length.
    from ..contracts.compile import field_kind

    for cf in compiled.features:
        for k, v in cf.values.items():
            kind = field_kind(k.split(".")[-1])
            values.append((kind, v))
            if kind == "length" and ("diameter" in k):
                values.append((kind, v / 2))  # a stated radius
    for v in compiled.assertion_values.get("bbox", []):
        values.append(("length", v))
    default_unit = requirements.get("units") or "mm"
    missing = []
    for d in requirements.get("dimensions", []):
        if d.get("value") is None or d.get("kind") not in ("length", "angle") or d.get("source") not in ("user", "drawing"):
            continue
        if d["kind"] == "length" and d["value"] == 0:
            continue  # "no centre bore" is recorded as 0: an absent feature, not a dimension to build
        if d["kind"] == "angle" and has_chamfer and abs(d["value"] * ANGLE_TO_DEG.get(d.get("unit") or "deg", 1.0) - 45) < 1e-6:
            continue  # IR chamfers are 45 degrees by definition ("1 X 45°")
        if d["kind"] == "length":
            want = d["value"] * LENGTH_TO_MM.get(d.get("unit") or default_unit, 1.0)
        else:
            want = d["value"] * ANGLE_TO_DEG.get(d.get("unit") or "deg", 1.0)
        if not any(kind == d["kind"] and abs(v - want) <= 1e-6 * max(1.0, abs(want)) for kind, v in values):
            missing.append(f"{d['name']} = {d['value']:g} {d.get('unit') or (default_unit if d['kind'] == 'length' else 'deg')}")
    if missing:
        raise ShilpaError(ErrorCode.REQUIREMENT_NOT_MET,
                          "the plan does not use these stated values: " + "; ".join(missing)
                          + ". Add each as a parameter that drives the matching feature.",
                          details={"unused": missing})


def _names_in(text: str | None) -> set[str]:
    from ..contracts import expr as _expr

    return _expr.names(text) if text else set()
