"""Assembly specification: part instances, mates and their checks (roadmap layer 3, stage S3).

An ``AssemblySpec`` is fixed before any part geometry exists. It lists part
*instances* (each resolved by a part source into a ``BuiltPart`` with ports),
*mates* that connect one instance's port to another's, one grounded instance,
the intended mechanism DOF, and the interference and clearance expectations the
layer-5 validator checks the placed result against.

Mate graphs must be trees rooted at the ground (as in ArtiCAD); closed loops
belong inside one part (a weldment on a skeleton), not in the mate graph.

Placement convention (implemented in ``shilpa/assembly/build.py``). A port frame
P maps port-local coordinates to part-local ones (columns x, y = z cross x, z,
origin). For a mate ``a -> b`` the child's part-to-world transform is::

    T_b = T_a @ P_a @ M @ inverse(P_b)
    M   = Translate(xy[0], xy[1], offset) @ RotZ(angle) @ F

with ``F`` a 180 degree turn about x when the mate is *opposed* (b's z points
against a's z, the face-to-face case; x axes stay aligned) and identity when it
is *aligned* (coaxial: z and x coincide). ``align`` defaults to opposed for
fixed, planar and ball mates and aligned for revolute, slider, cylindrical and
screw joints. ``angle`` is in degrees about a's z, ``offset`` in mm along a's z.
For a revolute joint ``angle`` is the assembled joint position and ``limits``
its range in degrees; for a slider ``offset`` is the position and ``limits`` mm;
a screw advances ``pitch / 360`` mm along z per degree turned away from its
assembled ``angle``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .ir import Recipe
from .ports import PartSource, Port

InstanceId = str
MateType = Literal["fixed", "revolute", "slider", "cylindrical", "ball", "planar", "screw"]
MateIntent = Literal["welded", "bolted", "press_fit", "clearance", "contact"]

JOINT_DOF: dict[str, int] = {"fixed": 0, "revolute": 1, "slider": 1, "cylindrical": 2, "ball": 3, "planar": 3, "screw": 1}
OPPOSED_BY_DEFAULT = {"fixed", "planar", "ball"}
# Joints whose range the swept-motion check samples, and which value the limits bound.
SWEPT = {"revolute": "angle", "slider": "offset", "cylindrical": "angle", "screw": "angle"}
# Contract keys that must differ rather than agree (a male thread mates a female one).
COMPLEMENTARY_KEYS = {"gender"}
CONTRACT_REL_TOL = 1e-6

_ID = r"^[a-z][a-z0-9_]{0,63}$"
_REF = r"^[a-z][a-z0-9_]{0,63}\.[a-z][a-z0-9_]{0,63}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RecipeRef(_Strict):
    """A make-part from a typed recipe. The part IR has no ports, so they are declared here."""

    recipe: Recipe
    ports: list[Port] = Field(default_factory=list)


class GeneratorRef(_Strict):
    """A catalog, weldment or sheet-metal part. ``ports`` add to or override the generator's own."""

    generator: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    ports: list[Port] = Field(default_factory=list)


class MirrorOf(_Strict):
    instance: InstanceId = Field(pattern=_ID)
    plane: Literal["XY", "XZ", "YZ"] = "YZ"  # part-local mirror plane


class Instance(_Strict):
    id: InstanceId = Field(pattern=_ID)
    source: PartSource = "recipe"
    ref: RecipeRef | GeneratorRef | None = None
    copy_of: InstanceId | None = Field(default=None, pattern=_ID)  # same geometry and ports, built once
    mirror_of: MirrorOf | None = None
    quantity: int = Field(default=1, ge=1)  # BOM count this instance stands for (e.g. a fastener set)
    part_number: str | None = None  # BOM line key; defaults to the copy root's id
    color: str | None = None  # CSS name or #rrggbb, carried into STEP
    grounded: bool = False

    @model_validator(mode="after")
    def _one_reference(self):
        derived = (self.copy_of is not None) + (self.mirror_of is not None)
        if derived > 1:
            raise ValueError(f"instance {self.id}: give copy_of or mirror_of, not both")
        if derived:
            if self.ref is not None:
                raise ValueError(f"instance {self.id}: a copy or mirror takes no ref of its own")
            return self
        if self.ref is None:
            raise ValueError(f"instance {self.id}: needs a ref, copy_of or mirror_of")
        if self.source == "recipe" and not isinstance(self.ref, RecipeRef):
            raise ValueError(f"instance {self.id}: recipe parts need ref.recipe")
        if self.source != "recipe" and not isinstance(self.ref, GeneratorRef):
            raise ValueError(f"instance {self.id}: {self.source} parts need ref.generator")
        return self


