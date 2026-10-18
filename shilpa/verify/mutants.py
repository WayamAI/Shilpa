"""Oracle quality by mutation: does a test suite notice when the part is wrong?

Mutants are made from a correct reference recipe and rebuilt with the production
build123d adapter, so every mutant is a real, valid part that differs from the
reference in one requirement-shaped way:

  dim     scale one length parameter by +/-5-20 %
  count   change one count by +/-1
  drop    remove one hole, pattern, pocket, fillet or chamfer
  move    shift one positioned feature along X or Y; rotate an explicitly angled bolt circle
  mirror  negate every X (or Y) position in the recipe

A mutant is *killed* when the suite fails it. Mutants that do not build (stillborn)
or that are congruent to the reference in the canonical frame (equivalent: a
mirror of a symmetric part, a change to an unused parameter) are excluded, as in
standard mutation testing. Mutation score = killed / (built and non-equivalent).
"""

from __future__ import annotations

import copy
import random
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import build123d as bd

from ..adapters import build123d_adapter as adapter
from ..contracts.errors import ShilpaError
from .requirements import RequirementTest, canonicalize, run_tests

EQUIV_REL = 1e-6
HOLE_OPS = {"hole", "corner_hole_pattern", "linear_hole_pattern", "polar_hole_pattern"}
DROP_OPS = HOLE_OPS | {"pocket", "fillet", "chamfer"}
MOVE_OPS = {"hole", "linear_hole_pattern", "polar_hole_pattern", "pocket", "centered_rectangle", "circle"}
REF_KEYS = ("body_ref", "target_ref", "tool_ref", "profile_ref")


@dataclass
class Mutant:
    id: str
    operator: str
    description: str
    recipe: dict


@dataclass
class MutantOutcome:
    id: str
    operator: str
    description: str
    status: str  # "evaluated" | "stillborn" | "equivalent"
    killed: dict[str, bool] = field(default_factory=dict)  # suite name -> killed
    note: str | None = None


def _value(p) -> float | None:
    if isinstance(p, dict):
        return p.get("value")
    return float(p)


def _kind(p) -> str:
    return p.get("kind", "length") if isinstance(p, dict) else "length"


def _source(p) -> str:
    return p.get("source", "user") if isinstance(p, dict) else "user"


def _set_value(recipe: dict, name: str, v: float) -> None:
    p = recipe["parameters"][name]
    if isinstance(p, dict):
        p["value"] = v
    else:
        recipe["parameters"][name] = v


def _add_param(recipe: dict, name: str, value: float, kind: str = "length") -> str:
    unit = "deg" if kind == "angle" else "mm"
    base, i = name, 1
    while name in recipe["parameters"]:
        i += 1
        name = f"{base}{i}"
    recipe["parameters"][name] = {"value": value, "kind": kind, "unit": unit, "source": "user"}
    return name


def _referenced(recipe: dict) -> set[str]:
    out = set()
    for f in recipe["features"]:
        out |= {f[k] for k in REF_KEYS if f.get(k)}
    return out


def _part_size(recipe: dict) -> float:
    try:
        b = adapter.build(recipe)
        if b.ok:
            bb = b.shape.bounding_box()
            return max(bb.size.X, bb.size.Y, bb.size.Z)
    except ShilpaError:
        pass
    return 50.0


def make_mutants(recipe: dict, seed: int = 0, operators: tuple[str, ...] = ("dim", "count", "drop", "move", "mirror")) -> list[Mutant]:
    rng = random.Random(seed)
    out: list[Mutant] = []

    def add(op, desc, r):
        out.append(Mutant(f"m{len(out) + 1:02d}-{op}", op, desc, r))

    params = recipe["parameters"]
    if "dim" in operators:
        for name, p in params.items():
            v = _value(p)
            if v is None or _kind(p) != "length" or _source(p) in ("assumed", "default") or v == 0:
                continue
            f = 1 + rng.choice((-1, 1)) * rng.uniform(0.05, 0.20)
            r = copy.deepcopy(recipe)
            _set_value(r, name, round(v * f, 6))
            add("dim", f"{name} {v:g} -> {v * f:.4g} ({(f - 1) * 100:+.0f} %)", r)

    if "count" in operators:
        for name, p in params.items():
            v = _value(p)
            if v is None or _kind(p) != "count":
                continue
            new = v + 1 if v <= 1 or rng.random() < 0.5 else v - 1
            r = copy.deepcopy(recipe)
            _set_value(r, name, new)
            add("count", f"{name} {v:g} -> {new:g}", r)
        for i, f in enumerate(recipe["features"]):
            for k, ref in f.items():
                if k.endswith("count_ref") and isinstance(ref, str) and ref.strip().isdigit():
                    n = int(ref)
                    new = n + 1 if n <= 1 or rng.random() < 0.5 else n - 1
                    r = copy.deepcopy(recipe)
                    r["features"][i][k] = str(new)
                    add("count", f"{f['id']}.{k} {n} -> {new}", r)

    if "drop" in operators:
        for i, f in enumerate(recipe["features"]):
            if f["op"] not in DROP_OPS:
                continue
            r = copy.deepcopy(recipe)
            r["features"].pop(i)
            for g in r["features"]:  # whatever was built on the dropped feature now uses its input body
                for k in REF_KEYS:
                    if g.get(k) == f["id"]:
                        g[k] = f["body_ref"]
            if r.get("output") == f["id"]:
                r["output"] = f["body_ref"]
            add("drop", f"drop {f['op']} {f['id']}", r)

    if "move" in operators:
        delta = round(max(1.0, 0.06 * _part_size(recipe)), 3)
        used = _referenced(recipe)
        for i, f in enumerate(recipe["features"]):
            if f["op"] not in MOVE_OPS:
                continue
            if f["op"] in ("centered_rectangle", "circle") and f["id"] not in used:
                continue
            for axis in ("x", "y"):
                r = copy.deepcopy(recipe)
                d = _add_param(r, "mut_shift", delta)
                key = f"center_{axis}_ref"
                cur = f.get(key)
                r["features"][i][key] = f"({cur}) + {d}" if cur else d
                add("move", f"move {f['id']} {delta:g} mm along {axis.upper()}", r)
            if f["op"] == "polar_hole_pattern" and f.get("start_angle_ref"):
                r = copy.deepcopy(recipe)
                a = _add_param(r, "mut_rot", 10.0, "angle")
                r["features"][i]["start_angle_ref"] = f"({f['start_angle_ref']}) + {a}"
                add("move", f"rotate {f['id']} by 10 deg", r)

    if "mirror" in operators:
        for axis in ("x", "y"):
            r = copy.deepcopy(recipe)
            changed = False
            for g in r["features"]:
                key = f"center_{axis}_ref"
                if g.get(key):
                    g[key] = f"-({g[key]})"
                    changed = True
                if axis == "y" and g.get("start_angle_ref"):
                    g["start_angle_ref"] = f"-({g['start_angle_ref']})"
                    changed = True
            if changed:
                add("mirror", f"mirror all {axis.upper()} positions", r)
    return out


