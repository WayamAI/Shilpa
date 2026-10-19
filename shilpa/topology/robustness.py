"""Edit robustness: do selections still mean the same entities after a parameter edit?

CADEngBench's finding (edits that touch existing history pass 40-46 % of the time) is a
selection problem: a fillet's edge query that matched "the four outer vertical edges"
at nominal size matches something else, or nothing, after an edit. This module
measures that for Shilpa recipes, comparing the heuristic selectors a recipe was
written with against persistent named references (IR 1.2) that select the same
entities at nominal size.

Per recipe:

1. Build it at nominal size. For every selection (fillet / chamfer edges, shell open
   faces, hole entry sides) record the *intent*: the selected entities' persistent
   names with instance indices dropped (``mount_holes.wall&base_solid.top``).
2. Make the named twin: each heuristic selector becomes a ``NamedSelector`` whose
   reference is the generalised names when they select exactly the same entities at
   nominal size, otherwise the explicit names.
3. For each edit (lengths scaled by +/-10-30 %, counts +/-1) rebuild both variants.
   A variant keeps the intent when it builds and every selection picks exactly the
   entities of the edited part whose generalised names are in the nominal intent
   (same feature + role, count consistent with the edited pattern counts).

An edit that neither variant can build for reasons other than selection (a hole
pattern that no longer fits) is infeasible and excluded. Robustness score = edits
rebuilt with the intended selections / feasible edits.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from ..adapters import build123d_adapter as ad
from ..contracts.errors import ErrorCode, ShilpaError
from .naming import NamingError
from .refs import generalize

SELECTOR_ERRORS = {ErrorCode.SELECTOR_EMPTY, ErrorCode.SELECTOR_AMBIGUOUS}
LENGTH_FACTORS = (0.75, 0.9, 1.1, 1.3)
COUNT_STEPS = (-1, 1)


def _gen_edge(name: str) -> str:
    pair = name.split("~", 1)[0].split("&")
    return "&".join(sorted(generalize(p) for p in pair))


def _gen(name: str) -> str:
    return _gen_edge(name) if "&" in name else generalize(name)


@dataclass
class Selection:
    feature_id: str
    field: str  # "edges" | "open_faces.<i>" | "entry"
    body_ref: str
    kind: str  # "edges" | "faces"
    intent: set[str]  # generalised names
    nominal_count: int
    ref: str  # the named reference that replaces the heuristic selector


@dataclass
class EditOutcome:
    edit: str
    heuristic: str  # "ok" | "wrong_selection" | "selector_error" | "build_error" | "infeasible"
    named: str
    notes: list[str] = field(default_factory=list)


def _heuristic(table, spec, fname: str, values: dict) -> list:
    """Re-run a heuristic selector against a body state."""
    shape = table.shape
    if fname == "edges":
        return ad.select_edges(shape, spec.edges, values.get("edges.diameter"))
    if fname.startswith("open_faces"):
        return ad._side_faces(shape, spec.open_faces[int(fname.split(".")[1])].side)
    return ad._side_faces(shape, spec.face)  # hole entry


def _selectors(compiled):
    """(feature, field, kind) for every heuristic selection in a recipe."""
    for cf in compiled.features:
        f = cf.spec
        if cf.op in ("fillet", "chamfer") and not isinstance(f.edges, ad.NamedSelector):
            yield cf, "edges", "edges"
        elif cf.op == "shell":
            for i, s in enumerate(f.open_faces):
                if not isinstance(s, ad.NamedSelector):
                    yield cf, f"open_faces.{i}", "faces"
        elif cf.op in ("hole", "corner_hole_pattern", "linear_hole_pattern", "polar_hole_pattern") and f.entry_face is None:
            yield cf, "entry", "faces"


def _ref_for(table, ents, kind: str) -> str:
    names = table.names_of(ents)
    keys = {id_ for id_ in map(lambda e: hash(e.wrapped), ents)}
    general = ",".join(sorted({_gen(n) for n in names}))
    for cand in (general, ",".join(sorted(names))):
        try:
            k, got = table.resolve(cand)
        except NamingError:
            continue
        if k == kind and {hash(e.wrapped) for e in got} == keys:
            return cand
    raise NamingError(f"no named reference reproduces {names}")


def analyse(recipe: dict, hole_entries: bool = True) -> tuple[list[Selection], dict]:
    """Nominal intents of every heuristic selection, and the named twin of the recipe."""
    res = ad.build(recipe)
    if not res.ok:
        raise ShilpaError(ErrorCode.PRECONDITION_FAILED, f"nominal build failed: {res.error.info.message}")
    twin = copy.deepcopy(recipe)
    by_id = {f["id"]: f for f in twin["features"]}
    sels = []
    for cf, fname, kind in _selectors(res.compiled):
        if fname == "entry" and not hole_entries:
            continue
        table = res.names[cf.spec.body_ref]
        ents = _heuristic(table, cf.spec, fname, cf.values)
        ref = _ref_for(table, ents, kind)
        sels.append(Selection(cf.id, fname, cf.spec.body_ref, kind, {_gen(n) for n in table.names_of(ents)}, len(ents), ref))
        f = by_id[cf.id]
        if fname == "edges":
            f["edges"] = {"ref": ref}
        elif fname == "entry":
            f["entry_face"] = {"ref": ref}
        else:
            f["open_faces"][int(fname.split(".")[1])] = {"ref": ref}
    if sels:
        twin["schema_version"] = "1.2"
    return sels, twin


def edits(recipe: dict) -> list[tuple[str, dict]]:
    """Parameter edits: every plain length value scaled, every count stepped."""
    out = []
    for name, p in recipe["parameters"].items():
        value = p if isinstance(p, (int, float)) else p.get("value")
        kind = "length" if isinstance(p, (int, float)) else p.get("kind", "length")
        if value is None or kind not in ("length", "count"):
            continue
        steps = [(f"{name}x{k:g}", value * k) for k in LENGTH_FACTORS] if kind == "length" else \
            [(f"{name}{s:+d}", value + s) for s in COUNT_STEPS if value + s >= 1]
        for label, v in steps:
            r = copy.deepcopy(recipe)
            if isinstance(p, (int, float)):
                r["parameters"][name] = v
            else:
                r["parameters"][name]["value"] = v
            out.append((label, r))
    return out


def _judge(recipe: dict, sels: list[Selection], named: bool) -> tuple[str, list[str], ErrorCode | None]:
    try:
        res = ad.build(recipe)
    except ShilpaError as exc:  # compile-time: e.g. a count edit below the minimum
        return "build_error", [exc.info.message], exc.code
    if not res.ok:
        status = "selector_error" if res.error.code in SELECTOR_ERRORS else "build_error"
        return status, [f"{res.error.info.feature_id}: {res.error.info.message}"], res.error.code
    by_id = {cf.id: cf for cf in res.compiled.features}
    notes = []
    for s in sels:
        cf = by_id[s.feature_id]
        table = res.names.get(s.body_ref)
        if table is None:
            return "wrong_selection", [f"{s.body_ref} has no names"], None
        if named:
            sel = cf.spec.edges if s.field == "edges" else cf.spec.entry_face if s.field == "entry" else \
                cf.spec.open_faces[int(s.field.split(".")[1])]
            ents = table.resolve(sel.ref)[1]
        else:
            ents = _heuristic(table, cf.spec, s.field, cf.values)
        got = {hash(e.wrapped) for e in ents}
        pool = table.faces if s.kind == "faces" else [(n, e) for n, e, _ in table.edges]
        want = {hash(e.wrapped) for n, e in pool if _gen(n) in s.intent}
        if got != want:
            notes.append(f"{s.feature_id}.{s.field}: selected {sorted(_gen(n) for n in table.names_of(ents))} "
                         f"({len(got)}), intended {len(want)} of {sorted(s.intent)}")
    return ("wrong_selection" if notes else "ok"), notes, None


def run(recipe: dict) -> dict:
    """Robustness of one recipe's selections under every edit, heuristic vs named."""
    sels, twin = analyse(recipe)
    outcomes = []
    if sels:
        for (label, edited), (_, edited_twin) in zip(edits(recipe), edits(twin)):
            h, hn, hcode = _judge(edited, sels, named=False)
            n, nn, ncode = _judge(edited_twin, sels, named=True)
            if h == "build_error" and n == "build_error":
                h = n = "infeasible"  # the edit itself breaks the design, not a selection
            outcomes.append(EditOutcome(label, h, n, hn + nn))
    feasible = [o for o in outcomes if o.named != "infeasible"]
    return {
        "selections": [{"feature": s.feature_id, "field": s.field, "intent": sorted(s.intent), "count": s.nominal_count,
                        "ref": s.ref} for s in sels],
        "edits": len(outcomes), "feasible": len(feasible),
        "heuristic_ok": sum(o.heuristic == "ok" for o in feasible),
        "named_ok": sum(o.named == "ok" for o in feasible),
        "outcomes": [o.__dict__ for o in outcomes],
    }