class Mate(_Strict):
    id: str | None = Field(default=None, pattern=_ID)
    a: str = Field(pattern=_REF)  # "instance.port", the side nearer the ground by convention
    b: str = Field(pattern=_REF)
    type: MateType = "fixed"
    align: Literal["opposed", "aligned"] | None = None  # None: the default for the type (module docstring)
    offset: float = 0.0  # mm along a's z
    angle: float = 0.0  # degrees about a's z
    xy: tuple[float, float] = (0.0, 0.0)  # mm in a's x/y plane (planar positions, bolt-circle shifts)
    pitch: float | None = None  # mm per turn, screw joints only
    limits: tuple[float, float] | None = None  # degrees (revolute, cylindrical, screw) or mm (slider)
    intent: MateIntent | None = None

    @model_validator(mode="after")
    def _consistent(self):
        if self.a.split(".")[0] == self.b.split(".")[0]:
            raise ValueError(f"mate {self.a} - {self.b}: both ends on one instance")
        if self.limits is not None:
            if self.type not in SWEPT:
                raise ValueError(f"mate {self.a} - {self.b}: limits only apply to {sorted(SWEPT)} joints")
            if self.limits[0] > self.limits[1]:
                raise ValueError(f"mate {self.a} - {self.b}: limits must be (low, high)")
        if self.type == "screw" and not self.pitch:
            raise ValueError(f"mate {self.a} - {self.b}: screw joints need a pitch")
        return self

    @property
    def name(self) -> str:
        return self.id or f"{self.a}~{self.b}"

    @property
    def inst_a(self) -> str:
        return self.a.split(".")[0]

    @property
    def inst_b(self) -> str:
        return self.b.split(".")[0]

    @property
    def port_a(self) -> str:
        return self.a.split(".")[1]

    @property
    def port_b(self) -> str:
        return self.b.split(".")[1]

    @property
    def opposed(self) -> bool:
        return (self.align or ("opposed" if self.type in OPPOSED_BY_DEFAULT else "aligned")) == "opposed"

    @property
    def dof(self) -> int:
        return JOINT_DOF[self.type]


class InterferenceAllowance(_Strict):
    """A pair allowed to overlap: press fits and modelled threads."""

    a: InstanceId = Field(pattern=_ID)
    b: InstanceId = Field(pattern=_ID)
    max_volume: float = Field(ge=0)  # mm^3
    reason: Literal["press_fit", "thread", "other"] = "press_fit"


class ClearanceTarget(_Strict):
    a: InstanceId = Field(pattern=_ID)
    b: InstanceId = Field(pattern=_ID)
    min: float = Field(default=0.0, ge=0)  # mm, minimum distance between the two parts
    max: float | None = None


class Tolerances(_Strict):
    interference_volume: float = 1.0  # mm^3 of unlisted overlap that counts as a clash
    contact_gap: float = 0.01  # mm; a fixed mate whose parts are farther apart is hovering
    sweep_steps: int = Field(default=8, ge=2)  # samples across a joint's limits, ends included


