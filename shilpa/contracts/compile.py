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
from . import iso_holes, profile2d
from .ir import HOLE_OPS, PATH_OPS, SKETCH_OPS, Param, Recipe

LENGTH_TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}
ANGLE_TO_DEG = {"deg": 1.0, "rad": 180.0 / math.pi}

# Reference fields that may be zero or negative. Everything else must be > 0.
SIGNED_FIELDS = {"center_x_ref", "center_y_ref", "offset_ref", "start_angle_ref", "rotation_angle_ref",
                 "start_x_ref", "start_y_ref", "x_ref", "y_ref", "mid_x_ref", "mid_y_ref"}
# Fields that name other features rather than holding a dimension.
FEATURE_REF_FIELDS = ("profile_ref", "body_ref", "target_ref", "tool_ref", "path_ref")
# Sketch axes each plane contains (revolve axes must lie in the sketch plane).
PLANE_AXES = {"XY": ("X", "Y"), "XZ": ("X", "Z"), "YZ": ("Y", "Z")}
# May be zero (a pitch along an axis with one hole); negative is still invalid.
NON_NEGATIVE_FIELDS = {"pitch_x_ref", "pitch_y_ref"}


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
    meta: dict[str, Any] = field(default_factory=dict)  # non-geometric facts, e.g. a tapped hole's thread
    segments: list[profile2d.Seg] | None = None  # profiles and paths: resolved exact geometry


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
    if fname in NON_NEGATIVE_FIELDS and q.value < 0:
        raise ShilpaError(ErrorCode.INVALID_PARAMETER, f"{fname} cannot be negative (got {q.value:g})",
                          feature_id=feature_id, field=fname)
    if fname not in SIGNED_FIELDS and fname not in NON_NEGATIVE_FIELDS and q.value <= 0:
        raise ShilpaError(
            ErrorCode.INVALID_PARAMETER,
            f"{fname} must be greater than zero (got {q.value:g})",
            feature_id=feature_id,
            field=fname,
        )
    return q.value


def _ref_fields(model) -> dict[str, str]:
    return {k: v for k, v in model if k.endswith("_ref") and isinstance(v, str) and not k.endswith(FEATURE_REF_FIELDS)}


def _schema_error(msg: str, fid: str, fname: str | None = None) -> ShilpaError:
    return ShilpaError(ErrorCode.INVALID_SCHEMA, msg, feature_id=fid, field=fname)


def _compile_segments(f, params, values: dict[str, float]) -> list[profile2d.Seg]:
    """Evaluate a profile's or path's segments and resolve them into exact lines and arcs."""
    need = {"line": (), "arc": ("mid_x_ref", "mid_y_ref"), "tangent_arc": (), "radius_arc": ("radius_ref",)}
    resolved = []
    for i, s in enumerate(f.segments):
        given = {k for k in ("mid_x_ref", "mid_y_ref", "radius_ref") if getattr(s, k) is not None}
        if given != set(need[s.kind]):
            want = ", ".join(need[s.kind]) or "no mid point or radius"
            raise _schema_error(f"segment {i} ({s.kind}) takes {want}", f.id, f"segments.{i}")
        seg = {"kind": s.kind, "clockwise": s.clockwise}
        for k, v in s:
            if k.endswith("_ref") and v is not None:
                seg[k[:-4]] = values[f"segments.{i}.{k[:-4]}"] = _eval_ref(v, params, f.id, k)
        resolved.append(seg)
    start = (values["start_x_ref"], values["start_y_ref"])
    segs = profile2d.resolve(start, resolved, closed=f.op == "profile", fid=f.id)
    if f.op == "path":
        profile2d.require_smooth(segs, f.id)
    return segs


