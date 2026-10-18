"""Structured-output contracts for the planner stages (blueprint section 9)."""

from __future__ import annotations

import copy

from typing import Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from ..contracts.ir import FEATURE_TYPES, SCHEMA_VERSION, Assumption

# The plan schema offers every IR operation; strict mode turns the union into an anyOf keyed by "op".
PlanFeature = Union[FEATURE_TYPES]


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- stage 1: requirements


class Dimension(_S):
    name: str = Field(description="snake_case parameter name, e.g. width, hole_diameter")
    value: float | None = Field(description="numeric value as stated, or null if not stated")
    unit: Literal["mm", "cm", "m", "in", "deg", "rad"] | None
    kind: Literal["length", "angle", "count"]
    critical: bool = Field(description="true if the geometry is undefined without it")
    source: Literal["user", "assumed", "default"]
    evidence: str | None = Field(description="exact words from the request that state this value")


class MissingItem(_S):
    name: str
    question: str = Field(description="short question to ask the engineer")
    critical: bool


class Conflict(_S):
    description: str
    fields: list[str]


class Requirements(_S):
    task_class: Literal["engineering_cad", "visual_asset", "drawing_reconstruction", "native_document_edit", "unsupported"]
    family: Literal["plate", "spacer", "shaft", "flange", "bracket", "enclosure", "other"]
    summary: str = Field(description="one sentence restating the part")
    units: Literal["mm", "cm", "m", "in"] | None
    dimensions: list[Dimension]
    features: list[str] = Field(description="plain-language list of features, e.g. 'four through holes at the corners'")
    assumptions: list[str] = Field(description="engineering conventions applied because the request did not say otherwise")
    missing: list[MissingItem]
    conflicts: list[Conflict]
    unsupported_reason: str | None


# ---------------------------------------------------------------- stage 2: plan (recipe)


class PlanParameter(_S):
    name: str
    value: float
    kind: Literal["length", "angle", "count"]
    unit: Literal["mm", "cm", "m", "in", "deg", "rad"] | None
    source: Literal["user", "assumed", "default", "derived"]


class PlanOutput(_S):
    """Strict-mode friendly shape of a Recipe. Converted with ``to_recipe``."""

    name: str
    units: Literal["mm", "cm", "m", "in"]
    parameters: list[PlanParameter]
    features: list[PlanFeature]
    expected_bbox_refs: list[str] | None = Field(description="three refs for the X, Y, Z overall size, or null")
    assumptions: list[Assumption]
    change_summary: str | None = Field(description="for edits and repairs: what changed and why")


def to_recipe(plan: dict) -> dict:
    params = {}
    for p in plan.get("parameters", []):
        entry = {"value": p["value"], "kind": p["kind"], "source": p.get("source") or "user"}
        if p.get("unit"):
            entry["unit"] = p["unit"]
        if entry["kind"] != "length" or entry["source"] != "user" or "unit" in entry:
            params[p["name"]] = entry
        else:
            params[p["name"]] = p["value"]
    # Strict mode makes every optional field an explicit null; nested segments, face selectors,
    # edge selectors and shaft sections carry them too.
    features = [_drop_nulls(f) for f in plan.get("features", [])]
    recipe = {
        "schema_version": SCHEMA_VERSION,
        "name": plan.get("name"),
        "intent": "engineering_cad",
        "units": plan.get("units") or "mm",
        "parameters": params,
        "features": features,
        "assumptions": plan.get("assumptions") or [],
        "assertions": {"solid_count": 1, "valid_brep": True},
    }
    bbox = plan.get("expected_bbox_refs")
    if bbox and len(bbox) == 3:
        recipe["assertions"]["bbox_ref"] = bbox
    return recipe


def _drop_nulls(node):
    if isinstance(node, dict):
        return {k: _drop_nulls(v) for k, v in node.items() if v is not None}
    if isinstance(node, list):
        return [_drop_nulls(v) for v in node]
    return node


def from_recipe(recipe: dict) -> dict:
    """Inverse of to_recipe, used to show the planner the current state for edits and repairs.

    Returns an independent copy: callers may modify it without touching the recipe.
    """
    recipe = copy.deepcopy(recipe)
    params = []
    for name, v in recipe["parameters"].items():
        if isinstance(v, dict):
            params.append({"name": name, "value": v.get("value"), "kind": v.get("kind", "length"),
                           "unit": v.get("unit"), "source": v.get("source", "user")})
        else:
            params.append({"name": name, "value": v, "kind": "length", "unit": None, "source": "user"})
    return {
        "name": recipe.get("name"),
        "units": recipe.get("units", "mm"),
        "parameters": params,
        "features": recipe["features"],
        "expected_bbox_refs": (recipe.get("assertions") or {}).get("bbox_ref"),
        "assumptions": recipe.get("assumptions", []),
    }
