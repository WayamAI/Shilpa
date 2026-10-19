"""Independent assembly checks on a placed result (roadmap layer 5, stage S3).

Every check measures the placed B-reps with plain OCCT passes (boolean common,
BRepExtrema distance) rather than trusting the spec: a mate that says "fixed"
must actually touch, a hinge that says it swings to 100 degrees must actually
clear its neighbours along the way. FreeCAD's Assembly workbench has no
interference tool, so these are Shilpa's own.

Swept motion moves one joint at a time across its limits with every other
joint at its assembled value; coupled multi-joint sweeps are not sampled.
"""

from __future__ import annotations

import json
from collections.abc import Collection
from dataclasses import asdict, dataclass, field
from itertools import combinations

import numpy as np
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps

from ..assembly.build import AssemblyBuild
from ..contracts.assembly import SWEPT, part_number
from .geometry import Check

BBOX_SLACK = 1e-3  # mm; boxes closer than this are tested exactly


@dataclass
class PairResult:
    a: str
    b: str
    interference_volume: float
    allowed_volume: float


@dataclass
class AssemblyReport:
    passed: bool
    checks: list[Check] = field(default_factory=list)
    placements: dict[str, list[list[float]]] = field(default_factory=dict)
    interferences: list[PairResult] = field(default_factory=list)
    dof: dict = field(default_factory=dict)
    bom: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return json.loads(json.dumps(asdict(self), default=float))

    def check(self, name: str) -> Check:
        return next(c for c in self.checks if c.name == name)

    @property
    def failed(self) -> list[str]:
        return [c.name for c in self.checks if not c.passed]


def _r(v: float, nd: int = 6) -> float:
    return round(float(v), nd)


def common_volume(s1, s2) -> float:
    op = BRepAlgoAPI_Common(s1.wrapped, s2.wrapped)
    if not op.IsDone():
        raise RuntimeError("boolean common failed")
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(op.Shape(), props)
    return abs(props.Mass())


def min_distance(s1, s2) -> float:
    d = BRepExtrema_DistShapeShape(s1.wrapped, s2.wrapped)
    if not d.IsDone():
        raise RuntimeError("BRepExtrema failed")
    return d.Value()


def _boxes_touch(b1, b2, slack: float = BBOX_SLACK) -> bool:
    lo1, hi1, lo2, hi2 = (tuple(v) for v in (b1.min, b1.max, b2.min, b2.max))
    return all(lo1[k] <= hi2[k] + slack and lo2[k] <= hi1[k] + slack for k in range(3))


def _pair(a: str, b: str) -> str:
    return "+".join(sorted((a, b)))


class _Interference:
    """Pairwise clash test with a bbox prefilter, honouring the spec's whitelist."""

    def __init__(self, build: AssemblyBuild):
        self.spec = build.spec
        self.threshold = build.spec.tolerances.interference_volume
        # Optimal boxes cost milliseconds each and every solid meets many partners (all pairs, every swept
        # pose), so each is computed once. Holding the shape keeps its id from being reused while cached.
        self._boxes: dict[int, tuple] = {}

    def box(self, s):
        hit = self._boxes.get(id(s))
        if hit is None:
            hit = self._boxes[id(s)] = (s, s.bounding_box())
        return hit[1]

    def allowed(self, a: str, b: str) -> float:
        w = self.spec.allowance(a, b)
        return max(w.max_volume, self.threshold) if w else self.threshold

    def volume(self, s1, s2) -> float:
        if not _boxes_touch(self.box(s1), self.box(s2)):
            return 0.0
        return common_volume(s1, s2)


def bill_of_materials(build: AssemblyBuild) -> list[dict]:
    """One line per part number: quantity, source, instances and volume of one item."""
    lines: dict[str, dict] = {}
    for inst in build.spec.instances:
        pn = part_number(build.spec, inst.id)
        root = build.spec.root_of(inst.id)
        part = build.parts.get(inst.id)
        line = lines.setdefault(pn, {"part_number": pn, "quantity": 0, "source": root.source, "instances": [],
                                     "name": part.name if part else None,
                                     "volume_mm3": _r(part.solid.volume, 3) if part else None,
                                     "generator": getattr(root.ref, "generator", None)})
        line["quantity"] += inst.quantity
        line["instances"].append(inst.id)
    return list(lines.values())