def _compile_hole_series(f, values: dict[str, float]) -> dict[str, Any]:
    """Fill hole-series dimensions from the ISO table where no explicit ref was given, and check them."""
    std = iso_holes.lookup(f.standard_size) if f.standard_size else None
    kind = f.hole_type
    extra = {"counterbore": ("cbore_diameter_ref", "cbore_depth_ref"), "countersink": ("csk_diameter_ref", "csk_angle_ref"),
             "tapped": ("thread_depth_ref",), "simple": ()}
    for k in ("cbore_diameter_ref", "cbore_depth_ref", "csk_diameter_ref", "csk_angle_ref", "thread_depth_ref"):
        if getattr(f, k) is not None and k not in extra[kind]:
            raise _schema_error(f"{k} does not apply to a {kind} hole", f.id, k)

    def need(key: str, table_value: float | None, what: str) -> None:
        if key in values:
            return
        if table_value is None:
            hint = f" ({f.standard_size} has no {what} in the table)" if std else " or give standard_size"
            raise _schema_error(f"{key} is required for a {kind} hole{hint}", f.id, key)
        values[key] = table_value

    need("diameter_ref", (std.tap_drill if kind == "tapped" else std.clearance[f.fit]) if std else None, "diameter")
    d = values["diameter_ref"]
    meta: dict[str, Any] = {}
    if kind == "counterbore":
        need("cbore_diameter_ref", std.cbore_diameter if std else None, "counterbore")
        need("cbore_depth_ref", std.cbore_depth if std else None, "counterbore")
        if values["cbore_diameter_ref"] <= d:
            raise _schema_error("counterbore diameter must be larger than the hole diameter", f.id, "cbore_diameter_ref")
        if f.mode == "blind" and values["cbore_depth_ref"] >= values["depth_ref"]:
            raise _schema_error("counterbore depth must be less than the hole depth", f.id, "cbore_depth_ref")
    elif kind == "countersink":
        need("csk_diameter_ref", std.csk_diameter if std else None, "countersink")
        values.setdefault("csk_angle_ref", std.csk_angle if std else 90.0)
        if values["csk_diameter_ref"] <= d:
            raise _schema_error("countersink diameter must be larger than the hole diameter", f.id, "csk_diameter_ref")
        if not 0 < values["csk_angle_ref"] < 180:
            raise _schema_error("countersink angle must be between 0 and 180 degrees", f.id, "csk_angle_ref")
        csk_depth = (values["csk_diameter_ref"] - d) / 2 / math.tan(math.radians(values["csk_angle_ref"] / 2))
        if f.mode == "blind" and csk_depth >= values["depth_ref"]:
            raise _schema_error("countersink is deeper than the hole", f.id, "csk_diameter_ref")
        values["csk_depth"] = csk_depth
    elif kind == "tapped":
        if std is None:
            raise _schema_error("tapped holes need standard_size (the thread spec comes from it)", f.id, "standard_size")
        meta["thread"] = std.thread
        meta["thread_standard"] = "ISO 261 coarse, tap drill ISO 2306"
        if "thread_depth_ref" in values:
            if f.mode == "blind" and values["thread_depth_ref"] > values["depth_ref"]:
                raise _schema_error("thread depth exceeds the hole depth", f.id, "thread_depth_ref")
            meta["thread_depth"] = values["thread_depth_ref"]
    if std:
        meta["standard_size"] = std.size
    return meta