class AssemblySpec(_Strict):
    schema_version: Literal["1.0"] = "1.0"
    name: str | None = None
    units: Literal["mm"] = "mm"
    instances: list[Instance] = Field(min_length=1, max_length=200)
    mates: list[Mate] = Field(default_factory=list)
    dof: int | None = Field(default=None, ge=0)  # intended mechanism DOF
    interference_allowed: list[InterferenceAllowance] = Field(default_factory=list)
    clearances: list[ClearanceTarget] = Field(default_factory=list)
    bom: dict[str, int] | None = None  # expected quantity per part number
    tolerances: Tolerances = Field(default_factory=Tolerances)

    @model_validator(mode="after")
    def _structure(self):
        ids = [i.id for i in self.instances]
        dup = sorted({i for i in ids if ids.count(i) > 1})
        if dup:
            raise ValueError(f"duplicate instance ids: {dup}")
        names = [m.name for m in self.mates]
        dup = sorted({n for n in names if names.count(n) > 1})
        if dup:
            raise ValueError(f"duplicate mate ids: {dup}")
        by_id = {i.id: i for i in self.instances}
        for inst in self.instances:
            seen = [inst.id]
            cur = inst
            while (parent := cur.copy_of or (cur.mirror_of.instance if cur.mirror_of else None)) is not None:
                if parent not in by_id:
                    raise ValueError(f"instance {cur.id}: copies unknown instance {parent!r}")
                if parent in seen:
                    raise ValueError(f"instance {inst.id}: copy/mirror chain loops through {parent!r}")
                seen.append(parent)
                cur = by_id[parent]
        return self

    def instance(self, iid: str) -> Instance:
        return next(i for i in self.instances if i.id == iid)

    def root_of(self, iid: str) -> Instance:
        """The instance that actually carries the reference (end of a copy/mirror chain)."""
        inst = self.instance(iid)
        while inst.copy_of or inst.mirror_of:
            inst = self.instance(inst.copy_of or inst.mirror_of.instance)
        return inst

    def allowance(self, a: str, b: str) -> InterferenceAllowance | None:
        return next((w for w in self.interference_allowed if {w.a, w.b} == {a, b}), None)


# ---------------------------------------------------------------- static validation


@dataclass
class SpecIssue:
    code: str  # unknown_instance | unknown_port | no_ground | multiple_grounds | unreachable | cycle
    #            | port_contract_mismatch | unknown_pair
    message: str
    where: list[str] = field(default_factory=list)  # instance ids, "inst.port" refs or mate names
    severity: Literal["error", "warning"] = "error"


def declared_ports(spec: AssemblySpec) -> dict[str, dict[str, Port] | None]:
    """Ports known without building anything. None when a generator may add ports of its own."""
    out: dict[str, dict[str, Port] | None] = {}
    for inst in spec.instances:
        root = spec.root_of(inst.id)
        ports = {p.name: p for p in root.ref.ports} if root.ref else {}
        out[inst.id] = ports if isinstance(root.ref, RecipeRef) else (ports or None)
    return out


def contracts_compatible(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    """Shared contract keys that disagree. Numbers compare with a relative tolerance, strings case-insensitively."""
    bad = []
    for key in sorted(set(a) & set(b)):
        va, vb = a[key], b[key]
        if key in COMPLEMENTARY_KEYS:
            if str(va).lower() == str(vb).lower():
                bad.append(f"{key}: both {va!r}")
            continue
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)) and not isinstance(va, bool):
            ok = math.isclose(float(va), float(vb), rel_tol=CONTRACT_REL_TOL, abs_tol=1e-9)
        elif isinstance(va, str) and isinstance(vb, str):
            ok = va.strip().lower() == vb.strip().lower()
        else:
            ok = va == vb
        if not ok:
            bad.append(f"{key}: {va!r} vs {vb!r}")
    return bad


def spanning_tree(spec: AssemblySpec, ground: str | None, mates: list[Mate] | None = None
                  ) -> tuple[list[tuple[Mate, bool]], set[str], list[Mate]]:
    """Breadth-first mate order from the ground.

    Returns ``(order, reached, closing)``: ``order`` lists ``(mate, forward)`` where forward means
    ``mate.a`` was placed first; ``closing`` lists mates whose two ends were already connected
    (each closes a loop). Mates touching unknown instances are ignored. Order is deterministic:
    breadth-first, mates taken in spec order. ``mates`` restricts the graph (default: all).
    """
    known = {i.id for i in spec.instances}
    mates = [m for m in (spec.mates if mates is None else mates) if m.inst_a in known and m.inst_b in known]
    reached: set[str] = set()
    order: list[tuple[Mate, bool]] = []
    used: set[int] = set()
    if ground in known:
        reached.add(ground)
        queue = [ground]
        while queue:
            cur = queue.pop(0)
            for k, m in enumerate(mates):
                if k in used or cur not in (m.inst_a, m.inst_b):
                    continue
                other = m.inst_b if m.inst_a == cur else m.inst_a
                if other in reached:
                    continue
                used.add(k)
                order.append((m, m.inst_a == cur))
                reached.add(other)
                queue.append(other)
    # Any mate not in the tree whose ends are both reached closes a loop; loops among unreached
    # parts are found with a union-find over the leftovers.
    parent: dict[str, str] = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for m, _ in order:
        parent[find(m.inst_a)] = find(m.inst_b)
    closing = []
    for k, m in enumerate(mates):
        if k in used:
            continue
        ra, rb = find(m.inst_a), find(m.inst_b)
        if ra == rb:
            closing.append(m)
        else:
            parent[ra] = rb
    return order, reached, closing


