"""Rollback router for template products (roadmap layer 5: "is the error in the code or in the design?").

When a product check fails, the router decides who is responsible and, where a
deterministic repair exists, applies it to the skeleton and rebuilds:

* **part-level**: one part's parameters are wrong but the skeleton is fine
  (seatpost too short for the fitted saddle height, crankset chainline off the
  cassette line). The part's parameter changes; the frame does not.
* **design-level**: the skeleton itself cannot satisfy the check (a tyre wider
  than the frame was designed for, a fork crown too low, chainstays too short,
  a steering stop past the point where the tyre meets the down tube). A
  skeleton value changes and everything derived from it is re-derived, so the
  head tube shortens when the fork grows and the stays re-bend when the design
  tyre widens.

The loop is bounded (``max_iter``), deterministic and LLM-free. Every change is
recorded as a ``ChangeRecord`` with the iteration, the old and new value, the
level, the check that triggered it and the reason; changed values take
provenance ``router``. Warnings (toe overlap, a long standover) are reported
with the repair a designer would consider, never auto-applied. Checks with no
safe repair (crank sweep, standover below zero, part build failures) are
reported as unresolved, with their level, for a human or a later planner pass.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from ..assembly.build import AssemblyBuild, build_assembly
from ..contracts.product import ChangeRecord, ProductSpec, SkeletonParam
from .checks import ProductCheck, ProductReport, check_bicycle
from .templates.bicycle import CROWN_HEIGHT, SEATPOST_LENGTHS, spec_from_skeleton

MAX_CHAINSTAY = 460.0  # mm; beyond this the bike stops being a road or gravel bike
CHAINSTAY_STEP = 10.0  # mm per repair step when the chainstays crowd the tyre
MIN_HEAD_TUBE = 90.0


@dataclass
class Action:
    param: str
    new: Any
    level: str  # part | design
    check: str
    reason: str
    responsible: str | None = None


@dataclass
class RouterResult:
    spec: ProductSpec
    build: AssemblyBuild
    report: ProductReport
    status: str  # passed | repaired | unresolved
    iterations: list[dict] = field(default_factory=list)
    unresolved: list[dict] = field(default_factory=list)
    suggestions: list[dict] = field(default_factory=list)
    seconds: float = 0.0

    def to_dict(self) -> dict:
        return {"status": self.status, "iterations": self.iterations, "unresolved": self.unresolved,
                "suggestions": self.suggestions, "history": [h.model_dump() for h in self.spec.history],
                "seconds": round(self.seconds, 1)}


def _v(spec: ProductSpec, key: str) -> Any:
    return spec.skeleton[key].value


# ---------------------------------------------------------------- per-check repair rules


def _tyre_front_fork(spec: ProductSpec, c: ProductCheck) -> list[Action] | str:
    tyre, max_tyre = _v(spec, "tyre_width"), _v(spec, "max_tyre_width")
    if tyre > max_tyre:
        return [Action("max_tyre_width", tyre, "design", c.name,
                       f"{tyre:g} mm tyre exceeds the {max_tyre:g} mm the frameset was designed for; re-derive fork "
                       "length, blade spread and stay bends around it", "skeleton")]
    member = c.detail.get("member", "")
    if member in ("crown", "steerer"):
        need = _v(spec, "wheel_bsd") / 2 + tyre + CROWN_HEIGHT + spec.targets["tyre_clearance_min"] + 1.0
        new = max(need, _v(spec, "fork_a2c") + c.detail["deficit"] + 1.0)
        return [Action("fork_a2c", round(new, 1), "design", c.name, f"tyre {c.actual} mm from the fork crown; lengthen "
                       "axle-to-crown (head tube re-derived so both axles stay level)", "fork")]
    if member.startswith("blade"):
        return [Action("fork_blade_spread", round(_v(spec, "fork_blade_spread") + c.detail["deficit"] + 1.0, 1), "design",
                       c.name, "tyre crowds the fork blades; spread them", "fork")]
    return f"tyre meets fork member {member!r}; no repair rule"


def _tyre_rear(spec: ProductSpec, c: ProductCheck) -> list[Action] | str:
    tyre, max_tyre = _v(spec, "tyre_width"), _v(spec, "max_tyre_width")
    if tyre > max_tyre:
        return [Action("max_tyre_width", tyre, "design", c.name,
                       f"{tyre:g} mm tyre exceeds the {max_tyre:g} mm the frame was designed for; re-derive the stay bends",
                       "skeleton")]
    member = c.detail.get("member", "")
    if member.startswith("seatstay"):
        return [Action("max_tyre_width", round(max_tyre + c.detail["deficit"] + 1.0, 1), "design", c.name,
                       "tyre crowds the seat stays; widen their bend by designing for a wider tyre", "frame")]
    if member.startswith(("chainstay", "seat_tube", "bb_shell")):
        cs = _v(spec, "chainstay_length")
        if cs + CHAINSTAY_STEP > MAX_CHAINSTAY:
            return f"tyre crowds {member} and the chainstays are already {cs:g} mm (limit {MAX_CHAINSTAY:g})"
        steps = max(1, math.ceil((c.detail["deficit"] + (4.0 if c.detail.get("overlap_mm3") else 0.0)) / 3.0))
        new = min(MAX_CHAINSTAY, cs + CHAINSTAY_STEP * steps)
        return [Action("chainstay_length", new, "design", c.name,
                       f"tyre {c.actual} mm from {member}; lengthen the chainstays so the stays open out before the tyre", "frame")]
    return f"tyre meets frame member {member!r}; no repair rule"


def _steering(spec: ProductSpec, c: ProductCheck) -> list[Action] | str:
    hits = c.detail.get("contact_angles") or []
    lock = _v(spec, "steer_lock")
    min_lock = spec.targets.get("min_lock", 30.0)
    if not hits:
        return f"steering clearance {c.actual} mm below target without contact; no repair rule"
    first = min(abs(a) for a in hits)
    step = 2 * lock / 8  # the sweep's sample spacing: the contact lies between the last clear sample and this one
    new = math.floor(first - step)
    if new < min_lock:
        return f"{c.detail.get('pair')} contact at {first:g} deg; a stop below {min_lock:g} deg is not acceptable"
    return [Action("steer_lock", float(new), "design", c.name,
                   f"{c.detail.get('pair')} touches at {first:g} deg; move the steering stop to {new} deg", "frame")]


def _seatpost(spec: ProductSpec, c: ProductCheck) -> list[Action] | str:
    ins, lo, hi = c.detail["insertion"], c.detail["min"], c.detail["usable"]
    length = _v(spec, "seatpost_length")
    if ins < lo:
        longer = [L for L in SEATPOST_LENGTHS if L > length]
        if longer:
            return [Action("seatpost_length", longer[0], "part", c.name,
                           f"insertion {ins:.0f} mm below the {lo:g} mm mark; fit a {longer[0]:g} mm post", "seatpost")]
        return [Action("seat_tube_nominal", round(_v(spec, "seat_tube_length") + lo - ins + 5, 1), "design", c.name,
                       "no stock post is long enough; lengthen the seat tube", "frame")]
    shorter = [L for L in SEATPOST_LENGTHS if L < length]
    if ins > hi and shorter:
        return [Action("seatpost_length", shorter[-1], "part", c.name,
                       f"post would sit {ins:.0f} mm deep (usable {hi:.0f}); fit a {shorter[-1]:g} mm post", "seatpost")]
    return f"seatpost insertion {ins:.0f} mm outside [{lo:g}, {hi:.0f}] and no stock length fixes it"


def _chainline(spec: ProductSpec, c: ProductCheck) -> list[Action] | str:
    return [Action("chainline", _v(spec, "rear_chainline"), "part", c.name,
                   f"chainline off by {c.actual} mm; set the crankset's ring-pack centre to the cassette line", "crankset")]


def _ground(spec: ProductSpec, c: ProductCheck) -> list[Action] | str:
    if spec.skeleton["head_tube_length"].source != "derived":
        return [Action("head_tube_length", None, "design", c.name,
                       "a fixed head-tube length leaves the axles at different heights; re-derive it from stack", "frame")]
    return "axles level by construction yet tyres miss the ground; likely a part-envelope mismatch (no repair rule)"


RULES: dict[str, Callable[[ProductSpec, ProductCheck], list[Action] | str]] = {
    "tyre_clearance[front_tyre~fork]": _tyre_front_fork,
    "tyre_clearance[rear_tyre~frame]": _tyre_rear,
    "steering_sweep": _steering,
    "seatpost_insertion": _seatpost,
    "chainline": _chainline,
    "ground_contact": _ground,
}

SUGGEST = {
    "toe_overlap": "warning only: more fork offset, a shorter crank or a longer front centre would remove it",
    "standover": "warning only: a smaller size or more top-tube slope lowers standover",
    "trail": "warning only: adjust head angle or fork offset",
}

# Assembly-level failures already covered by a product check (repairing the product check fixes them).
COVERED = ("front_tyre", "rear_tyre")


def plan_repairs(spec: ProductSpec, report: ProductReport) -> tuple[list[Action], list[dict], list[dict]]:
    actions: list[Action] = []
    unresolved, suggestions = [], []
    for c in report.checks:
        if c.passed:
            continue
        if c.severity == "warning":
            suggestions.append({"check": c.name, "actual": c.actual, "suggestion": SUGGEST.get(c.name, "warning only")})
            continue
        if c.category == "assembly" and (c.name == "assembly" or any(r in COVERED for r in c.responsible)):
            continue
        rule = RULES.get(c.name)
        out = rule(spec, c) if rule else f"no repair rule for {c.name}"
        if isinstance(out, str):
            unresolved.append({"check": c.name, "level": c.level, "responsible": c.responsible, "reason": out,
                               "actual": c.actual, "target": c.target})
        else:
            actions += [a for a in out if a.param not in {x.param for x in actions}]
    return actions, unresolved, suggestions


def apply_repairs(spec: ProductSpec, actions: list[Action], iteration: int) -> ProductSpec:
    sk = {k: v.model_copy() for k, v in spec.skeleton.items()}
    history = list(spec.history)
    for a in actions:
        old = sk[a.param].value
        if a.new is None:  # back to derived
            sk[a.param] = SkeletonParam(value=None, unit=sk[a.param].unit, source="derived", note=a.reason)
        else:
            sk[a.param] = sk[a.param].model_copy(update={"value": a.new, "source": "router", "note": a.reason})
        history.append(ChangeRecord(iteration=iteration, param=a.param, old=old, new=a.new, level=a.level, check=a.check,
                                    reason=a.reason, responsible=a.responsible))
    new = spec_from_skeleton(spec.requirements, sk, spec.name, history)
    # A longer fork shortens the derived head tube; below the minimum the stack has to grow instead.
    htl = new.skeleton["head_tube_length"]
    if htl.source == "derived" and htl.value < MIN_HEAD_TUBE:
        deficit = MIN_HEAD_TUBE - htl.value
        ha = math.radians(new.value("head_angle"))
        stack = new.value("stack") + deficit * math.sin(ha)
        sk = {k: v.model_copy() for k, v in new.skeleton.items()}
        reason = f"head tube would be {htl.value:.0f} mm (< {MIN_HEAD_TUBE:g}); raise stack to keep it"
        history.append(ChangeRecord(iteration=iteration, param="stack", old=new.value("stack"), new=round(stack, 1),
                                    level="design", check="derived:head_tube_length", reason=reason, responsible="skeleton"))
        sk["stack"] = sk["stack"].model_copy(update={"value": round(stack, 1), "source": "router", "note": reason})
        new = spec_from_skeleton(spec.requirements, sk, spec.name, history)
    return new


def run_with_router(spec: ProductSpec, max_iter: int = 4, steps: int = 9, run_assembly: bool = True,
                    log: Callable[[str], None] | None = None) -> RouterResult:
    """Build, check, repair, rebuild until the product passes, nothing is repairable, or ``max_iter`` repairs ran."""
    t0 = time.perf_counter()
    iterations = []
    repaired = False
    seen: set[str] = set()
    for it in range(max_iter + 1):
        ti = time.perf_counter()
        build = build_assembly(spec.assembly)
        report = check_bicycle(spec, build, run_assembly=run_assembly, steps=steps)
        actions, unresolved, suggestions = plan_repairs(spec, report)
        row = {"iteration": it, "passed": report.passed, "failed": [c.name for c in report.failed],
               "warnings": [c.name for c in report.warnings], "seconds": round(time.perf_counter() - ti, 1),
               "actions": [a.__dict__ for a in actions], "unresolved": unresolved}
        iterations.append(row)
        if log:
            log(f"iteration {it}: {'pass' if report.passed else 'fail ' + str(row['failed'])}; "
                f"{len(actions)} repair(s) {[(a.param, a.new) for a in actions]}")
        if report.passed or not actions or it == max_iter:
            break
        key = repr(sorted((a.param, a.new) for a in actions))
        if key in seen:  # the same repair again would loop
            break
        seen.add(key)
        spec = apply_repairs(spec, actions, it + 1)
        repaired = True
    status = "passed" if report.passed and not repaired else "repaired" if report.passed else "unresolved"
    return RouterResult(spec, build, report, status, iterations, unresolved, suggestions, time.perf_counter() - t0)
