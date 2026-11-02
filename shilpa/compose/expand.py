"""Expand Composition IR steps into instances and mates, deterministically (spec 4.3 steps 1 and 2).

``Expander.run(steps)`` walks the steps in order, keeping the composition state (instances,
which one is grounded, which are placed). Every reference is resolved against that state;
selectors (``holes[*]`` plus filters) are evaluated into concrete features in the fixed group
order; ``insert`` becomes one instance per target feature (copies of the first) and one mate
each. Nothing here calls a model or guesses: an ambiguous or missing reference, an implausible
unit, a fit mismatch or a changed selection count becomes a *blocker* with options, and options
are deterministic patches (``Patch``) the user picks.

Output: ``Program`` (instances + mate plans, consumed by ``lower.py``) and one ``StepReport``
per step (reading, counts, quantities, assumptions, blockers, warnings: the interpretation card).
"""

from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any

from ..contracts.composition import P0_OPS, Patch, Predicate, Qty, Ref, Selector, Step
from ..contracts.iso_holes import TABLE as ISO_HOLES
from . import units
from .features import Feature, PartInfo, box_face, perpendicular_x
from .mentions import parse_one
from .resolve import InstanceState, Library, catalog_hits, instance_base, slugify

APPROX_TOL_MM = 0.05  # [Assumption] default tolerance for ≈ on lengths
EXACT_TOL_MM = 1e-3
PLANNED = {"fasten": "P3", "pattern": "P3", "mirror": "P1", "repeat": "P3", "constraint": "P3", "replace": "P3",
           "remove": "P3", "promote": "P1"}
WORLD = {"+X": (1, 0, 0), "-X": (-1, 0, 0), "+Y": (0, 1, 0), "-Y": (0, -1, 0), "+Z": (0, 0, 1), "-Z": (0, 0, -1)}


@dataclass
class MatePlan:
    id: str
    step_id: str
    a: str  # instance on the ground side
    a_feat: Feature
    a_seat: str | None
    b: str
    b_feat: Feature
    b_seat: str | None
    type: str = "fixed"
    align: str | None = None
    offset: float = 0.0
    angle: float = 0.0
    limits: tuple[float, float] | None = None
    intent: str | None = None


@dataclass
class Blocker:
    step_id: str
    code: str
    message: str
    field: str | None = None
    options: list[dict] = dc_field(default_factory=list)  # [{"label", "patch": [Patch dict]}]
    blocking: bool = True

    @property
    def id(self) -> str:
        return f"{self.step_id}:{self.code}"

    def to_dict(self) -> dict:
        return {"id": self.id, "step_id": self.step_id, "code": self.code, "message": self.message, "field": self.field,
                "options": self.options, "blocking": self.blocking}


@dataclass
class StepReport:
    step_id: str
    op: str
    reading: str = ""
    instances_added: list[str] = dc_field(default_factory=list)
    mates_added: list[str] = dc_field(default_factory=list)
    quantities: list[dict] = dc_field(default_factory=list)
    assumptions: list[dict] = dc_field(default_factory=list)
    filters: list[dict] = dc_field(default_factory=list)
    blockers: list[Blocker] = dc_field(default_factory=list)
    warnings: list[dict] = dc_field(default_factory=list)

    def to_dict(self) -> dict:
        return {"step_id": self.step_id, "op": self.op, "reading": self.reading, "instances_added": self.instances_added,
                "mates_added": self.mates_added, "quantities": self.quantities, "assumptions": self.assumptions,
                "filters": self.filters, "blockers": [b.to_dict() for b in self.blockers], "warnings": self.warnings}


@dataclass
class Program:
    instances: "OrderedDict[str, InstanceState]" = dc_field(default_factory=OrderedDict)
    parts: dict[str, PartInfo] = dc_field(default_factory=dict)
    mates: list[MatePlan] = dc_field(default_factory=list)

    @property
    def ground(self) -> str | None:
        return next((i.id for i in self.instances.values() if i.grounded), None)

    def part_of(self, iid: str) -> PartInfo:
        return self.parts[self.instances[iid].part_key]

    def scene_mm(self, extra: list[PartInfo] = ()) -> float:
        sizes = [self.part_of(i).size_mm for i in self.instances] + [p.size_mm for p in extra]
        return max(sizes) if sizes else 0.0


class _StepError(Exception):
    def __init__(self, blocker: Blocker):
        super().__init__(blocker.message)
        self.blocker = blocker


def _fmt(v: float) -> str:
    return f"{v:g}"


def _thread_size(part: PartInfo) -> str | None:
    t = part.meta.get("thread")
    return t if t in ISO_HOLES else None


def _suits(d: float) -> str | None:
    """The metric size whose ISO 273 clearance range (fine to coarse) contains diameter d."""
    for size, h in ISO_HOLES.items():
        if h.clearance["fine"] - 0.01 <= d <= h.clearance["coarse"] + 0.01:
            return size
    return None


def _fits(size: str, hole: Feature) -> bool:
    h = ISO_HOLES[size]
    d = hole.attrs["diameter"]
    if hole.attrs.get("thread"):
        return hole.attrs["thread"] == size
    return h.clearance["fine"] - 0.01 <= d <= h.clearance["coarse"] + 0.01