def compile_recipe(recipe: Recipe | dict | str, capabilities: set[str] | None = None) -> CompiledRecipe:
    if not isinstance(recipe, Recipe):
        recipe = parse_recipe(recipe)
    if tuple(recipe.frame.origin) != (0, 0, 0) or tuple(recipe.frame.normal) != (0, 0, 1):
        raise ShilpaError(ErrorCode.UNSUPPORTED_OPERATION, "only the default frame (origin 0, +Z normal) is supported")

    params, evidence = resolve_parameters(recipe)
    seen: dict[str, str] = {}  # id -> "sketch" | "path" | "body"
    compiled: list[CompiledFeature] = []
    by_id: dict[str, CompiledFeature] = {}

    for f in recipe.features:
        if f.id in seen or f.id in params:
            raise ShilpaError(ErrorCode.INVALID_SCHEMA, f"duplicate id {f.id!r}", feature_id=f.id)
        if capabilities is not None and f.op not in capabilities:
            raise ShilpaError(
                ErrorCode.UNSUPPORTED_OPERATION, f"operation {f.op!r} is not supported by this adapter", feature_id=f.id
            )
        refs = [(r, getattr(f, r, None), want) for r, want in (("profile_ref", "sketch"), ("body_ref", "body"), ("target_ref", "body"),
                                                                ("tool_ref", "body"), ("path_ref", "path"))]
        refs += [(f"profile_refs.{i}", t, "sketch") for i, t in enumerate(getattr(f, "profile_refs", None) or [])]
        for ref_field, target, want in refs:
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
        meta: dict[str, Any] = {}
        segments = None
        edges = getattr(f, "edges", None)
        if edges is not None and edges.diameter_ref:
            values["edges.diameter"] = _eval_ref(edges.diameter_ref, params, f.id, "diameter_ref")
        if f.op == "stepped_shaft":
            for i, s in enumerate(f.sections):
                values[f"sections.{i}.diameter"] = _eval_ref(s.diameter_ref, params, f.id, "diameter_ref")
                values[f"sections.{i}.length"] = _eval_ref(s.length_ref, params, f.id, "length_ref")
        elif f.op in ("profile", "path"):
            segments = _compile_segments(f, params, values)
        elif f.op in HOLE_OPS:
            meta = _compile_hole_series(f, values)
        elif f.op == "circle" and "inner_diameter_ref" in values and values["inner_diameter_ref"] >= values["diameter_ref"]:
            raise _schema_error("inner_diameter must be smaller than diameter", f.id, "inner_diameter_ref")
        elif f.op == "revolve":
            prof = by_id[f.profile_ref]
            if f.axis not in PLANE_AXES[prof.spec.plane]:
                raise _schema_error(f"revolve axis {f.axis} does not lie in the {prof.spec.plane} plane of {f.profile_ref!r}; "
                                    f"use one of {PLANE_AXES[prof.spec.plane]}", f.id, "axis")
            if prof.values.get("offset_ref"):
                raise _schema_error("a revolved sketch must not be offset from its plane (the axis must lie in it)", f.id, "profile_ref")
            if values.get("angle_ref", 360.0) > 360.0 + 1e-9:
                raise _schema_error("revolve angle cannot exceed 360 degrees", f.id, "angle_ref")
        elif f.op == "loft":
            profs = [by_id[p] for p in f.profile_refs]
            if len({p.spec.plane for p in profs}) != 1:
                raise _schema_error("loft sections must all be on the same plane type", f.id, "profile_refs")
            offs = [p.values.get("offset_ref", 0.0) for p in profs]
            if any(b <= a + 1e-9 for a, b in zip(offs, offs[1:])):
                raise _schema_error(f"loft sections must have strictly increasing offset_ref (got {offs})", f.id, "profile_refs")
        elif f.op == "sweep":
            if by_id[f.path_ref].op == "helix" and by_id[f.profile_ref].spec.plane != "XZ":
                raise _schema_error("a helical sweep needs its profile on the XZ plane", f.id, "profile_ref")
        elif f.op == "polar_pattern" and values.get("angle_ref", 360.0) > 360.0 + 1e-9:
            raise _schema_error("polar pattern angle cannot exceed 360 degrees", f.id, "angle_ref")
        cf = CompiledFeature(f.id, f.op, f, values, meta, segments)
        compiled.append(cf)
        by_id[f.id] = cf
        seen[f.id] = "sketch" if f.op in SKETCH_OPS else "path" if f.op in PATH_OPS else "body"

    bodies = [c.id for c in compiled if seen[c.id] == "body"]
    if not bodies:
        raise ShilpaError(ErrorCode.INVALID_SCHEMA, "recipe produces no solid body")
    output_id = recipe.output or bodies[-1]
    if seen.get(output_id) != "body":
        raise ShilpaError(ErrorCode.UNKNOWN_REFERENCE, f"output {output_id!r} is not a body feature", field="output")
    # Every body must contribute to the output; otherwise part of the request is silently dropped.
    inputs = {c.id: [getattr(c.spec, r) for r in ("body_ref", "target_ref", "tool_ref") if getattr(c.spec, r, None)]
              for c in compiled if seen[c.id] == "body"}
    reached, stack = set(), [output_id]
    while stack:
        cur = stack.pop()
        if cur not in reached:
            reached.add(cur)
            stack.extend(inputs.get(cur, []))
    dangling = [b for b in bodies if b not in reached]
    if dangling:
        raise ShilpaError(ErrorCode.INVALID_SCHEMA,
                          f"bodies {dangling} are built but never become part of the output {output_id!r}; "
                          "Shilpa makes one connected part per request", field="features", details={"dangling": dangling})

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
