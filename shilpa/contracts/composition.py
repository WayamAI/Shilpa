"""Composition IR 0.1: the typed program a composition prompt becomes (Shilpa Composition Language, spec section 4).

A prompt is parsed into ``Step`` records. Each step is one operation (``add``, ``ground``,
``place``, ``mate``, ``insert``; the other ops are in the schema but planned for later
phases). Steps refer to parts and features with ``Ref`` records whose ids were resolved
deterministically from @-mentions; selectors such as ``holes[*]`` with filters are kept as
selectors (re-evaluated on every run), with ``expected_count`` recording the count the user
approved.

The LLM may *propose* steps, but it never computes geometry (``Qty.mm`` is always
recomputed by ``shilpa.compose.units``) and never picks between ambiguous targets (the
resolver turns ambiguity into a blocker). Replay of an IR with pinned versions is fully
deterministic: ``shilpa.compose.lower`` turns it into the existing ``AssemblySpec``.

The JSON Schema is generated from these models into ``schemas/composition-ir-0.1.json``
(``python -m shilpa.contracts.composition`` rewrites it).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

IR_VERSION = "0.1"

Op = Literal["add", "ground", "place", "mate", "insert", "fasten", "pattern", "mirror", "repeat", "constraint",
             "replace", "remove", "promote", "clarify"]
P0_OPS = {"add", "ground", "place", "mate", "insert", "clarify"}
CompareOp = Literal["=", "<", ">", "<=", ">=", "≈"]
PredicateAttr = Literal["diameter", "depth", "length", "area", "x", "y", "z", "normal", "kind", "thread", "on"]
Unit = Literal["mm", "cm", "m", "in", "ft", "deg", "rad"]
Provenance = Literal["user", "assumed", "derived", "default"]
MateKind = Literal["coincident", "coaxial", "parallel", "perpendicular", "tangent", "fixed", "revolute", "slider",
                   "cylindrical", "ball", "planar", "screw"]
MateIntent = Literal["welded", "bolted", "press_fit", "clearance", "contact"]
WorldDir = Literal["+X", "-X", "+Y", "-Y", "+Z", "-Z"]
Anchor = Literal["origin", "center", "port", "bbox_min", "bbox_max"]
Seat = Literal["entry", "exit", "mid", "flush_top", "flush_bottom"]
RefSource = Literal["catalog", "native", "instance"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Predicate(_Strict):
    """One filter term: ``diameter ≈ 6.4 mm``, ``kind = through``, ``on @plate.face.top``."""

    attr: PredicateAttr
    op: CompareOp = "="
    value: float | str
    unit: Unit | None = None
    tol: float | None = Field(default=None, ge=0)


class Selector(_Strict):
    path: str | None = Field(default=None, max_length=200)  # "holes[*]", "face.top", "axis.main"
    filter: list[Predicate] = Field(default_factory=list, max_length=8)
    expected_count: int | None = Field(default=None, ge=0, le=500)


class Ref(_Strict):
    """A resolved reference. ``mention`` links it to the prompt's mention table (m1, m2 ...)."""

    text: str = Field(max_length=300)
    mention: str | None = Field(default=None, max_length=16)
    source: RefSource | None = None  # what the part part of the reference resolved to
    item: str | None = Field(default=None, max_length=200)  # native: model id; catalog: "catalog:<generator>"
    version: str | None = Field(default=None, max_length=80)  # native: pinned ModelVersion id; catalog: params hash
    generator: str | None = Field(default=None, max_length=100)
    params: dict[str, Any] | None = None
    instance: str | None = Field(default=None, max_length=64)  # an instance already in the composition
    feature_uid: str | None = Field(default=None, max_length=200)
    selector: Selector | None = None


class Qty(_Strict):
    value: float
    unit: Unit = "mm"
    mm: float | None = None  # normalised (degrees for angles); always recomputed, never trusted from the LLM
    as_typed: str | None = Field(default=None, max_length=40)
    provenance: Provenance = "user"
    confirmed: bool = False  # the user kept a value the plausibility check questioned


class Direction(_Strict):
    """Exactly one of the four forms."""

    world: WorldDir | None = None
    normal_of: Ref | None = None
    along: Ref | None = None
    away_from: Ref | None = None

    @model_validator(mode="after")
    def _one(self):
        given = [k for k in ("world", "normal_of", "along", "away_from") if getattr(self, k) is not None]
        if len(given) != 1:
            raise ValueError(f"direction needs exactly one of world, normal_of, along, away_from; got {given or 'none'}")
        return self


class Offset(_Strict):
    distance: Qty
    direction: Direction | None = None
    from_: Ref | None = Field(default=None, alias="from")  # measure from this feature (e.g. a shaft end)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class MateSpec(_Strict):
    kind: MateKind
    flip: bool = False
    angle: Qty | None = None
    limits: list[Qty] | None = Field(default=None, min_length=2, max_length=2)
    intent: MateIntent | None = None


class Assumption(_Strict):
    field: str = Field(max_length=120)
    value: Any = None
    reason: str = Field(max_length=500)


class Patch(_Strict):
    """One deterministic edit an answer applies: set fields on a step, acknowledge a warning, or add a step."""

    step: str | None = None
    set: dict[str, Any] = Field(default_factory=dict)  # dotted path -> value, e.g. "target.selector.filter"
    acknowledge: str | None = None  # a blocker code the user accepts (it becomes a recorded warning)
    append_step: dict[str, Any] | None = None


class ClarifyOption(_Strict):
    label: str = Field(max_length=200)
    patch: list[Patch] = Field(default_factory=list)


class Clarify(_Strict):
    question: str = Field(max_length=500)
    field: str | None = None
    options: list[ClarifyOption] = Field(default_factory=list, max_length=8)
    blocking: bool = True


class Step(_Strict):
    id: str = Field(pattern=r"^s[0-9]{1,4}$")
    op: Op
    prompt: str = Field(default="", max_length=8000)
    enabled: bool = True
    source: Ref | None = None
    target: Ref | None = None
    quantity: int | None = Field(default=None, ge=1, le=200)
    mate: MateSpec | None = None
    offset: Offset | None = None
    anchor: Anchor | None = None
    source_port: str | None = Field(default=None, max_length=64)
    seat: Seat | None = None
    assumptions: list[Assumption] = Field(default_factory=list)
    clarify: Clarify | None = None
    acknowledged: list[str] = Field(default_factory=list)  # blocker codes the user chose to continue past

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class CompositionIR(_Strict):
    ir_version: Literal["0.1"] = IR_VERSION
    composition_id: str
    base_version: str | None = None  # ModelVersion this applies to (409 when stale)
    units: Literal["mm"] = "mm"
    steps: list[Step] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def _unique_ids(self):
        ids = [s.id for s in self.steps]
        dup = sorted({i for i in ids if ids.count(i) > 1})
        if dup:
            raise ValueError(f"duplicate step ids: {dup}")
        return self


def json_schema() -> dict:
    schema = CompositionIR.model_json_schema(by_alias=True)
    schema["$id"] = f"shilpa/composition-ir/{IR_VERSION}"
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return schema


SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / f"composition-ir-{IR_VERSION}.json"


def schema_text() -> str:
    return json.dumps(json_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_PATH.write_text(schema_text(), encoding="utf-8")
    print(f"wrote {SCHEMA_PATH}")