class Expander:
    def __init__(self, library: Library):
        self.lib = library
        self.prog = Program()
        self.reports: list[StepReport] = []
        self.new_ids: set[str] = set()
        self._added_now: set[str] = set()  # instances created by add steps in the steps being interpreted

    # ------------------------------------------------------------ entry point

    def run(self, steps: list[Step], new_ids: set[str] | None = None) -> tuple[Program, list[StepReport]]:
        self.new_ids = set(new_ids if new_ids is not None else (s.id for s in steps))
        for step in steps:
            rep = StepReport(step.id, step.op)
            self.reports.append(rep)
            if not step.enabled:
                rep.reading = "Disabled."
                continue
            snapshot = (OrderedDict((k, InstanceState(**vars(v))) for k, v in self.prog.instances.items()), list(self.prog.mates))
            try:
                self._step(step, rep)
            except _StepError as exc:
                b = exc.blocker
                if b.code in step.acknowledged and b.blocking:
                    rep.warnings.append({"code": b.code, "message": b.message + " (continued at your request)"})
                else:
                    rep.blockers.append(b)
                    self.prog.instances, self.prog.mates = snapshot  # a blocked step adds nothing
                    continue
            if step.id not in self.new_ids:
                # A step that applied before is re-resolved; its findings are history, not new questions.
                for b in rep.blockers:
                    b.code = "broken_reference" if b.code in ("unknown_feature", "missing_feature", "unknown_part") else b.code
        self._finish()
        return self.prog, self.reports

    def _finish(self) -> None:
        if not self.prog.instances:
            return
        if self.prog.ground is None:
            first = next(iter(self.prog.instances.values()))
            first.grounded = True
            rep = self._report(first.step_id)
            if rep is not None:
                rep.assumptions.append({"field": "ground", "value": first.id,
                                        "reason": f"nothing was grounded, so the first part, {first.id}, is fixed in space"})
        for inst in self.prog.instances.values():
            if not inst.grounded and not inst.placed:
                rep = self._report(inst.step_id)
                if rep is not None and not any(b.code == "unplaced" for b in rep.blockers):
                    rep.blockers.append(Blocker(inst.step_id, "unplaced",
                                                f"{inst.id} is added but not placed or mated, so it would float. "
                                                "Say where it goes (for example: on top of another part), or ground it."))

    def _report(self, step_id: str) -> StepReport | None:
        return next((r for r in self.reports if r.step_id == step_id), None)

    # ------------------------------------------------------------ references

    def _fail(self, step: Step, code: str, message: str, field_: str | None = None, options: list[dict] | None = None):
        raise _StepError(Blocker(step.id, code, message, field_, options or []))

    def _part_of_ref(self, step: Step, ref: Ref, where: str) -> PartInfo:
        if ref.source == "instance":
            if ref.instance not in self.prog.instances:
                self._fail(step, "unknown_part", f"{ref.text}: instance {ref.instance!r} is not in this composition", where)
            return self.prog.part_of(ref.instance)
        if ref.source not in ("native", "catalog"):
            self._fail(step, "unresolved_reference", f"{ref.text} was not resolved to a part. Pick it from the @ list.", where)
        try:
            part = self.lib.part(ref)
        except LookupError as exc:
            self._fail(step, "unknown_part", str(exc), where)
        except Exception as exc:  # a part that does not build
            self._fail(step, "part_failed", f"{ref.text} could not be loaded: {exc}", where)
        self.prog.parts.setdefault(part.key, part)
        return part

    def _instances_of(self, part: PartInfo) -> list[InstanceState]:
        return [i for i in self.prog.instances.values() if i.part_key == part.key]

    def _existing(self, step: Step, ref: Ref, where: str, *, allow_none: bool = False) -> InstanceState | None:
        """The instance a reference means: itself, or the single instance of a library part."""
        if ref.source == "instance":
            self._part_of_ref(step, ref, where)
            return self.prog.instances[ref.instance]
        part = self._part_of_ref(step, ref, where)
        insts = self._instances_of(part)
        if len(insts) == 1:
            return insts[0]
        if len(insts) > 1:
            opts = [{"label": f"{i.id}", "patch": [Patch(step=step.id, set={f"{where}.source": "instance", f"{where}.instance": i.id}).model_dump()]}
                    for i in insts]
            self._fail(step, "ambiguous_reference", f"{ref.text} matches {len(insts)} instances: "
                       + ", ".join(f"{i.id}" for i in insts) + ". Pick one.", where, opts)
        if allow_none:
            return None
        self._fail(step, "not_in_composition", f"{ref.text} is not in this composition yet. Add it first "
                   f"(for example: use {ref.text.split('.')[0]} as the base).", where)
        return None

    def _new_instance(self, step: Step, ref: Ref, part: PartInfo, *, copy_of: str | None = None) -> InstanceState:
        slug = slugify(ref.text.lstrip("@").split(".")[0].split("{")[0].split("#")[0]) if ref.text.startswith("@") else part.slug
        base = instance_base(slug)
        iid, k = base, 1
        while iid in self.prog.instances:
            k += 1
            iid = f"{base}_{k}"
        inst = InstanceState(iid, part.key, slug, part.label, step.id, copy_of=copy_of)
        self.prog.instances[iid] = inst
        if step.id in self.new_ids:
            self._added_now.add(iid)
        return inst

    def _source_instance(self, step: Step, ref: Ref, rep: StepReport) -> InstanceState:
        """The part being placed: an unplaced instance, or a new instance of a library part (implicit add)."""
        part = self._part_of_ref(step, ref, "source")
        if ref.source == "instance":
            inst = self.prog.instances[ref.instance]
        else:
            fresh = [i for i in self._instances_of(part) if i.id in self._added_now and not i.placed and not i.grounded]
            if fresh:
                inst = fresh[0]
            else:
                inst = self._new_instance(step, ref, part)
                rep.instances_added.append(inst.id)
        if inst.grounded:
            self._fail(step, "source_grounded", f"{inst.id} is the grounded base; it cannot be placed relative to another part. "
                       "Ground a different part first.", "source")
        if inst.placed:
            self._fail(step, "already_placed", f"{inst.id} is already placed by step {self._placed_by(inst.id)}. "
                       "Editing earlier steps arrives in P3; add a new instance instead.", "source")
        return inst

    def _placed_by(self, iid: str) -> str:
        return next((m.step_id for m in self.prog.mates if m.b == iid), "?")

    # ------------------------------------------------------------ selectors

    def select(self, step: Step, ref: Ref, part: PartInfo, where: str) -> list[Feature] | None:
        """Features a reference selects, in group order; None for the whole part."""
        if ref.feature_uid:
            f = next((f for f in part.features if f.uid == ref.feature_uid), None)
            if f is None:
                self._fail(step, "unknown_feature", f"{ref.text}: feature {ref.feature_uid} is not on {part.label} "
                           f"version {part.version[:8]}", where)
            return [f]
        sel = ref.selector
        if sel is None or not sel.path:
            return None
        feats = self._path(step, sel.path, part, ref, where)
        total = len(feats)
        for p in sel.filter:
            feats = [f for f in feats if self._pred(step, p, f, part, ref)]
        if not feats:
            self._fail(step, "missing_feature", self._missing_message(ref, part, sel, total), where,
                       self._missing_options(step, ref, part, sel, where))
        return feats

    def _path(self, step: Step, path: str, part: PartInfo, ref: Ref, where: str) -> list[Feature]:
        m = re.match(r"^(?P<g>[A-Za-z_][A-Za-z0-9_.]*?)(?:\[(?P<i>[^\]]+)\])?$", path.strip())
        if not m:
            self._fail(step, "unknown_feature", f"{ref.text}: cannot read the feature path {path!r}", where)
        g, idx = m.group("g"), m.group("i")
        groups, names = part.groups(), part.by_name()
        if idx is None:
            if g in names:
                return [names[g]]
            if g in groups and groups[g]:
                return list(groups[g])
            self._fail(step, "unknown_feature", f"{ref.text}: {part.label} has no feature or group {g!r}. "
                       f"It has: {', '.join(sorted(set(groups) | {n for n in names if '[' not in n}))}.", where)
        members = groups.get(g, [])
        if not members:
            self._fail(step, "unknown_feature", f"{ref.text}: {part.label} has no group {g!r}", where)
        if idx == "*":
            return list(members)
        if idx in ("first", "last"):
            return [members[0] if idx == "first" else members[-1]]
        if ".." in idx:
            a, b = (int(x) for x in idx.split(".."))
            if b >= len(members):
                self._fail(step, "unknown_feature", f"{ref.text}: {g} has {len(members)} members (0 to {len(members) - 1})", where)
            return members[a:b + 1]
        k = int(idx)
        if k >= len(members):
            self._fail(step, "unknown_feature", f"{ref.text}: {g} has {len(members)} members (0 to {len(members) - 1})", where)
        return [members[k]]

    def _pred(self, step: Step, p: Predicate, f: Feature, part: PartInfo, ref: Ref) -> bool:
        if p.attr == "kind":
            return str(f.attrs.get("kind", "")).lower() == str(p.value).lower()
        if p.attr == "thread":
            want = str(p.value).upper().split("X")[0]
            return str(f.attrs.get("thread") or "").upper() == want
        if p.attr == "on":
            face = self._on_face(step, str(p.value), part, ref)
            if face is None or f.type != "hole":
                return False
            entry = f.attrs["entry"]
            return abs(sum((e - o) * n for e, o, n in zip(entry, face.origin, face.z))) < 1e-3 and \
                sum(a * b for a, b in zip(f.z, face.z)) > 0.999
        if p.attr == "normal":
            return False
        if isinstance(p.value, str):
            self._fail(step, "bad_filter", f"{ref.text}: {p.attr} needs a number")
        mm = units.normalise(Qty(value=float(p.value), unit=p.unit or "mm")).mm
        if p.attr in ("x", "y", "z"):
            got = f.origin["xyz".index(p.attr)]
        else:
            got = f.attrs.get(p.attr)
            if got is None and p.attr == "area":
                got = f.attrs.get("area")
            if got is None:
                return False
        tol = p.tol if p.tol is not None else (APPROX_TOL_MM if p.op == "≈" else EXACT_TOL_MM)
        return {"=": abs(got - mm) <= tol, "≈": abs(got - mm) <= tol, "<": got < mm, ">": got > mm,
                "<=": got <= mm + EXACT_TOL_MM, ">=": got >= mm - EXACT_TOL_MM}[p.op]

    def _on_face(self, step: Step, text: str, part: PartInfo, ref: Ref) -> Feature | None:
        if text.startswith("."):
            path = text[1:]
        else:
            try:
                m = parse_one(text)
            except ValueError:
                return None
            own = ref.text.lstrip("@").split(".")[0].split("{")[0].lower()
            if m.part.name.lower() != own and m.part.name.lower() != (ref.instance or "").lower():
                return None  # holes on another part's face: not on this part
            path = m.path_text
        found = part.by_name().get(path)
        return found if found is not None and found.type == "face" else None

    def _missing_message(self, ref: Ref, part: PartInfo, sel: Selector, total: int) -> str:
        holes = part.groups().get("holes", [])
        if sel.filter and holes:
            counts: dict[float, int] = {}
            for h in holes:
                counts[h.attrs["diameter"]] = counts.get(h.attrs["diameter"], 0) + 1
            closest = ", ".join(f"{_fmt(d)} mm (x{n})" for d, n in sorted(counts.items()))
            want = " and ".join(f"{p.attr} {p.op} {p.value}{(' ' + p.unit) if p.unit else ''}" for p in sel.filter)
            return f"{ref.text}: {part.label} has no {sel.path.split('[')[0]} with {want}. Present: {closest}."
        return f"{ref.text}: {sel.path} matched nothing on {part.label} ({total} candidates before filtering)."

    def _missing_options(self, step: Step, ref: Ref, part: PartInfo, sel: Selector, where: str) -> list[dict]:
        diam = [p for p in sel.filter if p.attr == "diameter"]
        if not diam:
            return []
        rest = [p for p in sel.filter if p.attr != "diameter"]
        opts = []
        for d in sorted({h.attrs["diameter"] for h in part.groups().get("holes", [])}):
            new = [*rest, Predicate(attr="diameter", op="≈", value=d, unit="mm")]
            opts.append({"label": f"Use {_fmt(d)} mm", "patch": [Patch(step=step.id, set={f"{where}.selector.filter": [
                p.model_dump(mode="json", exclude_none=True) for p in new]}).model_dump()]})
        return opts

    # ------------------------------------------------------------ quantities

    def _qty(self, step: Step, rep: StepReport, q: Qty | None, field_: str, *, length: bool, extra: list[PartInfo] = (),
             default: float | None = None) -> float:
        if q is None:
            if default is None:
                self._fail(step, "missing_value", f"step {step.id} needs a {field_.split('.')[-1]}", field_)
            rep.assumptions.append({"field": field_, "value": default, "reason": f"no {field_.split('.')[-1]} given; using {_fmt(default)}"})
            return default
        try:
            q = units.normalise(q)
        except units.UnitError as exc:
            self._fail(step, "bad_unit", str(exc), field_)
        if length == units.is_angle(q.unit):
            self._fail(step, "unit_mismatch", f"{q.as_typed} is {'an angle' if length else 'a length'}; this needs "
                       f"{'a length' if length else 'an angle'}", field_)
        rep.quantities.append({"field": field_, "as_typed": q.as_typed, "value": q.value, "unit": q.unit, "mm": q.mm,
                               "normalised": units.echo(q), "provenance": q.provenance})
        if q.provenance == "assumed":
            rep.assumptions.append({"field": field_, "value": f"{_fmt(q.value)} mm",
                                    "reason": "no unit was given, so the project default (mm) is assumed"})
        if length and step.id in self.new_ids:  # applied steps were answered when they were applied
            found = units.suspect(q, self.prog.scene_mm(list(extra)))
            if found:
                opts = [{"label": label, "patch": [Patch(step=step.id, set={field_: alt.model_dump(mode="json")}).model_dump()]}
                        for label, alt in found["options"]]
                self._fail(step, "unit_suspect", found["message"], field_, opts)
        return q.mm

    # ------------------------------------------------------------ ops

    def _step(self, step: Step, rep: StepReport) -> None:
        if step.op not in P0_OPS:
            self._fail(step, "planned", f"'{step.op}' is planned for phase {PLANNED.get(step.op, 'P3')} and is not built yet. "
                       "Nothing was faked.")
        getattr(self, f"_op_{step.op}")(step, rep)

    def _op_clarify(self, step: Step, rep: StepReport) -> None:
        c = step.clarify
        q = c.question if c else "The request needs a clarification."
        opts = [{"label": o.label, "patch": []} for o in (c.options if c else [])]
        rep.reading = "Question: " + q
        self._fail(step, "clarify", q + " Answer by rewording the prompt or picking a part with @.", c.field if c else None, opts)

    def _op_add(self, step: Step, rep: StepReport) -> None:
        ref = step.source or step.target
        if ref is None:
            self._fail(step, "missing_source", "add needs a part")
        part = self._part_of_ref(step, ref, "source")
        if ref.source == "instance":
            self._fail(step, "already_added", f"{ref.instance} is already in this composition", "source")
        n = step.quantity or 1
        first = None
        for _ in range(n):
            inst = self._new_instance(step, ref, part, copy_of=first.id if first else None)
            first = first or inst
            rep.instances_added.append(inst.id)
        rep.reading = f"Add {n} x {part.label} ({'catalog' if part.source == 'catalog' else 'your library'}) as {', '.join(rep.instances_added)}."

    def _op_ground(self, step: Step, rep: StepReport) -> None:
        ref = step.source or step.target
        if ref is None:
            self._fail(step, "missing_source", "ground needs a part")
        where = "source" if step.source else "target"
        inst = self._existing(step, ref, where, allow_none=True)
        if inst is None:  # "ground @plate" before adding it: add it now
            inst = self._new_instance(step, ref, self._part_of_ref(step, ref, where))
            rep.instances_added.append(inst.id)
        prev = self.prog.ground
        if prev and prev != inst.id:
            if inst.placed:
                self._fail(step, "already_placed", f"{inst.id} is placed relative to another part, so it cannot also be the base. "
                           "Re-rooting arrives with step editing in P3.", where)
            self.prog.instances[prev].grounded = False
            self.prog.instances[prev].placed = True  # it stays where it was, held by its mates
            rep.warnings.append({"code": "ground_moved", "message": f"the base moves from {prev} to {inst.id}"})
            if not any(m.a == prev or m.b == prev for m in self.prog.mates):
                self.prog.instances[prev].placed = False
        inst.grounded = True
        rep.reading = f"Ground {inst.id}: it is the fixed base of the assembly."

    def _op_place(self, step: Step, rep: StepReport) -> None:
        if step.source is None or step.target is None:
            self._fail(step, "missing_reference", "place needs a part to place and a part or face to place it against")
        tgt_inst = self._target_instance(step, rep)
        tpart = self.prog.part_of(tgt_inst.id)
        tfeats = self.select(step, step.target, tpart, "target")
        src_part = self._part_of_ref(step, step.source, "source")
        anchor = step.anchor or "center"
        if anchor not in ("center", "origin"):
            self._fail(step, "planned", f"anchor '{anchor}' is planned for P3; P0 places by the part's centre or origin", "anchor")
        if step.anchor is None:
            rep.assumptions.append({"field": "anchor", "value": "center", "reason": "the part is centred on the target (bounding-box centre)"})
        off = step.offset
        direction = off.direction if off else None
        if tfeats is not None:
            if len(tfeats) != 1 or tfeats[0].type not in ("face", "port"):
                self._fail(step, "needs_one_face", f"{step.target.text} selects {len(tfeats)} features; place needs exactly one face", "target")
            a_feat = tfeats[0]
            if direction is not None and direction.normal_of is None:
                self._fail(step, "planned", "placing off a face in a direction other than its normal is planned for P3", "offset.direction")
            how = f"{{dist}} mm off {step.target.text} along its outward normal"
        else:
            if direction is None or direction.away_from is not None:
                d = "+X"
                rep.assumptions.append({"field": "offset.direction", "value": d,
                                        "reason": f"away from {tgt_inst.id}'s centre along +X, because the parts are currently aligned on X"})
            elif direction.world:
                d = direction.world
            elif direction.normal_of is not None:
                self._fail(step, "needs_one_face", "a normal direction needs a face, e.g. @plate.face.top", "offset.direction")
                d = "+Z"
            else:
                self._fail(step, "planned", "placing along an axis or edge is planned for P3", "offset.direction")
                d = "+X"
            a_feat = box_face(tpart, WORLD[d])
            how = f"{{dist}} mm from {tgt_inst.id} along {d} (gap between the facing sides)"
        dist = self._qty(step, rep, off.distance if off else None, "offset.distance", length=True, extra=[src_part], default=0.0)
        how = how.replace("{dist}", _fmt(dist))
        src = self._source_instance(step, step.source, rep)
        n = a_feat.z
        b_feat = self._anchor_feature(src_part, anchor, n)
        if step.source_port:
            b_feat = self._named(step, src_part, step.source_port, "source_port")
        mate = self._add_mate(step, rep, tgt_inst.id, a_feat, None, src.id, b_feat, None, type_="fixed", align="opposed",
                              offset=dist, intent="clearance" if dist > EXACT_TOL_MM else "contact")
        src.placed = True
        if tfeats is not None:
            rep.assumptions.append({"field": "orientation", "value": "x aligned",
                                    "reason": f"rotation about the face normal is not given; {src.id} keeps its x axis on "
                                              f"{tgt_inst.id}'s x axis"})
            rep.warnings.append({"code": "under_constrained", "message": f"{src.id} can still turn about the face normal in the "
                                 "design intent (1 DOF not stated). Say how it is aligned to lock it."})
        rep.reading = f"Place {src_part.label} ({src.id}) {how}, {'centred' if anchor == 'center' else 'by its origin'}. Mate {mate.id}: fixed."

    def _anchor_feature(self, part: PartInfo, anchor: str, toward: tuple) -> Feature:
        """The source face that seats toward the target: the side whose outward normal is ``-toward`` (box centre)."""
        opposite = tuple(-c for c in toward)
        if anchor == "origin":
            z = tuple(float(c) for c in opposite)
            return Feature("anchor:origin", ["anchor.origin"], "face", (0.0, 0.0, 0.0), z, perpendicular_x(z), {"role": "origin"})
        try:
            return box_face(part, opposite)
        except StopIteration:  # a non axis-aligned face normal
            return box_face(part, (0, 0, -1))

    def _named(self, step: Step, part: PartInfo, name: str, field_: str) -> Feature:
        names = part.by_name()
        f = names.get(name) or names.get(f"port.{name}")
        if f is None:
            self._fail(step, "unknown_feature", f"{part.label} has no feature or port {name!r}", field_)
        return f

    def _target_instance(self, step: Step, rep: StepReport) -> InstanceState:
        inst = self._existing(step, step.target, "target", allow_none=True)
        if inst is not None:
            return inst
        if self.prog.instances:
            self._existing(step, step.target, "target")  # raises not_in_composition
        # Empty composition: the target becomes the grounded base.
        part = self._part_of_ref(step, step.target, "target")
        inst = self._new_instance(step, step.target, part)
        inst.grounded = True
        rep.instances_added.append(inst.id)
        rep.assumptions.append({"field": "target", "value": inst.id,
                                "reason": f"the composition was empty, so {inst.id} is added and grounded as the base"})
        return inst

    def _axis_feature(self, step: Step, part: PartInfo, feats: list[Feature] | None, ref: Ref, where: str) -> tuple[Feature, str | None]:
        if feats is None:
            f = part.by_name().get("axis.main")
            if f is None:
                self._fail(step, "no_axis", f"{ref.text} has no main axis; name one, e.g. {ref.text}.axis.<name> or a hole", where)
            return f, None
        if len(feats) != 1:
            self._fail(step, "needs_one_axis", f"{ref.text} selects {len(feats)} features; coaxial needs exactly one axis", where)
        f = feats[0]
        if f.type == "hole":
            return f, "axis"
        if f.type == "axis" or (f.port_name and f.attrs.get("contract", {}).get("kind") == "axis"):
            return f, None
        self._fail(step, "needs_one_axis", f"{ref.text} is a {f.type}, not an axis", where)
        return f, None

    def _op_mate(self, step: Step, rep: StepReport) -> None:
        if step.source is None or step.target is None or step.mate is None:
            self._fail(step, "missing_reference", "mate needs a source, a target and a mate kind")
        kind = step.mate.kind
        if kind in ("parallel", "perpendicular", "tangent"):
            self._fail(step, "planned", f"'{kind}' constraints are planned for {'P4' if kind == 'tangent' else 'P3'}", "mate.kind")
        tgt_inst = self._target_instance(step, rep)
        tpart = self.prog.part_of(tgt_inst.id)
        tfeats = self.select(step, step.target, tpart, "target")
        spart = self._part_of_ref(step, step.source, "source")
        sfeats = self.select(step, step.source, spart, "source")
        intent = step.mate.intent
        off = step.offset
        if kind == "coaxial":
            a_feat, a_seat = self._axis_feature(step, tpart, tfeats, step.target, "target")
            b_feat, b_seat = self._axis_feature(step, spart, sfeats, step.source, "source")
            a_z = a_feat.z if a_seat is None else tuple(a_feat.attrs["drill"])
            offset = 0.0
            where_txt = ""
            if off is not None:
                d = self._qty(step, rep, off.distance, "offset.distance", length=True, extra=[spart])
                offset = d
                if off.from_ is not None:
                    ffeats = self.select(step, off.from_, tpart, "offset.from")
                    if ffeats is None or len(ffeats) != 1:
                        self._fail(step, "needs_one_face", "measure the offset from exactly one face of the target part", "offset.from")
                    ff = ffeats[0]
                    a_origin = a_feat.origin if a_seat is None else tuple(a_feat.attrs["entry"])
                    base = sum((f - o) * z for f, o, z in zip(ff.origin, a_origin, a_z))
                    inward = -1.0 if sum(a * b for a, b in zip(ff.z, a_z)) > 0 else 1.0
                    offset = base + inward * d
                    where_txt = f", {_fmt(d)} mm from {off.from_.text}"
                else:
                    where_txt = f", {_fmt(d)} mm along the axis"
            fit = self._fit(step, rep, a_feat, b_feat, spart)
            intent = intent or fit
            jtype = "fixed" if (off is not None or intent in ("press_fit", "welded", "bolted")) else "cylindrical"
            src = self._source_instance(step, step.source, rep)
            mate = self._add_mate(step, rep, tgt_inst.id, a_feat, a_seat, src.id, b_feat, b_seat, type_=jtype, align="aligned",
                                  offset=round(offset, 9), intent=intent)
            src.placed = True
            rep.reading = (f"Mount {spart.label} ({src.id}) coaxial with {step.target.text}{where_txt}; "
                           f"{'fixed' if jtype == 'fixed' else 'free to turn and slide'} ({mate.id}"
                           f"{', ' + intent.replace('_', ' ') if intent else ''}).")
            return
        if kind == "coincident" or tfeats is not None and sfeats is None and kind in ("fixed", "planar"):
            if tfeats is None or len(tfeats) != 1:
                self._fail(step, "needs_one_face", f"{step.target.text}: name exactly one face to sit on", "target")
            a_feat = tfeats[0]
            b_feat = sfeats[0] if sfeats and len(sfeats) == 1 else self._anchor_feature(spart, "center", a_feat.z)
            if sfeats is None:
                rep.assumptions.append({"field": "source", "value": b_feat.name,
                                        "reason": f"the side of {spart.label} facing the target ({b_feat.name}) sits on it"})
            src = self._source_instance(step, step.source, rep)
            mate = self._add_mate(step, rep, tgt_inst.id, a_feat, None, src.id, b_feat, None,
                                  type_="planar" if kind == "planar" else "fixed", align="opposed", offset=0.0,
                                  intent=intent or "contact")
            src.placed = True
            rep.reading = f"Sit {spart.label} ({src.id}) {b_feat.name} on {step.target.text}, face to face ({mate.id})."
            return
        # Joint kinds on named ports.
        if tfeats is None or sfeats is None or len(tfeats) != 1 or len(sfeats) != 1:
            self._fail(step, "needs_ports", f"a {kind} joint needs one named feature on each part, e.g. @hinge.axis.main")
        angle = self._qty(step, rep, step.mate.angle, "mate.angle", length=False) if step.mate.angle else 0.0
        limits = None
        if step.mate.limits:
            is_len = kind == "slider"
            lo = self._qty(step, rep, step.mate.limits[0], "mate.limits[0]", length=is_len)
            hi = self._qty(step, rep, step.mate.limits[1], "mate.limits[1]", length=is_len)
            limits = (lo, hi)
        src = self._source_instance(step, step.source, rep)
        a_seat = "axis" if tfeats[0].type == "hole" else None
        b_seat = "axis" if sfeats[0].type == "hole" else None
        mate = self._add_mate(step, rep, tgt_inst.id, tfeats[0], a_seat, src.id, sfeats[0], b_seat, type_=kind,
                              align="opposed" if step.mate.flip else None, offset=0.0, angle=angle, limits=limits, intent=intent)
        src.placed = True
        rep.reading = f"Join {spart.label} ({src.id}) to {step.target.text} with a {kind} joint ({mate.id})."

    def _fit(self, step: Step, rep: StepReport, a_feat: Feature, b_feat: Feature, spart: PartInfo) -> str | None:
        ca, cb = a_feat.attrs.get("contract", {}), b_feat.attrs.get("contract", {})
        da = ca.get("bore_d") if a_feat.type != "hole" else a_feat.attrs.get("diameter")
        db = cb.get("bore_d")
        if da is None or db is None:
            return None
        if abs(float(da) - float(db)) > 0.01:
            self._fail(step, "fit_mismatch", f"{spart.label} has a {_fmt(db)} mm bore, but the target axis is {_fmt(da)} mm.",
                       "source")
        rep.assumptions.append({"field": "mate.intent", "value": "press_fit",
                                "reason": f"bore {_fmt(db)} mm on a {_fmt(da)} mm shaft: a bearing seat is assumed to be a press fit"})
        return "press_fit"

    def _op_insert(self, step: Step, rep: StepReport) -> None:
        if step.source is None or step.target is None:
            self._fail(step, "missing_reference", "insert needs a part and the features to put it in")
        if step.source.source == "instance":
            self._fail(step, "needs_library_part", "insert places new copies of a library or catalog part; mention the part, "
                       "not an instance", "source")
        tgt_inst = self._existing(step, step.target, "target")
        tpart = self.prog.part_of(tgt_inst.id)
        target = step.target
        if target.selector is None or not target.selector.path:
            target = target.model_copy(update={"selector": Selector(path="holes[*]")})
            rep.assumptions.append({"field": "target.selector.path", "value": "holes[*]", "reason": "every hole on the part"})
        feats = self.select(step, target, tpart, "target")
        holes = [f for f in feats if f.type == "hole"]
        if len(holes) != len(feats):
            self._fail(step, "needs_holes", f"{target.text}: insert goes into holes; the selection has other features", "target")
        sel = target.selector
        rep.filters.append({"text": target.text, "path": sel.path, "filter": [p.model_dump(mode="json", exclude_none=True) for p in sel.filter],
                            "count": len(holes), "of": len(tpart.groups().get("holes", []))})
        if sel.expected_count is None:
            step.target = target.model_copy(update={"selector": sel.model_copy(update={"expected_count": len(holes)})})
        elif sel.expected_count != len(holes):
            accept = Patch(step=step.id, set={"target.selector.expected_count": len(holes)}).model_dump()
            self._fail(step, "selection_changed", f"Holes selected on {tgt_inst.id} went from {sel.expected_count} to {len(holes)}. "
                       f"This step would add {len(holes)} parts instead of {sel.expected_count}.", "target.selector",
                       [{"label": f"Accept {len(holes)}", "patch": [accept]}])
        spart = self._part_of_ref(step, step.source, "source")
        size = _thread_size(spart)
        if size:
            bad = [h for h in holes if not _fits(size, h)]
            if bad:
                self._fit_blocker(step, size, holes, bad, spart, target)
        seat = step.seat or "entry"
        if step.seat is None:
            rep.assumptions.append({"field": "seat", "value": "entry", "reason": "seated on the face the hole is drilled from"})
        if seat not in ("entry", "exit"):
            self._fail(step, "planned", f"seat '{seat}' is planned for P3; P0 seats on the entry or exit face", "seat")
        if seat == "exit" and any(h.attrs.get("kind") == "blind" for h in holes):
            self._fail(step, "blind_exit", "a blind hole has no exit face to seat on", "seat")
        b_feat = self._seat_feature(step, spart)
        first = None
        for h in holes:
            inst = self._new_instance(step, step.source, spart, copy_of=first.id if first else None)
            first = first or inst
            rep.instances_added.append(inst.id)
            self._add_mate(step, rep, tgt_inst.id, h, seat, inst.id, b_feat, None, type_="fixed", align="opposed", offset=0.0,
                           intent="contact")
            inst.placed = True
        diam = sorted({h.attrs["diameter"] for h in holes})
        face = {"entry": "entry", "exit": "exit"}[seat]
        rep.reading = (f"Place {len(holes)} x {spart.label}, one per {'/'.join('Ø' + _fmt(d) for d in diam)} hole on "
                       f"{tgt_inst.id}, coaxial, seated on the {face} face ({len(holes)} instances, {len(holes)} mates).")

    def _seat_feature(self, step: Step, spart: PartInfo) -> Feature:
        if step.source_port:
            return self._named(step, spart, step.source_port, "source_port")
        faces = [f for f in spart.features if f.port_name and f.type == "face"]
        if faces:
            return faces[0]
        return box_face(spart, (0, 0, -1))

    def _fit_blocker(self, step: Step, size: str, holes: list[Feature], bad: list[Feature], spart: PartInfo, target: Ref) -> None:
        good = [h for h in holes if h not in bad]
        by_d: dict[float, int] = {}
        for h in bad:
            by_d[h.attrs["diameter"]] = by_d.get(h.attrs["diameter"], 0) + 1
        parts = []
        for d, n in sorted(by_d.items()):
            s = _suits(d)
            parts.append(f"{n} of {len(holes)} holes are Ø{_fmt(d)}" + (f" ({s} clearance)" if s else ""))
        msg = "; ".join(parts) + f". {spart.label} is {size}."
        sel = target.selector
        opts = []
        good_d = sorted({h.attrs["diameter"] for h in good})
        if len(good_d) == 1:
            flt = [*(p.model_dump(mode="json", exclude_none=True) for p in sel.filter if p.attr != "diameter"),
                   {"attr": "diameter", "op": "≈", "value": good_d[0], "unit": "mm"}]
            only = Patch(step=step.id, set={"target.selector.filter": flt, "target.selector.expected_count": len(good)}).model_dump()
            opts.append({"label": f"Only the {len(good)} Ø{_fmt(good_d[0])} holes", "patch": [only]})
            alt = self._sibling_size(spart, by_d)
            if alt is not None and len(by_d) == 1:
                d_bad = next(iter(by_d))
                new_step = step.model_dump(mode="json", by_alias=True, exclude_none=True)
                new_step.update({"id": "", "source": alt, "acknowledged": []})
                new_step["target"]["selector"] = {"path": sel.path, "filter": [
                    *(p.model_dump(mode="json", exclude_none=True) for p in sel.filter if p.attr != "diameter"),
                    {"attr": "diameter", "op": "≈", "value": d_bad, "unit": "mm"}], "expected_count": len(bad)}
                opts.append({"label": f"Also use {alt['text'].lstrip('@')} in the Ø{_fmt(d_bad)} holes",
                             "patch": [only, Patch(append_step=new_step).model_dump()]})
        opts.append({"label": f"All {len(holes)} (with a warning)", "patch": [Patch(step=step.id, acknowledge="fit_mismatch").model_dump()]})
        self._fail(step, "fit_mismatch", msg + " Insert into which holes?", "target.selector", opts)

    def _sibling_size(self, spart: PartInfo, by_d: dict[float, int]) -> dict | None:
        """The same catalog part in the size the mismatched holes suit (an M8 nut for M8 clearance holes)."""
        if spart.source != "catalog" or not spart.params or "standard" not in spart.params:
            return None
        sizes = {_suits(d) for d in by_d}
        if len(sizes) != 1 or None in sizes:
            return None
        size = sizes.pop()
        std = spart.params["standard"]
        hits = catalog_hits(f"{std} {size}")
        hits = [h for h in hits if h["generator"] == spart.generator]
        if len(hits) != 1:
            return None
        h = hits[0]
        from .features import params_hash

        text = f"@{str(std).upper()}-{size}"
        return {"text": text, "source": "catalog", "item": f"catalog:{h['generator']}", "version": params_hash(h["params"]),
                "generator": h["generator"], "params": h["params"]}

    # ------------------------------------------------------------ mates

    def _add_mate(self, step: Step, rep: StepReport, a: str, a_feat: Feature, a_seat: str | None, b: str, b_feat: Feature,
                  b_seat: str | None, *, type_: str, align: str | None, offset: float, intent: str | None,
                  angle: float = 0.0, limits: tuple[float, float] | None = None) -> MatePlan:
        n = sum(1 for m in self.prog.mates if m.step_id == step.id) + 1
        plan = MatePlan(f"{step.id}_m{n}", step.id, a, a_feat, a_seat, b, b_feat, b_seat, type_, align, round(offset, 9),
                        round(angle, 9), limits, intent)
        self.prog.mates.append(plan)
        rep.mates_added.append(plan.id)
        return plan


