"""Product planner: a text request becomes template choices, never geometry (roadmap S4, the LLM's job).

The model reads the request and picks a product template, sizes, wheel size,
use case, interface standards and a few skeleton overrides, through one
structured-output call (``llm.call_structured``). Everything geometric follows
deterministically from the template (``shilpa/product/templates``): the model
cannot place a tube or size a bearing. Requests outside the known templates
come back as an explicit "unsupported product class" with the supported list,
not an improvised design.

Provenance: fields the request states are tagged ``user`` in the skeleton,
fields the model filled in are tagged ``llm``.

``parse_request_offline`` is the no-LLM path: a few regular-expression rules
(rider height in cm / m / ft-in, inseam, 700c / 650b, road / gravel, tyre
width, size words, 1x / 2x, quick release) produce the same ``PlannerResult``,
so the product flow can be demonstrated and tested without Azure. It refuses
non-bicycle requests the same way the model is told to.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..contracts.errors import ErrorCode, ShilpaError
from ..product.templates import SUPPORTED
from ..product.templates.bicycle import SIZE_TABLE, BicycleChoices
from .llm import Budget, call_structured, strict_schema

OverrideKey = Literal["stack", "reach", "head_angle", "seat_angle", "chainstay_length", "bb_drop", "fork_offset",
                      "stem_length", "stem_angle", "bar_width", "spacer_stack", "steer_lock", "max_tyre_width", "q_factor"]
ChoiceField = Literal["use_case", "frame_size", "rider_height_cm", "rider_inseam_cm", "wheel_size", "tyre_width_mm",
                      "bb_standard", "rear_axle", "front_axle", "crank_length_mm", "chainrings"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlannerOverride(_Strict):
    key: OverrideKey
    value: float
    reason: str


class ProductPlan(_Strict):
    """The model's answer. Optional fields left null fall back to the template's table or defaults."""

    supported: bool
    product_class: str = Field(description="what was asked for, in one or two words, e.g. 'bicycle', 'drone'")
    template: Literal["bicycle.diamond_v1"] | None
    unsupported_reason: str | None
    use_case: Literal["road", "gravel"] | None
    frame_size: Literal["XS", "S", "M", "L", "XL", "XXL"] | None
    rider_height_cm: float | None
    rider_inseam_cm: float | None
    wheel_size: Literal["700c", "650b"] | None
    tyre_width_mm: float | None
    bb_standard: Literal["BSA68", "BSA73"] | None
    rear_axle: Literal["12x142", "135x10qr"] | None
    front_axle: Literal["12x100", "100x9qr"] | None
    crank_length_mm: float | None
    chainrings: list[int] | None
    overrides: list[PlannerOverride]
    stated_by_user: list[ChoiceField] = Field(description="choice fields the request states explicitly")
    assumptions: list[str]


def _size_rows() -> str:
    return "\n".join(f"  {s}: rider {r[0]:g}-{r[1]:g} cm, stack {r[2]:g}, reach {r[3]:g}" for s, r in SIZE_TABLE.items())


SYSTEM = f"""You are the product planner of Shilpa, an engineering CAD agent.
You turn a product request into TEMPLATE CHOICES. You never design geometry: a deterministic template
builds the skeleton, frame, fork, standard parts and checks from your choices.

Supported product templates (anything else is unsupported):
{chr(10).join(f"- {k}: {v}" for k, v in SUPPORTED.items())}

If the request is not for a product one of these templates makes (for example a drone, a motorbike, an
e-bike motor, a tandem, a full-suspension mountain bike, a chair), answer supported=false, template=null,
set product_class to what was asked for and explain briefly in unsupported_reason. Leave the other choice
fields null and overrides empty.