# ---------------------------------------------------------------- evaluation


def _congruent(a: bd.Shape, b: bd.Shape, vol: float) -> bool:
    """True if b equals a up to the canonical frame's residual symmetry (quarter / half turns about Z)."""
    if abs(a.volume - b.volume) > EQUIV_REL * vol * 10:
        return False
    ba = a.bounding_box()
    for angle in (0, 90, 180, 270):
        c = b.rotate(bd.Axis.Z, angle) if angle else b
        cb = c.bounding_box()
        if any(abs(x - y) > 1e-6 for x, y in zip((ba.size.X, ba.size.Y, ba.size.Z), (cb.size.X, cb.size.Y, cb.size.Z))):
            continue
        try:
            diff = (a - c).volume + (c - a).volume
        except Exception:
            continue
        if diff <= EQUIV_REL * vol:
            return True
    return False


def _shape_via_step(shape, tmp: Path, name: str) -> bd.Shape:
    path = tmp / f"{name}.step"
    bd.export_step(shape, str(path))
    return bd.import_step(str(path))


def evaluate_mutants(reference: dict, mutants: list[Mutant], suites: dict[str, list[RequirementTest | dict]],
                     workdir: Path | None = None) -> dict:
    """Build every mutant, drop stillborn and equivalent ones, and record which suites kill each."""
    tmp_ctx = tempfile.TemporaryDirectory(prefix="shilpa-mut-") if workdir is None else None
    tmp = Path(workdir or tmp_ctx.name)
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        ref_build = adapter.build(reference)
        if not ref_build.ok:
            return {"error": f"reference does not build: {ref_build.error.info.message}", "mutants": []}
        ref_shape = _shape_via_step(ref_build.shape, tmp, "reference")
        ref_canon = canonicalize(ref_shape)
        vol = ref_canon.volume
        ref_verdicts = {name: run_tests(tests, ref_shape).passed for name, tests in suites.items()}
        outcomes: list[MutantOutcome] = []
        for m in mutants:
            try:
                b = adapter.build(m.recipe)
            except ShilpaError as exc:
                outcomes.append(MutantOutcome(m.id, m.operator, m.description, "stillborn", note=exc.info.message))
                continue
            if not b.ok:
                outcomes.append(MutantOutcome(m.id, m.operator, m.description, "stillborn", note=b.error.info.message))
                continue
            try:
                shape = _shape_via_step(b.shape, tmp, m.id)
            except Exception as exc:
                outcomes.append(MutantOutcome(m.id, m.operator, m.description, "stillborn", note=f"export: {exc}"))
                continue
            if _congruent(ref_canon, canonicalize(shape), vol):
                outcomes.append(MutantOutcome(m.id, m.operator, m.description, "equivalent"))
                continue
            killed = {name: not run_tests(tests, shape).passed for name, tests in suites.items()}
            outcomes.append(MutantOutcome(m.id, m.operator, m.description, "evaluated", killed))
        return {"reference_passes": ref_verdicts, "mutants": [o.__dict__ for o in outcomes]}
    finally:
        if tmp_ctx is not None:
            tmp_ctx.cleanup()


def mutation_score(evaluations: list[dict], suite: str) -> dict:
    """Aggregate kills for one suite over several evaluate_mutants results."""
    ev = [m for e in evaluations for m in e.get("mutants", []) if m["status"] == "evaluated" and suite in m["killed"]]
    killed = sum(m["killed"][suite] for m in ev)
    by_op: dict[str, list[int]] = {}
    for m in ev:
        s = by_op.setdefault(m["operator"], [0, 0])
        s[0] += m["killed"][suite]
        s[1] += 1
    all_m = [m for e in evaluations for m in e.get("mutants", [])]
    return {
        "killed": killed, "evaluated": len(ev), "score": round(killed / len(ev), 4) if ev else None,
        "by_operator": {k: {"killed": a, "evaluated": n, "score": round(a / n, 4)} for k, (a, n) in sorted(by_op.items())},
        "stillborn": sum(m["status"] == "stillborn" for m in all_m),
        "equivalent": sum(m["status"] == "equivalent" for m in all_m),
        "survivors": [m["description"] for m in ev if not m["killed"][suite]],
    }