def validate_assembly(build: AssemblyBuild, skip_sweeps: Collection[str] = ()) -> AssemblyReport:
    """Run every assembly check. ``skip_sweeps`` names joints whose swept motion the caller measures
    itself (a product check with exact clearances); they are reported as skipped, not sampled here."""
    spec = build.spec
    tol = spec.tolerances
    checks: list[Check] = []

    # -- spec and build integrity
    errors = [i for i in build.issues if i.severity == "error"]
    checks.append(Check("spec_valid", not errors, actual=[i.code for i in build.issues] or None,
                        note="; ".join(i.message for i in build.issues) or None))
    for iid, err in build.errors.items():
        checks.append(Check(f"part_built[{iid}]", False, note=f"{err.code}: {err.message}"))
    empty = [iid for iid, p in build.parts.items() if p.solid is None or p.solid.volume <= 1e-9]
    checks.append(Check("bom_built", not build.errors and not empty, len(spec.instances), len(build.parts) - len(empty),
                        note=f"no geometry: {sorted(set(build.errors) | set(empty))}" if build.errors or empty else None))
    bom = bill_of_materials(build)
    if spec.bom is not None:
        got = {line["part_number"]: line["quantity"] for line in bom}
        checks.append(Check("bom_quantities", got == spec.bom, spec.bom, got))
    checks.append(Check("all_placed", not build.unplaced, actual=build.unplaced or None,
                        note="not connected to the ground by resolvable mates" if build.unplaced else None))

    # -- static interference, every placed pair
    clash = _Interference(build)
    pairs: list[PairResult] = []
    for a, b in combinations([i.id for i in spec.instances if i.id in build.placed], 2):
        vol = clash.volume(build.placed[a], build.placed[b])
        allowed = clash.allowed(a, b)
        listed = spec.allowance(a, b) is not None
        if vol > 1e-6 or listed:
            pairs.append(PairResult(a, b, _r(vol, 4), allowed))
            checks.append(Check(f"interference[{_pair(a, b)}]", vol <= allowed, allowed, _r(vol, 4), "mm^3",
                                "whitelisted" if listed else None))
    bad = [_pair(p.a, p.b) for p in pairs if p.interference_volume > p.allowed_volume]
    checks.append(Check("interference", not bad, 0, bad or 0, tol.interference_volume, "clashing pairs" if bad else None))

    # -- clearance targets
    for t in spec.clearances:
        if t.a not in build.placed or t.b not in build.placed:
            checks.append(Check(f"clearance[{_pair(t.a, t.b)}]", False, note="pair not placed"))
            continue
        d = min_distance(build.placed[t.a], build.placed[t.b])
        ok = d >= t.min - 1e-9 and (t.max is None or d <= t.max + 1e-9)
        checks.append(Check(f"clearance[{_pair(t.a, t.b)}]", ok, [t.min, t.max], _r(d, 4), note="mm, minimum distance"))

    # -- contact gap: rigid joints must actually touch
    for m in spec.mates:
        rigid = m.type == "fixed" or m.intent in ("welded", "bolted", "press_fit", "contact")
        if not rigid or m.intent == "clearance":
            continue
        if m.inst_a not in build.placed or m.inst_b not in build.placed:
            checks.append(Check(f"contact[{m.name}]", False, note="mate not placed"))
            continue
        d = min_distance(build.placed[m.inst_a], build.placed[m.inst_b])
        checks.append(Check(f"contact[{m.name}]", d <= tol.contact_gap, 0, _r(d, 4), tol.contact_gap, "mm gap between mated parts"))

    # -- DOF accounting over the placement tree
    by_mate = {m.name: m.dof for m, _ in build.order}
    total = sum(by_mate.values())
    dof = {"computed": total, "intended": spec.dof, "by_mate": by_mate}
    checks.append(Check("dof", spec.dof is None or total == spec.dof, spec.dof, total,
                        note=None if spec.dof is not None else "no intended DOF given"))

    # -- swept motion: one joint at a time across its limits
    for m, _ in build.order:
        if m.type not in SWEPT or m.limits is None:
            continue
        if m.name in skip_sweeps:
            checks.append(Check(f"sweep[{m.name}]", True, list(m.limits), None, note="measured by the caller (skipped here)"))
            continue
        moving = build.moving_side(m)
        if not moving <= set(build.placed):
            continue
        static = [i for i in build.placed if i not in moving]
        hits = []
        for value in np.linspace(m.limits[0], m.limits[1], tol.sweep_steps):
            T = build.pose({m.name: {SWEPT[m.type]: float(value)}})
            for mv in sorted(moving):
                s_mv = build.world_solid(mv, T[mv])
                for st in static:
                    vol = clash.volume(s_mv, build.placed[st])
                    if vol > clash.allowed(mv, st):
                        hits.append({"value": _r(value, 4), "pair": _pair(mv, st), "volume": _r(vol, 4)})
        unit = "mm" if SWEPT[m.type] == "offset" else "deg"
        checks.append(Check(f"sweep[{m.name}]", not hits, list(m.limits), hits[:5] or None, tol.interference_volume,
                            f"{tol.sweep_steps} samples in {unit}; first collision at {hits[0]['value']} {unit}" if hits else
                            f"{tol.sweep_steps} samples in {unit}"))

    return AssemblyReport(all(c.passed for c in checks), checks, build.placement_table(), pairs, dof, bom)
