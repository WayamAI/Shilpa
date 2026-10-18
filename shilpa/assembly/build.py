"""Build and place an assembly (roadmap layer 5, placement half).

Part sources turn an instance's reference into a ``BuiltPart`` (solid plus ports in
part-local coordinates). Sources are pluggable: ``register_source(kind, fn)`` with
``fn(ref) -> BuiltPart`` where ``ref`` is the instance's ``RecipeRef`` or
``GeneratorRef``. The ``recipe`` source ships here and runs the trusted build123d
adapter; catalog, weldment and sheet-metal modules register their own.

Placement is deterministic and closed-form, breadth-first from the ground with the
transform convention in ``contracts/assembly.py``. Like build123d's ``connect_to``
it places once and does not bind: relationships live in the spec, and the swept
check simply re-places with other joint values.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

import build123d as bd
import numpy as np
from OCP.gp import gp_Trsf

from ..contracts.assembly import AssemblySpec, GeneratorRef, Instance, Mate, RecipeRef, SpecIssue, check_spec, spanning_tree
from ..contracts.errors import ErrorCode, ErrorInfo, ShilpaError
from ..contracts.ports import BuiltPart, Port

SourceFn = Callable[[RecipeRef | GeneratorRef], BuiltPart]
_SOURCES: dict[str, SourceFn] = {}


def register_source(kind: str, fn: SourceFn, *, replace: bool = False) -> None:
    """Register the builder for one ``Instance.source`` kind."""
    if kind in _SOURCES and not replace:
        raise ValueError(f"a part source for {kind!r} is already registered")
    _SOURCES[kind] = fn


def sources() -> set[str]:
    return set(_SOURCES)


def _recipe_source(ref: RecipeRef) -> BuiltPart:
    from ..adapters import build123d_adapter as adapter

    res = adapter.build(ref.recipe)  # compile errors raise ShilpaError
    if not res.ok:
        raise ShilpaError(res.error.info.code, res.error.info.message, feature_id=res.error.info.feature_id)
    return BuiltPart(
        name=ref.recipe.name or "part",
        solid=res.shape,
        ports={p.name: p for p in ref.ports},
        source="recipe",
        meta={"volume": res.shape.volume, "features": len(res.compiled.features)},
    )


register_source("recipe", _recipe_source)


# ---------------------------------------------------------------- frames


def port_matrix(p: Port) -> np.ndarray:
    """Port-local to part-local: columns x, y = z cross x, z, origin."""
    z, x = np.array(p.z, float), np.array(p.x, float)
    T = np.eye(4)
    T[:3, 0], T[:3, 1], T[:3, 2], T[:3, 3] = x, np.cross(z, x), z, p.origin
    return T


def _rot_z(deg: float) -> np.ndarray:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    T = np.eye(4)
    T[:2, :2] = [[c, -s], [s, c]]
    return T


FLIP = np.diag([1.0, -1.0, -1.0, 1.0])  # 180 degrees about x: z opposed, x kept


def mate_matrix(m: Mate, angle: float | None = None, offset: float | None = None) -> np.ndarray:
    """``M = Translate(xy, offset) @ RotZ(angle) @ F`` from port a's frame to port b's frame."""
    angle = m.angle if angle is None else angle
    offset = m.offset if offset is None else offset
    if m.type == "screw":
        offset += (angle - m.angle) / 360.0 * m.pitch  # the assembled position is the spec's (angle, offset)
    T = np.eye(4)
    T[:3, 3] = (m.xy[0], m.xy[1], offset)
    T = T @ _rot_z(angle)
    return T @ FLIP if m.opposed else T


def to_location(T: np.ndarray) -> bd.Location:
    t = gp_Trsf()
    t.SetValues(*(float(v) for v in T[:3, :].reshape(-1)))
    return bd.Location(t)


def _mirror_part(part: BuiltPart, plane: str) -> BuiltPart:
    axis = {"YZ": 0, "XZ": 1, "XY": 2}[plane]
    R = np.ones(3)
    R[axis] = -1

    def flip(v):
        return tuple(float(c) for c in np.array(v) * R)

    ports = {n: p.model_copy(update={"origin": flip(p.origin), "z": flip(p.z), "x": flip(p.x)}) for n, p in part.ports.items()}
    solid = part.solid.mirror(getattr(bd.Plane, plane))
    return BuiltPart(part.name + "_mirror", solid, ports, part.source, {**part.meta, "mirrored": plane})


# ---------------------------------------------------------------- build


@dataclass
class AssemblyBuild:
    spec: AssemblySpec
    parts: dict[str, BuiltPart]  # instance -> part-local geometry and ports
    errors: dict[str, ErrorInfo]  # instance -> why its part failed to build
    issues: list[SpecIssue]
    order: list[tuple[Mate, bool]]  # placement tree, breadth-first; forward = a placed before b
    ground: str | None
    matrices: dict[str, np.ndarray] = field(default_factory=dict)  # part-local -> world, placed instances only
    placed: dict[str, bd.Shape] = field(default_factory=dict)  # world-space solids, labelled
    compound: bd.Compound | None = None

    @property
    def ok(self) -> bool:
        return not self.errors and not any(i.severity == "error" for i in self.issues)

    @property
    def unplaced(self) -> list[str]:
        return [i.id for i in self.spec.instances if i.id not in self.matrices]

    def placement_table(self) -> dict[str, list[list[float]]]:
        return {k: [[round(float(v), 9) for v in row] for row in T] for k, T in self.matrices.items()}

    def moving_side(self, mate: Mate) -> set[str]:
        """Instances that move when this tree mate's joint moves (the side away from the ground)."""
        forward = next((f for m, f in self.order if m is mate), None)
        if forward is None:
            return set()
        child = mate.inst_b if forward else mate.inst_a
        kids: dict[str, list[str]] = {}
        for m, f in self.order:
            if m is mate:
                continue
            kids.setdefault(m.inst_a if f else m.inst_b, []).append(m.inst_b if f else m.inst_a)
        out, stack = set(), [child]
        while stack:
            cur = stack.pop()
            out.add(cur)
            stack += kids.get(cur, [])
        return out

    def pose(self, overrides: dict[str, dict[str, float]] | None = None) -> dict[str, np.ndarray]:
        """Placement matrices with some joints moved: ``{mate_name: {"angle": deg, "offset": mm}}``."""
        return place(self.parts, self.order, self.ground, overrides)

    def world_solid(self, iid: str, T: np.ndarray | None = None) -> bd.Shape:
        T = self.matrices[iid] if T is None else T
        return self.parts[iid].solid.moved(to_location(T))