def apply_patches(steps: list[Step], patches: list[dict]) -> list[Step]:
    """Apply answer patches (deterministic): set dotted fields, acknowledge a code, or append a step."""
    data = [s.model_dump(mode="json", by_alias=True, exclude_none=True) for s in steps]
    for raw in patches:
        p = Patch.model_validate(raw)
        if p.append_step is not None:
            new = dict(p.append_step)
            nums = [int(d["id"][1:]) for d in data]
            new["id"] = f"s{max(nums, default=0) + 1}"
            data.append(new)
            continue
        target = next((d for d in data if d["id"] == p.step), None)
        if target is None:
            raise ValueError(f"answer refers to unknown step {p.step!r}")
        if p.acknowledge:
            ack = target.setdefault("acknowledged", [])
            if p.acknowledge not in ack:
                ack.append(p.acknowledge)
        for path, value in p.set.items():
            _set_path(target, path, value)
    return [Step.model_validate(d) for d in data]


def _set_path(obj: dict, path: str, value: Any) -> None:
    keys = path.split(".")
    if not all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k) for k in keys) or len(keys) > 5:
        raise ValueError(f"bad patch path {path!r}")
    cur = obj
    for k in keys[:-1]:
        nxt = cur.get(k)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[k] = nxt
        cur = nxt
    cur[keys[-1]] = value
