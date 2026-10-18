"""Planner stages: intake parser, plan builder, repair planner and edit planner.

The model proposes; deterministic code decides. Model output is validated by
pydantic and ``compile_recipe`` before anything reaches a CAD worker, and the
clarification policy below is code, not prompt text (blueprint section 9).
"""

from __future__ import annotations

import json
import logging
import math
from functools import lru_cache
from pathlib import Path

from pydantic import ValidationError

from ..adapters import CAPABILITIES
from ..contracts.compile import ANGLE_TO_DEG, FEATURE_REF_FIELDS, LENGTH_TO_MM, compile_recipe
from ..contracts.errors import ErrorCode, ShilpaError
from .llm import Budget, call_structured, strict_schema
from .schemas import PlanOutput, Requirements, from_recipe, to_recipe

log = logging.getLogger("shilpa.planner")
CORPUS = Path(__file__).resolve().parents[2] / "evals" / "corpus"
EXAMPLE_IDS = ("P01", "F03", "B03", "E02", "H03", "N02", "N07", "N08")

IR_GUIDE = """
Shilpa IR 1.1 rules (engineering CAD, millimetres internally, Z up):
- Every dimension is a named parameter. Every numeric feature field is a *_ref string that is either a
  parameter name or a simple expression over parameters using + - * / and parentheses, e.g. "depth / 2 - thickness / 2".
  Bare numbers alone are not allowed in length fields; "thickness / 2" is fine, and a zero coordinate is "0 * width".
- Parameter kinds: length (mm/cm/m/in), angle (deg/rad), count (integers, no unit).
- Feature ids are snake_case, unique, and must not reuse a parameter name. Features may only reference earlier features.
- Sketch planes and their local axes: XY (x=X, y=Y), XZ (x=X, y=Z), YZ (x=Y, y=Z). Every sketch takes an optional
  offset_ref that moves it along the plane normal (+Z for XY, -Y for XZ, +X for YZ).
- Sketches: centered_rectangle (width_ref along local x, height_ref along local y, optional center_x_ref/center_y_ref,
  corner_radius_ref); circle (diameter_ref, optional centre, optional inner_diameter_ref for a ring/tube section);
  slot (length_ref centre-to-centre, width_ref, optional centre and rotation_angle_ref);
  profile: any closed outline from (start_x_ref, start_y_ref) through segments, each ending at (x_ref, y_ref):
  kind line; arc through (mid_x_ref, mid_y_ref); tangent_arc (continues tangent to the previous segment);
  radius_arc (radius_ref, the shorter arc, counter-clockwise unless clockwise=true). The outline closes itself with a
  straight line back to the start and must not cross itself. Use profiles for L/T/U sections, gussets, cams, keyhole
  shapes, half-sections to revolve, and anything that is not a rectangle, circle or slot.
- extrude: profile_ref (a sketch id), distance_ref, direction positive_z | negative_z | positive_normal |
  negative_normal | symmetric, optional offset_ref to start further along the normal.
- stepped_shaft: coaxial cylinders along +Z from Z=0, sections [{diameter_ref, length_ref}], optional bore_diameter_ref.
- revolve: profile_ref, axis X | Y | Z (a global axis through the origin that lies in the sketch plane, e.g. a profile on
  XZ about Z), optional angle_ref (default 360, partial turns go counter-clockwise about +axis). Draw the half-section
  on one side of the axis: pulleys, wheels, nozzles, knobs, grooved or flanged turned parts.
- path: open spine on a plane (default XZ) from (start_x_ref, start_y_ref) through line / arc / tangent_arc / radius_arc
  segments; it must be smooth, so join straight runs with a tangent_arc of the bend radius.
  helix: about Z, diameter_ref, pitch_ref, height_ref, optional offset_ref (start Z), left_handed.
  A spring's free length is its overall length: helix height_ref = free_length - wire_diameter and
  offset_ref = wire_diameter / 2, so the coil spans exactly 0 to free_length.
- sweep: profile_ref swept along path_ref. For a path the sketch must lie at the path start, normal to it (a path on XZ
  starting at the origin and heading +Z takes an XY sketch at the origin). For a helix (springs, coils) the sketch is on
  XZ with its centre at x = helix diameter / 2 and z = helix offset.
- loft: profile_refs (2-10 sketches on the same plane type with strictly increasing offset_ref), ruled true for
  straight-sided transitions (ducts, hoppers, nozzles, tapered bosses).
- hole, corner_hole_pattern (inset edge_offset_ref from each side of the entry face's extent),
  linear_hole_pattern (count_x/count_y/pitch_x/pitch_y, centred on center_x/center_y),
  polar_hole_pattern (count_ref, pitch_diameter_ref, optional start_angle_ref):
  holes are drilled straight into body_ref from one side of its bounding box: face top (default, drills -Z),
  bottom, x_min, x_max, y_min or y_max. Centres are in that face's coordinates: (X, Y) on top/bottom, (Y, Z) on the
  x faces, (X, Z) on the y faces. mode through_all or blind with depth_ref (measured from the entry face).
  The hole footprint must lie on that flat face, so drill holes in a lower plate BEFORE uniting taller bodies onto it.
  Only plain through holes may enter a curved side (a cross hole through a round shaft: face x_max, centre (0, z)).
  hole_type simple | counterbore | countersink | tapped. standard_size M3-M20 fills diameters from ISO tables
  (clearance per fit fine | medium | coarse, counterbore for socket head cap screws, 90 deg countersink for
  countersunk screws, tap drill for tapped holes); give cbore_diameter_ref / cbore_depth_ref / csk_diameter_ref /
  csk_angle_ref only to override the table or when no standard size applies. Tapped holes need standard_size,
  record the thread as metadata (no modelled thread) and take an optional thread_depth_ref.
  Intersecting drillings (manifolds, cross ports) are separate holes from different faces, never extruded cylinders.
- Every operation that modifies a body (holes, pocket, boolean, shell, fillet, chamfer, mirror, patterns) returns a
  new body id: chain them, so each feature's body_ref is the id of the previous modification and the last one is the
  output. Nothing may be left unused.
- pocket: rectangular cavity cut down from the top face (width_ref, height_ref, depth_ref, optional corner_radius_ref);
  it must leave walls and a floor.
- boolean: union | cut | intersect of target_ref and tool_ref bodies (union bodies must touch). A cut whose tool is an
  extrude must stay inside the target's side walls (use holes for openings through walls); revolve, sweep and loft
  tools may cut through side walls (grooves, channels).
- shell: hollow body_ref to wall thickness_ref, removing open_faces [{side: top|bottom|x_min|x_max|y_min|y_max,
  expected_count}], direction inward (default) or outward. Use it for enclosures, cups, ducts and hoppers.
- mirror: body_ref mirrored across plane XY | XZ | YZ placed at offset_ref along that plane's own axis (z, y, x);
  keep_original true unites the body with its image (the halves must touch, or be a tool for a later boolean).
- linear_pattern: count_ref copies of body_ref spacing_ref apart along +direction X | Y | Z (copy 1 is the original).
  polar_pattern: count_ref copies about axis X | Y | Z through the origin, 360 deg by default or angle_ref from first to
  last copy. Pattern or mirror a standalone tool (a boss, rib, spoke, slot cutter) and then boolean it into the part.
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

Supported engineering families right now: mounting plates, brackets, spacers/washers, stepped shafts,
flanges (with bolt circles and hubs), enclosures, and other single machined or moulded parts built from the
operations listed below (turned/revolved parts such as pulleys, swept tubes and handles, lofted ducts, shelled
housings, springs, manifold blocks with drilled channels). Classify anything that is not one of the named families
as family "other"; freeform or organic shapes, textured props and concept art are task_class "visual_asset" or
"unsupported".

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
- Metric screw sizes (M3-M20) name a standard: a clearance, counterbored or countersunk hole for that screw, or a
  tapped hole, takes its diameters from ISO tables. Record the size in features (e.g. "four M5 countersunk holes"),
  not as a dimension, and do not ask for its clearance, counterbore or countersink diameters.
Shilpa makes one connected part per request. If the request asks for two or more separate parts, set task_class
"unsupported" and say they should be requested one at a time.

If any requested feature cannot be built with the operations listed below (for example engraved text or logos,
modelled thread geometry, gear teeth, knurling, freeform or organic surfaces), set task_class "unsupported", name the
feature in unsupported_reason, and do not ask questions about it. Tapped holes are supported (the thread is recorded,
not modelled); springs and coils are supported as a helical sweep.

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
    """Deterministic clean-up of constraints strict mode cannot express.

    Empty optional refs become null, and nulls inside features are dropped: strict mode makes every
    optional field nullable, but a null boolean or enum (clockwise, left_handed, direction) means
    "use the default", not an invalid value.
    """
    def walk(node):
        if isinstance(node, dict):
            out = {k: (None if k.endswith("_ref") and isinstance(v, str) and not v.strip() else walk(v)) for k, v in node.items()}
            return {k: v for k, v in out.items() if v is not None}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    if isinstance(data.get("features"), list):
        data = {**data, "features": walk(data["features"])}
    return data


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

    def collect(node) -> None:  # refs anywhere in a feature: shaft sections, profile segments, selectors
        if isinstance(node, dict):
            for k, v in node.items():
                if k.endswith("_ref") and isinstance(v, str) and not k.endswith(FEATURE_REF_FIELDS):
                    used.update(_names_in(v))
                else:
                    collect(v)
        elif isinstance(node, list):
            for v in node:
                collect(v)

    for cf in compiled.features:
        collect(cf.spec.model_dump())
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
        size = getattr(cf.spec, "standard_size", None)
        if size:
            values.append(("length", float(size[1:])))  # "M6" stated as 6 mm is met by the M6 hole series
        for seg in cf.segments or []:
            if seg.kind == "arc":  # a stated bend or arc angle is met by an arc that sweeps it
                values.append(("angle", round(math.degrees(seg.sweep), 9)))
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
