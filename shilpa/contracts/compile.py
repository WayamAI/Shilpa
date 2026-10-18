"""Static checks and parameter resolution, run before any geometry executes.

``compile_recipe`` turns a Recipe into a CompiledRecipe: every parameter normalised
to millimetres or degrees (with conversion evidence), every ``*_ref`` evaluated,
feature references checked, and the adapter capability matrix consulted. A recipe
that fails here never reaches a CAD worker (blueprint T007, T008, T015, T026).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from . import expr
from .errors import ErrorCode, ShilpaError
from .expr import Quantity
from .ir import SKETCH_OPS, Param, Recipe

LENGTH_TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}
ANGLE_TO_DEG = {"deg": 1.0, "rad": 180.0 / math.pi}

# Reference fields that may be zero or negative. Everything else must be > 0.
SIGNED_FIELDS = {"center_x_ref", "center_y_ref", "offset_ref", "start_angle_ref"}


def field_kind(name: str) -> str:
    if "count" in name:
        return "count"
    if "angle" in name:
        return "angle"
    return "length"


@dataclass
class ConversionEvidence:
    parameter: str
    source_value: float
    source_unit: str
    normalized_value: float
    normalized_unit: str


@dataclass
class CompiledFeature:
    id: str
    op: str
    spec: Any  # the pydantic feature model
    values: dict[str, float]  # evaluated *_ref fields, mm / deg / count


@dataclass
class CompiledRecipe:
    recipe: Recipe
    params: dict[str, Quantity]
    features: list[CompiledFeature]
    output_id: str
    conversions: list[ConversionEvidence] = field(default_factory=list)
    assertion_values: dict[str, Any] = field(default_factory=dict)


def parse_recipe(data: dict | str) -> Recipe:
    try:
        if isinstance(data, str):
            return Recipe.model_validate_json(data)
        return Recipe.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first["loc"])
        raise ShilpaError(
            ErrorCode.INVALID_SCHEMA,
            f"{loc}: {first['msg']}",
            field=loc,
            details={"errors": exc.errors(include_url=False, include_context=False)[:10]},
        )


def resolve_parameters(recipe: Recipe) -> tuple[dict[str, Quantity], list[ConversionEvidence]]:
    raw: dict[str, Param] = {
        k: (v if isinstance(v, Param) else Param(value=float(v))) for k, v in recipe.parameters.items()
    }
    resolved: dict[str, Quantity] = {}
    evidence: list[ConversionEvidence] = []
    visiting: set[str] = set()

    def resolve(name: str, chain: tuple[str, ...]) -> Quantity:
        if name in resolved:
            return resolved[name]
        if name not in raw:
            raise ShilpaError(ErrorCode.UNKNOWN_REFERENCE, f"unknown parameter {name!r}", field=name)
        if name in visiting:
            raise ShilpaError(
                ErrorCode.REFERENCE_CYCLE, "parameter cycle: " + " -> ".join(chain + (name,)), field=name
            )
        p = raw[name]
        visiting.add(name)
        if p.expr is not None:
            scope = {n: resolve(n, chain + (name,)) for n in expr.names(p.expr)}
            q = expr.evaluate(p.expr, scope)
            if p.kind != q.kind and not (p.kind in expr.SCALAR_KINDS and q.kind in expr.SCALAR_KINDS):
                raise ShilpaError(
                    ErrorCode.UNIT_MISMATCH, f"{name} is declared {p.kind} but evaluates to {q.kind}", field=name
                )
            q = Quantity(q.value, p.kind)
        elif p.value is not None:
            q = Quantity(_normalize(name, p, recipe.units, evidence), p.kind)
        else:
            raise ShilpaError(ErrorCode.INVALID_PARAMETER, f"{name} has neither value nor expr", field=name)
        expr.finite(q, name)
        if p.kind == "count" and (q.value != int(q.value) or q.value < 0):
            raise ShilpaError(ErrorCode.INVALID_PARAMETER, f"{name} must be a non-negative integer", field=name)
        visiting.discard(name)
        resolved[name] = q
        return q

    for name in raw:
        resolve(name, ())
    return resolved, evidence


def _normalize(name: str, p: Param, default_unit: str, evidence: list[ConversionEvidence]) -> float:
    v = float(p.value)
    if not math.isfinite(v):
        raise ShilpaError(ErrorCode.INVALID_PARAMETER, f"non-finite value for {name}", field=name)
    if p.kind == "length":
        unit = p.unit or default_unit
        if unit not in LENGTH_TO_MM:
            raise ShilpaError(ErrorCode.UNIT_MISMATCH, f"{name} is a length but has unit {unit}", field=name)
        out = v * LENGTH_TO_MM[unit]
        if unit != "mm":
            evidence.append(ConversionEvidence(name, v, unit, out, "mm"))
        return out
    if p.kind == "angle":
        unit = p.unit or "deg"
        if unit not in ANGLE_TO_DEG:
            raise ShilpaError(ErrorCode.UNIT_MISMATCH, f"{name} is an angle but has unit {unit}", field=name)
        out = v * ANGLE_TO_DEG[unit]
        if unit != "deg":
            evidence.append(ConversionEvidence(name, v, unit, out, "deg"))
        return out
    if p.unit is not None:
        raise ShilpaError(ErrorCode.UNIT_MISMATCH, f"{name} is a {p.kind} and cannot have unit {p.unit}", field=name)
    return v


def _eval_ref(text: str, params: dict[str, Quantity], feature_id: str, fname: str) -> float:
    try:
        q = expr.evaluate(text, params)
    except ShilpaError as exc:
        exc.info.feature_id, exc.info.field = feature_id, fname
        raise
    want = field_kind(fname)
    # Bare constants are dimensionless, so a length field must reference at least one
    # length parameter. This keeps every dimension named and editable.
    ok = q.kind == want or (want == "count" and q.kind in expr.SCALAR_KINDS)
    if not ok:
        raise ShilpaError(
            ErrorCode.UNIT_MISMATCH,
            f"{fname} expects a {want} but {text!r} is a {q.kind}",
            feature_id=feature_id,
            field=fname,
        )
    if not math.isfinite(q.value):
        raise ShilpaError(ErrorCode.INVALID_PARAMETER, "non-finite value", feature_id=feature_id, field=fname)
    if want == "count" and (q.value != int(q.value) or q.value < 1):
        raise ShilpaError(
            ErrorCode.INVALID_PARAMETER, f"{fname} must be a positive integer", feature_id=feature_id, field=fname
        )
    if fname not in SIGNED_FIELDS and q.value <= 0:
        raise ShilpaError(
            ErrorCode.INVALID_PARAMETER,
            f"{fname} must be greater than zero (got {q.value:g})",
            feature_id=feature_id,
            field=fname,
        )
    return q.value


def _ref_fields(model) -> dict[str, str]:
    return {k: v for k, v in model if k.endswith("_ref") and isinstance(v, str) and not k.endswith(("profile_ref", "body_ref", "target_ref", "tool_ref"))}


def compile_recipe(recipe: Recipe | dict | str, capabilities: set[str] | None = None) -> CompiledRecipe:
    if not isinstance(recipe, Recipe):
        recipe = parse_recipe(recipe)
    if tuple(recipe.frame.origin) != (0, 0, 0) or tuple(recipe.frame.normal) != (0, 0, 1):
        raise ShilpaError(ErrorCode.UNSUPPORTED_OPERATION, "only the default frame (origin 0, +Z normal) is supported")

    params, evidence = resolve_parameters(recipe)
    seen: dict[str, str] = {}  # id -> "sketch" | "body"
    compiled: list[CompiledFeature] = []

    for f in recipe.features:
        if f.id in seen or f.id in params:
            raise ShilpaError(ErrorCode.INVALID_SCHEMA, f"duplicate id {f.id!r}", feature_id=f.id)
        if capabilities is not None and f.op not in capabilities:
            raise ShilpaError(
                ErrorCode.UNSUPPORTED_OPERATION, f"operation {f.op!r} is not supported by this adapter", feature_id=f.id
            )
        for ref_field, want in (("profile_ref", "sketch"), ("body_ref", "body"), ("target_ref", "body"), ("tool_ref", "body")):
            target = getattr(f, ref_field, None)
            if target is None:
                continue
            if target not in seen:
                raise ShilpaError(
                    ErrorCode.UNKNOWN_REFERENCE,
                    f"{ref_field} {target!r} does not name an earlier feature",
                    feature_id=f.id,
                    field=ref_field,
                )
            if seen[target] != want:
                raise ShilpaError(
                    ErrorCode.INVALID_SCHEMA,
                    f"{ref_field} {target!r} is a {seen[target]}, expected a {want}",
                    feature_id=f.id,
                    field=ref_field,
                )
        if getattr(f, "direction", None) in ("positive_z", "negative_z"):
            prof = next(c for c in compiled if c.id == f.profile_ref)
            if prof.spec.plane != "XY":
                raise ShilpaError(
                    ErrorCode.INVALID_SCHEMA, "positive_z/negative_z need an XY sketch", feature_id=f.id, field="direction"
                )
        if getattr(f, "mode", None) == "blind" and getattr(f, "depth_ref", None) is None:
            raise ShilpaError(ErrorCode.INVALID_SCHEMA, "blind holes need depth_ref", feature_id=f.id, field="depth_ref")

        values = {k: _eval_ref(v, params, f.id, k) for k, v in _ref_fields(f).items()}
        if f.op == "stepped_shaft":
            for i, s in enumerate(f.sections):
                values[f"sections.{i}.diameter"] = _eval_ref(s.diameter_ref, params, f.id, "diameter_ref")
                values[f"sections.{i}.length"] = _eval_ref(s.length_ref, params, f.id, "length_ref")
        compiled.append(CompiledFeature(f.id, f.op, f, values))
        seen[f.id] = "sketch" if f.op in SKETCH_OPS else "body"

    bodies = [c.id for c in compiled if seen[c.id] == "body"]
    if not bodies:
        raise ShilpaError(ErrorCode.INVALID_SCHEMA, "recipe produces no solid body")
    output_id = recipe.output or bodies[-1]
    if seen.get(output_id) != "body":
        raise ShilpaError(ErrorCode.UNKNOWN_REFERENCE, f"output {output_id!r} is not a body feature", field="output")

    a = recipe.assertions
    av: dict[str, Any] = {"solid_count": a.solid_count, "valid_brep": a.valid_brep}
    if a.bbox_ref:
        av["bbox"] = [_eval_ref(r, params, "assertions", "bbox_ref") for r in a.bbox_ref]
    if a.volume is not None:
        av["volume"] = a.volume
    if a.holes:
        av["holes"] = [
            {"diameter": _eval_ref(h.diameter_ref, params, "assertions", "diameter_ref"), "count": h.count}
            for h in a.holes
        ]
    return CompiledRecipe(recipe, params, compiled, output_id, evidence, av)
