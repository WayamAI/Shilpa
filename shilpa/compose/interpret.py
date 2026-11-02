"""Interpret-then-apply (spec 0, stages 1 to 4): bind mentions, expand, check, lower, and build the card.

``interpret(...)`` never builds geometry and never calls a model: it receives steps (from the
composer, or resubmitted by the client with answers applied) plus the mention table, and returns
the interpretation card. ``status == "ready"`` means Apply may run; the lowered ``AssemblySpec``
and its hash come with it so the client can see exactly what will be built.
"""

from __future__ import annotations

from typing import Any

from ..contracts.composition import IR_VERSION, CompositionIR, Ref, Step
from .expand import Blocker, Expander, apply_patches
from .lower import lower, spec_hash
from .mentions import MentionError
from .resolve import Library, Resolution

DISCLAIMER = "Geometry validated. Not reviewed for engineering release."
REF_FIELDS = ("source", "target")


def _refs(step: Step):
    """(dotted field, Ref) for every reference in a step."""
    for f in REF_FIELDS:
        r = getattr(step, f)
        if r is not None:
            yield f, r
    if step.offset is not None:
        if step.offset.from_ is not None:
            yield "offset.from", step.offset.from_
        d = step.offset.direction
        if d is not None:
            for k in ("normal_of", "along", "away_from"):
                if getattr(d, k) is not None:
                    yield f"offset.direction.{k}", getattr(d, k)


def _put(step: Step, where: str, ref: Ref) -> None:
    keys = where.split(".")
    obj = step
    for k in keys[:-1]:
        obj = getattr(obj, "from_" if k == "from" else k)
    setattr(obj, "from_" if keys[-1] == "from" else keys[-1], ref)


def bind(steps: list[Step], table: list[Resolution]) -> list[Blocker]:
    """Replace each mention reference with its resolution. Ambiguity and unknown parts become blockers."""
    by_id = {r.mention: r for r in table}
    by_text = {r.text: r for r in table}
    blockers: list[Blocker] = []
    for step in steps:
        for where, ref in list(_refs(step)):
            if ref.source is not None:
                continue  # already bound (a resubmitted step, or an answered ambiguity)
            res = by_id.get(ref.mention or "") or by_text.get(ref.text)
            if res is None:
                blockers.append(Blocker(step.id, "unresolved_reference", f"{ref.text or 'a reference'} does not match any @mention "
                                        "in the prompt. Mention the part with @.", where))
                continue
            if res.status != "ok":
                opts = []
                for c in res.candidates:
                    patch = {f"{where}.{k}": v for k, v in c["ref"].items()}
                    patch[f"{where}.mention"] = None
                    if "generator" in c["ref"]:
                        from .features import params_hash

                        patch[f"{where}.item"] = f"catalog:{c['ref']['generator']}"
                        patch[f"{where}.version"] = params_hash(c["ref"]["params"])
                    opts.append({"label": c["label"], "patch": [{"step": step.id, "set": patch}]})
                code = {"ambiguous": "ambiguous_reference", "unknown": "unknown_part"}.get(res.status, "invalid_reference")
                blockers.append(Blocker(step.id, code, res.message, where, opts))
                continue
            bound = res.ref.model_copy(deep=True)
            if bound.selector is None and ref.selector is not None:
                bound.selector = ref.selector
            elif bound.selector is not None and ref.selector is not None and ref.selector.filter and not bound.selector.filter:
                bound.selector = bound.selector.model_copy(update={"filter": ref.selector.filter})
            if ref.selector is not None and ref.selector.expected_count is not None and bound.selector is not None:
                bound.selector = bound.selector.model_copy(update={"expected_count": ref.selector.expected_count})
            _put(step, where, bound)
    return blockers


def _mention_error_blockers(errors: list[MentionError]) -> list[Blocker]:
    return [Blocker("s0", "mention_syntax", f"Mention at character {e.start}: {e.message}") for e in errors]


def renumber(steps: list[Step], after: list[Step]) -> list[Step]:
    """Give new steps ids that continue the applied history (s1, s2 ... are taken)."""
    start = max((int(s.id[1:]) for s in after), default=0)
    return [s.model_copy(update={"id": f"s{start + k + 1}"}) for k, s in enumerate(steps)]


def run(library: Library, applied: list[Step], new: list[Step]):
    exp = Expander(library)
    prog, reports = exp.run([*applied, *new], {s.id for s in new})
    return prog, reports


def interpret(*, composition_id: str, name: str | None, library: Library, applied: list[Step], new: list[Step],
              resolutions: list[Resolution] | None = None, mention_errors: list[MentionError] | None = None,
              base_version: str | None = None, answers: list[dict] | None = None, llm: dict | None = None) -> dict[str, Any]:
    """The interpretation card for ``new`` steps on top of ``applied`` ones."""
    resolutions = resolutions or []
    if answers:
        new = apply_patches(new, answers)
    pre = bind(new, resolutions) + _mention_error_blockers(mention_errors or [])
    prog, reports = run(library, applied, new)
    new_ids = {s.id for s in new}
    blockers = []
    seen = set()
    pre_steps = {b.step_id for b in pre}
    for b in pre:
        if (b.step_id, b.code, b.field) not in seen:
            seen.add((b.step_id, b.code, b.field))
            blockers.append(b.to_dict())
    warnings, assumptions, quantities, filters, readings = [], [], [], [], []
    for rep in reports:
        mine = rep.step_id in new_ids
        for b in rep.blockers:
            if rep.step_id in pre_steps and b.code in ("unresolved_reference", "unknown_part"):
                continue  # already explained by the mention blocker
            if mine or b.code == "broken_reference":
                blockers.append(b.to_dict())
        if not mine:
            continue
        warnings += [{"step_id": rep.step_id, **w} for w in rep.warnings]
        assumptions += [{"step_id": rep.step_id, **a} for a in rep.assumptions]
        quantities += [{"step_id": rep.step_id, **q} for q in rep.quantities]
        filters += [{"step_id": rep.step_id, **f} for f in rep.filters]
        readings.append({"step_id": rep.step_id, "op": rep.op, "text": rep.reading, "instances_added": rep.instances_added,
                         "mates_added": rep.mates_added})
    for s in new:
        for a in s.assumptions:  # the composer's own stated defaults
            assumptions.append({"step_id": s.id, "field": a.field, "value": a.value, "reason": a.reason, "by": "reader"})
    ready = not blockers and bool(new)
    spec = None
    if ready:
        spec = lower(prog, name)
    added = sum(len(r["instances_added"]) for r in readings)
    ir = CompositionIR(composition_id=composition_id, base_version=base_version, steps=[*applied, *new])
    return {
        "ir_version": IR_VERSION,
        "composition_id": composition_id,
        "base_version_id": base_version,
        "status": "ready" if ready else ("empty" if not new else "blocked"),
        "reading": " ".join(r["text"] for r in readings if r["text"]),
        "readings": readings,
        "counts": {"instances_added": added, "mates_added": sum(len(r["mates_added"]) for r in readings),
                   "instances_total": len(prog.instances), "mates_total": len(prog.mates)},
        "quantities": quantities,
        "assumptions": assumptions,
        "filters": filters,
        "mentions": [r.card() for r in resolutions],
        "blockers": blockers,
        "warnings": warnings,
        "steps": [s.model_dump(mode="json", by_alias=True, exclude_none=True) for s in new],
        "ir": ir.model_dump(mode="json", by_alias=True, exclude_none=True),
        "spec_hash": spec_hash(spec) if spec else None,
        "spec": spec,
        "llm": llm or {"used": False},
        "disclaimer": DISCLAIMER,
    }