For bicycles choose:
- use_case: road (default) or gravel (mixed surfaces, "gravel", "adventure", wide tyres).
- frame_size or rider_height_cm. If the request names a size, set frame_size; if it gives a height, set
  rider_height_cm (the template's sizing table then picks the size unless a size is also named). Sizing table:
{_size_rows()}
  A very tall or short rider outside the table still gets the nearest size (the template reports it).
- wheel_size: 700c or 650b. tyre_width_mm: ETRTO width in mm when the request says it (e.g. "45 mm tyres"),
  otherwise null (road 28, gravel 40 at 700c / 47 at 650b by default).
- standards: bb_standard BSA68 (default; BSA73 only if asked), rear_axle 12x142 (default thru-axle) or
  135x10qr, front_axle 12x100 (default) or 100x9qr. chainrings: e.g. [50, 34] road double, [40] gravel 1x;
  null for the default. crank_length_mm only if asked or clearly implied.
- overrides: only for explicit geometry requests the template exposes (e.g. "slacker head angle 70" ->
  head_angle 70). Each needs a reason. Do not invent overrides.
- stated_by_user: list the choice fields the request itself states; the rest are your assumptions.
- assumptions: short notes on anything you inferred.
"""


@dataclass
class PlannerResult:
    ok: bool
    supported: bool
    message: str
    plan: dict | None = None
    choices: BicycleChoices | None = None
    usage: list[dict] = field(default_factory=list)
    seconds: float = 0.0

    def to_dict(self) -> dict:
        return {"ok": self.ok, "supported": self.supported, "message": self.message, "plan": self.plan,
                "choices": self.choices.model_dump() if self.choices else None, "usage": self.usage,
                "seconds": round(self.seconds, 1)}


def plan_to_choices(plan: ProductPlan, text: str) -> BicycleChoices:
    """Map the model's plan onto the template's typed choices (pydantic re-validates every value)."""
    kw = {k: getattr(plan, k) for k in ("use_case", "frame_size", "rider_height_cm", "rider_inseam_cm", "wheel_size",
                                         "tyre_width_mm", "bb_standard", "rear_axle", "front_axle", "crank_length_mm",
                                         "chainrings") if getattr(plan, k) is not None}
    notes = list(plan.assumptions) + [f"override {o.key}={o.value:g}: {o.reason}" for o in plan.overrides]
    llm_fields = [k for k in kw if k not in plan.stated_by_user]
    return BicycleChoices(**kw, overrides={o.key: o.value for o in plan.overrides}, text=text, notes=notes,
                          llm_fields=llm_fields)


def unsupported_message(product_class: str, reason: str | None = None) -> str:
    supported = "; ".join(f"{k} ({v})" for k, v in SUPPORTED.items())
    return (f"unsupported product class {product_class!r}" + (f": {reason}" if reason else "") +
            f". Supported templates: {supported}.")


def plan_product(text: str, budget: Budget | None = None, timeout_s: float = 120.0) -> PlannerResult:
    t0 = time.perf_counter()
    budget = budget or Budget(input_tokens=40_000, output_tokens=8_000, deadline=time.time() + timeout_s + 30)
    schema = strict_schema(ProductPlan.model_json_schema())
    data = call_structured(system=SYSTEM, user=text, schema_name="product_plan", schema=schema, budget=budget,
                           max_output_tokens=3000, purpose="product_plan", timeout_s=timeout_s)
    try:
        plan = ProductPlan.model_validate(data)
    except ValidationError as exc:
        raise ShilpaError(ErrorCode.INVALID_SCHEMA, f"product plan does not match its schema: {exc.errors()[0]['msg']}")
    if not plan.supported or plan.template is None:
        return PlannerResult(True, False, unsupported_message(plan.product_class, plan.unsupported_reason),
                             plan.model_dump(), None, budget.calls, time.perf_counter() - t0)
    try:
        choices = plan_to_choices(plan, text)
    except (ValidationError, ValueError) as exc:
        return PlannerResult(False, True, f"planner choices rejected by the template: {exc}", plan.model_dump(), None,
                             budget.calls, time.perf_counter() - t0)
    return PlannerResult(True, True, f"{plan.template}: {plan.use_case or 'road'} "
                         f"{plan.frame_size or (str(plan.rider_height_cm) + ' cm rider' if plan.rider_height_cm else '')} "
                         f"{plan.wheel_size or '700c'}".strip(), plan.model_dump(), choices, budget.calls,
                         time.perf_counter() - t0)


# ---------------------------------------------------------------- offline (no LLM) parser

_BIKE = re.compile(r"\b(bi(?:ke|cycle)s?|cycle|frameset)\b", re.I)
# Product classes the bicycle template must not improvise, even when the word "bike" appears.
_UNSUPPORTED = re.compile(r"\b(drone|quad-?copter|multi-?rotor|uav|car|motor\s*bike|motorbike|motorcycle|scooter|e-?bike|"
                          r"electric|tandem|tricycle|trike|unicycle|full[-\s]*suspension|mtb|mountain\s*bike|chair|table|"
                          r"robot|enclosure|conveyor)\b", re.I)
_SIZE_WORDS = [(r"\bsize\s+(xxl|xl|xs|s|m|l)\b", None), (r"\b(xxl|2xl|extra[-\s]*extra[-\s]*large)\b", "XXL"),
               (r"\b(xl|extra[-\s]*large)\b", "XL"), (r"\b(xs|extra[-\s]*small)\b", "XS"), (r"\b(large)\b", "L"),
               (r"\b(medium|mid-?size)\b", "M"), (r"\b(small)\b", "S")]
_NUM = r"(\d+(?:[.,]\d+)?)"


def _f(x: str) -> float:
    return float(x.replace(",", "."))


def parse_request_offline(text: str) -> PlannerResult:
    """Rule-based request parser (no model call), with the same result shape as ``plan_product``.

    Recognises rider height ("178 cm", "1.85 m", "2 m rider", "6 ft 1"), inseam ("inseam 84 cm"),
    wheel size ("700c", "700x32", "29er" -> 700c; "650b", "27.5" -> 650b), use case ("gravel",
    "adventure", "all-road", "cx" -> gravel; "road", "endurance", "race" -> road), tyre width
    ("45 mm tyres", "tires 32mm", "700x32c"), frame-size words (XS ... XXL, "small", "medium"),
    "1x" / "2x" drivetrains, "quick release" axles, BSA73 and crank length ("172.5 mm cranks").
    Everything matched is user-stated; the rest falls back to the template's sizing table and defaults.
    """
    t0 = time.perf_counter()
    low = text.lower()
    found: dict = {}
    matched: dict[str, str] = {}
    bad = _UNSUPPORTED.search(low)
    if bad or not _BIKE.search(low):
        if bad:
            what, reason = bad.group(1), f"{bad.group(1)!r} is not something the diamond-frame bicycle template makes"
        else:
            words = re.sub(r"^(please\s+)?(design|make|build|create|draw|model)\s+(me\s+)?(an?\s+|the\s+)?", "", low.strip()).split()
            what, reason = " ".join(words[:3]) or "unknown", "the request does not ask for a bicycle"
        plan = {"supported": False, "product_class": what, "template": None, "unsupported_reason": reason, "parser": "offline"}
        return PlannerResult(True, False, unsupported_message(what, reason), plan, None, [], time.perf_counter() - t0)

    rest = low
    if m := re.search(r"inseam\D{0,12}" + _NUM + r"\s*(cm|mm|in(?:ch(?:es)?)?\b|\")", low):
        v, u = _f(m.group(1)), m.group(2)
        found["rider_inseam_cm"] = round(v / 10 if u == "mm" else v * 2.54 if u.startswith(("in", '"')) else v, 1)
        matched["rider_inseam_cm"] = m.group(0)
        rest = low[:m.start()] + " " + low[m.end():]
    if m := re.search(_NUM + r"\s*cm\b", rest):
        if 100 < _f(m.group(1)) < 230:
            found["rider_height_cm"], matched["rider_height_cm"] = _f(m.group(1)), m.group(0)
    elif m := re.search(_NUM + r"\s*(?:m|metres?|meters?)\b", rest):
        if 1.0 < _f(m.group(1)) < 2.3:
            found["rider_height_cm"], matched["rider_height_cm"] = round(_f(m.group(1)) * 100, 1), m.group(0)
    elif m := re.search(r"\b(\d)\s*(?:ft|foot|feet|')\s*(\d{1,2})?", rest):
        cm = (int(m.group(1)) * 12 + int(m.group(2) or 0)) * 2.54
        if 100 < cm < 230:
            found["rider_height_cm"], matched["rider_height_cm"] = round(cm, 1), m.group(0)

    if m := re.search(r"\b(650\s*b|27\.5|584)(?![\d.])", low):
        found["wheel_size"], matched["wheel_size"] = "650b", m.group(0)
    elif m := re.search(r"\b(700\s*c?|29er|622)(?!\d)", low):
        found["wheel_size"], matched["wheel_size"] = "700c", m.group(0)

    if m := re.search(r"\b(gravel|adventure|all[-\s]*road|cx|cyclo-?cross|bikepacking)\b", low):
        found["use_case"], matched["use_case"] = "gravel", m.group(0)
    elif m := re.search(r"\b(road|endurance|race|racing)\b", low):
        found["use_case"], matched["use_case"] = "road", m.group(0)

    tyre = (re.search(r"\b(?:700|650b?)\s*[x×]\s*" + _NUM + r"\s*c?\b", low)
            or re.search(_NUM + r"\s*mm\s*(?:wide\s*)?(?:tyres?|tires?|rubber)", low)
            or re.search(r"(?:tyres?|tires?)\D{0,12}" + _NUM + r"\s*mm", low))
    if tyre and 20 <= _f(tyre.group(1)) <= 60:
        found["tyre_width_mm"], matched["tyre_width_mm"] = _f(tyre.group(1)), tyre.group(0)

    for pat, size in _SIZE_WORDS:
        if m := re.search(pat, low):
            found["frame_size"], matched["frame_size"] = size or m.group(1).upper(), m.group(0)
            break

    if m := re.search(r"\b1\s*x\b|\bsingle\s*(?:ring|chainring)\b", low):
        found["chainrings"], matched["chainrings"] = [40], m.group(0)
    elif m := re.search(r"\b2\s*x\b|\bdouble\b|\bcompact\b", low):
        found["chainrings"], matched["chainrings"] = [50, 34], m.group(0)
    if m := re.search(r"quick[-\s]*release|\bqr\b", low):
        found["rear_axle"], found["front_axle"] = "135x10qr", "100x9qr"
        matched["rear_axle"] = matched["front_axle"] = m.group(0)
    if m := re.search(r"\bbsa\s*73\b|\b73\s*mm\s*(?:bb|bottom bracket|shell)", low):
        found["bb_standard"], matched["bb_standard"] = "BSA73", m.group(0)
    if m := re.search(_NUM + r"\s*mm\s*cranks?", low):
        if 150 <= _f(m.group(1)) <= 185:
            found["crank_length_mm"], matched["crank_length_mm"] = _f(m.group(1)), m.group(0)

    notes = [f"offline parser: {k} from {v.strip()!r}" for k, v in matched.items()]
    plan = {"supported": True, "product_class": "bicycle", "template": "bicycle.diamond_v1", "unsupported_reason": None,
            **found, "overrides": [], "stated_by_user": sorted(found), "assumptions": notes, "parser": "offline"}
    try:
        choices = BicycleChoices(**found, text=text, notes=notes)
    except (ValidationError, ValueError) as exc:
        return PlannerResult(False, True, f"parsed choices rejected by the template: {exc}", plan, None, [],
                             time.perf_counter() - t0)
    who = found.get("frame_size") or (f"{found['rider_height_cm']:g} cm rider" if "rider_height_cm" in found else "")
    desc = " ".join(x for x in (found.get("use_case", "road"), who, found.get("wheel_size", "700c")) if x)
    return PlannerResult(True, True, f"bicycle.diamond_v1: {desc} (offline parser)", plan, choices, [],
                         time.perf_counter() - t0)