def _tree_path(order: list[tuple[Mate, bool]], a: str, b: str) -> list[str]:
    """Instances on the tree path from a to b (for reporting the loop a closing mate makes)."""
    adj: dict[str, list[str]] = {}
    for m, _ in order:
        adj.setdefault(m.inst_a, []).append(m.inst_b)
        adj.setdefault(m.inst_b, []).append(m.inst_a)
    prev = {a: None}
    queue = [a]
    while queue:
        cur = queue.pop(0)
        for nxt in adj.get(cur, []):
            if nxt not in prev:
                prev[nxt] = cur
                queue.append(nxt)
    if b not in prev:
        return [a, b]
    path = [b]
    while path[-1] != a:
        path.append(prev[path[-1]])
    return path[::-1]


def check_spec(spec: AssemblySpec, ports: dict[str, dict[str, Port] | None] | None = None) -> list[SpecIssue]:
    """Static checks before (``ports`` from declarations) or after building (``ports`` from BuiltParts)."""
    ports = declared_ports(spec) if ports is None else ports
    known = {i.id for i in spec.instances}
    issues: list[SpecIssue] = []

    grounds = [i.id for i in spec.instances if i.grounded]
    if not grounds:
        issues.append(SpecIssue("no_ground", "no instance is grounded"))
    elif len(grounds) > 1:
        issues.append(SpecIssue("multiple_grounds", f"{len(grounds)} grounded instances; exactly one is allowed", grounds))

    for m in spec.mates:
        for ref, iid, pname in ((m.a, m.inst_a, m.port_a), (m.b, m.inst_b, m.port_b)):
            if iid not in known:
                issues.append(SpecIssue("unknown_instance", f"mate {m.name} references unknown instance {iid!r}", [ref]))
            elif ports.get(iid) is not None and pname not in ports[iid]:
                issues.append(SpecIssue("unknown_port", f"instance {iid!r} has no port {pname!r}; has {sorted(ports[iid])}", [ref]))
        pa, pb = (ports.get(m.inst_a) or {}).get(m.port_a), (ports.get(m.inst_b) or {}).get(m.port_b)
        if pa is not None and pb is not None:
            bad = contracts_compatible(pa.contract, pb.contract)
            if bad:
                issues.append(SpecIssue("port_contract_mismatch", f"mate {m.name}: " + "; ".join(bad), [m.a, m.b]))

    order, reached, closing = spanning_tree(spec, grounds[0] if len(grounds) == 1 else None)
    if len(grounds) == 1:
        lost = [i for i in sorted(known) if i not in reached]
        if lost:
            issues.append(SpecIssue("unreachable", f"not connected to ground {grounds[0]!r}: {lost}", lost))
    for m in closing:
        loop = _tree_path(order, m.inst_a, m.inst_b)
        issues.append(SpecIssue("cycle", f"mate {m.name} closes a loop {' - '.join(loop)} - {loop[0]}; mate graphs must be trees",
                                [m.name, *loop]))

    for pair in [*spec.interference_allowed, *spec.clearances]:
        missing = [x for x in (pair.a, pair.b) if x not in known]
        if missing:
            issues.append(SpecIssue("unknown_pair", f"{type(pair).__name__} names unknown instances {missing}", missing))
    if spec.bom is not None:
        numbers = {part_number(spec, i.id) for i in spec.instances}
        extra = sorted(set(spec.bom) - numbers)
        if extra:
            issues.append(SpecIssue("unknown_pair", f"expected BOM lists part numbers no instance has: {extra}", extra, "warning"))
    return issues


def part_number(spec: AssemblySpec, iid: str) -> str:
    """BOM line key: the explicit part number, else inherited along the copy chain, else the root id.

    Mirrors are different parts (opposite hand), so a mirror without a part number gets its own line.
    """
    inst = spec.instance(iid)
    while inst.part_number is None and inst.copy_of:
        inst = spec.instance(inst.copy_of)
    return inst.part_number or inst.id