def place(parts: dict[str, BuiltPart], order: list[tuple[Mate, bool]], ground: str | None,
          overrides: dict[str, dict[str, float]] | None = None) -> dict[str, np.ndarray]:
    """Walk the tree from the ground composing ``T_b = T_a @ P_a @ M @ inv(P_b)`` (or its inverse)."""
    overrides = overrides or {}
    if ground is None or ground not in parts:
        return {}
    T = {ground: np.eye(4)}
    for m, forward in order:
        if m.inst_a not in parts or m.inst_b not in parts:
            continue
        o = overrides.get(m.name, {})
        M = mate_matrix(m, o.get("angle"), o.get("offset"))
        Pa = port_matrix(parts[m.inst_a].port(m.port_a))
        Pb = port_matrix(parts[m.inst_b].port(m.port_b))
        if forward and m.inst_a in T:
            T[m.inst_b] = T[m.inst_a] @ Pa @ M @ np.linalg.inv(Pb)
        elif not forward and m.inst_b in T:
            T[m.inst_a] = T[m.inst_b] @ Pb @ np.linalg.inv(M) @ np.linalg.inv(Pa)
    return T


def _resolve_part(spec: AssemblySpec, inst: Instance, cache: dict[str, BuiltPart]) -> BuiltPart:
    if inst.id in cache:
        return cache[inst.id]
    if inst.copy_of:
        part = _resolve_part(spec, spec.instance(inst.copy_of), cache)
    elif inst.mirror_of:
        part = _mirror_part(_resolve_part(spec, spec.instance(inst.mirror_of.instance), cache), inst.mirror_of.plane)
    else:
        fn = _SOURCES.get(inst.source)
        if fn is None:
            raise ShilpaError(ErrorCode.UNSUPPORTED_OPERATION, f"no part source registered for {inst.source!r}; have {sorted(_SOURCES)}")
        part = fn(inst.ref)
        # Declared ports win over the source's own (they are the spec's hard constraints).
        part.ports = {**part.ports, **{p.name: p for p in inst.ref.ports}}
    cache[inst.id] = part
    return part


def build_assembly(spec: AssemblySpec | dict) -> AssemblyBuild:
    """Build every instance, re-run the static checks against the real ports, and place what can be placed.

    Never raises for part or spec problems: they come back as ``errors`` and ``issues`` so the
    validator and a rollback router can see all of them at once.
    """
    spec = spec if isinstance(spec, AssemblySpec) else AssemblySpec.model_validate(spec)
    parts: dict[str, BuiltPart] = {}
    errors: dict[str, ErrorInfo] = {}
    cache: dict[str, BuiltPart] = {}
    for inst in spec.instances:
        try:
            parts[inst.id] = _resolve_part(spec, inst, cache)
        except ShilpaError as exc:
            errors[inst.id] = exc.info
        except Exception as exc:  # a source's kernel failure
            errors[inst.id] = ErrorInfo(code=ErrorCode.KERNEL_FAILURE, message=f"{inst.source} part failed: {exc}")

    ports = {iid: (p.ports if iid in parts else None) for iid, p in ((i.id, parts.get(i.id)) for i in spec.instances)}
    issues = check_spec(spec, ports)
    grounds = [i.id for i in spec.instances if i.grounded]
    ground = grounds[0] if grounds else None  # with several grounds, place from the first and report

    # Only mates whose two ports resolve can place anything.
    usable = [m for m in spec.mates
              if m.inst_a in parts and m.inst_b in parts and m.port_a in parts[m.inst_a].ports and m.port_b in parts[m.inst_b].ports]
    order, _, _ = spanning_tree(spec, ground, usable)
    out = AssemblyBuild(spec, parts, errors, issues, order, ground)
    out.matrices = place(parts, order, ground)

    children = []
    for inst in spec.instances:
        if inst.id not in out.matrices:
            continue
        shape = out.world_solid(inst.id)
        shape.label = inst.id
        if inst.color:
            shape.color = bd.Color(inst.color)
        out.placed[inst.id] = shape
        children.append(shape)
    out.compound = bd.Compound(children=children, label=spec.name or "assembly")
    return out
