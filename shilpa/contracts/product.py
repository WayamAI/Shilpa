"""Product specification: requirements, skeleton, product tree and the derived assembly (roadmap layer 1, stage S4).

A ``ProductSpec`` is what a product template produces and what the rollback
router edits. It holds:

* ``requirements``: the request as free text plus the structured fields a
  template understands (use case, rider height or frame size, wheel size,
  materials, governing standards).
* ``template``: the product class template id that turns the skeleton into
  geometry (``bicycle.diamond_v1``). Open-ended decomposition is out of scope;
  a request outside the known templates is refused, not improvised.
* ``skeleton``: the master-layout parameters (layer 2). Every value carries
  provenance like ``ir.Param.source``: ``user`` (asked for), ``table`` (sizing
  table lookup), ``derived`` (computed from other skeleton values), ``assumed``
  / ``default`` (template choice), ``router`` (changed by a repair), ``llm``
  (proposed by the planner, never geometry).
* ``tree``: subsystems, then parts. Each part leaf is ``make``, ``buy`` or
  ``standard`` and names the assembly instances that realise it.
* ``assembly``: the derived ``AssemblySpec`` (layers 3 and 5).
* ``history``: every change the router made, with the check that triggered it.

``check_product`` runs the static checks that need no geometry: every tree
leaf maps to instances that exist, every instance sits under exactly one leaf,
and the governing standards agree with the generator parameters and declared
port contracts that encode them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .assembly import AssemblySpec, GeneratorRef, contracts_compatible

ParamSource = Literal["user", "table", "derived", "assumed", "default", "router", "llm"]
Procurement = Literal["make", "buy", "standard"]

_ID = r"^[a-z][a-z0-9_]{0,63}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SkeletonParam(_Strict):
    value: int | float | str | bool | list[int] | list[float] | None
    unit: str | None = None  # "mm", "deg", "cm", None for enums and counts
    source: ParamSource = "default"
    note: str | None = None


class Requirements(_Strict):
    text: str = ""
    product_class: str = "bicycle"
    use_case: Literal["road", "gravel"] | None = None
    rider_height_cm: float | None = Field(default=None, gt=100, lt=230)
    rider_inseam_cm: float | None = Field(default=None, gt=50, lt=120)
    frame_size: Literal["XS", "S", "M", "L", "XL", "XXL"] | None = None
    wheel_size: Literal["700c", "650b"] | None = None
    tyre_width_mm: float | None = Field(default=None, ge=20, le=60)
    materials: list[str] = Field(default_factory=list)
    # Governing interface standards by role: bb, headset, front_axle, rear_axle, seatpost, bar_clamp.
    standards: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class ProductNode(_Strict):
    id: str = Field(pattern=_ID)
    name: str = ""
    kind: Literal["product", "subsystem", "part"] = "part"
    procurement: Procurement | None = None  # parts only
    instances: list[str] = Field(default_factory=list)  # assembly instance ids realising a part
    standard: str | None = None  # the governing standard of a standard / buy part
    children: list[ProductNode] = Field(default_factory=list)

    @model_validator(mode="after")
    def _shape(self):
        if self.kind == "part":
            if self.children:
                raise ValueError(f"part {self.id} cannot have children")
            if self.procurement is None:
                raise ValueError(f"part {self.id} needs procurement make|buy|standard")
        elif self.instances or self.procurement:
            raise ValueError(f"{self.kind} {self.id}: only parts carry instances and procurement")
        return self

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    def leaves(self) -> list[ProductNode]:
        return [n for n in self.walk() if n.kind == "part"]


class ChangeRecord(_Strict):
    iteration: int
    param: str
    old: Any
    new: Any
    level: Literal["part", "design"]
    check: str  # the failing check that triggered the change
    reason: str
    responsible: str | None = None  # instance or skeleton group the router held responsible


class ProductSpec(_Strict):
    schema_version: Literal["1.0"] = "1.0"
    name: str
    template: str
    requirements: Requirements
    skeleton: dict[str, SkeletonParam]
    tree: ProductNode
    assembly: AssemblySpec
    targets: dict[str, float] = Field(default_factory=dict)  # product-check thresholds (mm, deg)
    derived: dict[str, float] = Field(default_factory=dict)  # skeleton outputs: wheelbase, trail, standover...
    history: list[ChangeRecord] = Field(default_factory=list)

    def value(self, key: str) -> Any:
        return self.skeleton[key].value


# ---------------------------------------------------------------- static checks


@dataclass
class ProductIssue:
    code: str  # leaf_without_instance | unknown_instance | orphan_instance | duplicate_instance
    #            | standard_mismatch | duplicate_node
    message: str
    where: list[str] = field(default_factory=list)
    severity: Literal["error", "warning"] = "error"


# Which generator parameter (or declared port contract key) encodes each standard role, and how a
# requirement string maps onto it. Values are compared with ``contracts_compatible``.
STANDARD_KEYS: dict[str, dict[str, Any]] = {
    "bb": {"params": ("shell_width", "bb_shell_width"), "parse": lambda s: {"standard": s[:3].upper(), "shell_width": int(s[3:])}},
    "front_axle": {"params": ("axle",), "parse": lambda s: {"axle": s}},
    "rear_axle": {"params": ("axle", "rear_axle"), "parse": lambda s: {"axle": s}},
    "seatpost": {"params": ("diameter", "seatpost_d"), "parse": lambda s: {"seatpost_d": float(s)}},
    "bar_clamp": {"params": ("clamp_d",), "parse": lambda s: {"clamp_d": float(s)}},
    "headset": {"params": ("shis", "headset"), "parse": lambda s: {"shis": s}},
}


def check_product(spec: ProductSpec, role_of: dict[str, list[str]] | None = None) -> list[ProductIssue]:
    """Static product checks. ``role_of`` maps a standard role to the instances that must honour it
    (the template knows which hub is the front one); without it only the tree is checked."""
    issues: list[ProductIssue] = []
    known = {i.id for i in spec.assembly.instances}
    ids = [n.id for n in spec.tree.walk()]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        issues.append(ProductIssue("duplicate_node", f"product tree node ids repeat: {dup}", dup))
    owner: dict[str, str] = {}
    for leaf in spec.tree.leaves():
        if not leaf.instances:
            issues.append(ProductIssue("leaf_without_instance", f"part {leaf.id} maps to no assembly instance", [leaf.id]))
        for iid in leaf.instances:
            if iid not in known:
                issues.append(ProductIssue("unknown_instance", f"part {leaf.id} names unknown instance {iid!r}", [leaf.id, iid]))
            elif iid in owner:
                issues.append(ProductIssue("duplicate_instance", f"instance {iid} sits under {owner[iid]} and {leaf.id}",
                                           [owner[iid], leaf.id]))
            else:
                owner[iid] = leaf.id
    orphans = sorted(known - set(owner))
    if orphans:
        issues.append(ProductIssue("orphan_instance", f"instances under no product-tree part: {orphans}", orphans))

    for role, iids in (role_of or {}).items():
        want = spec.requirements.standards.get(role)
        if want is None or role not in STANDARD_KEYS:
            continue
        rule = STANDARD_KEYS[role]
        try:
            expected = rule["parse"](want)
        except (ValueError, IndexError):
            issues.append(ProductIssue("standard_mismatch", f"standard {role}={want!r} is not understood", [role], "warning"))
            continue
        for iid in iids:
            if iid not in known:
                continue
            root = spec.assembly.root_of(iid)
            if not isinstance(root.ref, GeneratorRef):
                continue
            got = {}
            for key in rule["params"]:
                if key in root.ref.params:
                    got[next(iter(k for k in expected if k != "standard"), key)] = root.ref.params[key]
            for p in root.ref.ports:
                got.update({k: v for k, v in p.contract.items() if k in expected})
            bad = contracts_compatible(expected, got)
            if bad:
                issues.append(ProductIssue("standard_mismatch", f"{iid} does not honour {role}={want}: " + "; ".join(bad),
                                           [iid, role]))
    return issues
