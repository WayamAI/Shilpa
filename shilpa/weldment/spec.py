"""Tube/weldment sub-IR (roadmap layer 4, stage S2).

A weldment is a skeleton of named nodes plus straight members between them.
Each member is a tube swept along the line ``start_node -> end_node``; members
that meet are coped (fish-mouthed) so the lower-ranked tube ends on the outer
surface of the higher-ranked one, then everything is fused into one welded
solid. *Shells* are short sleeves (head tube, bottom-bracket shell, axle bosses)
that other tubes butt against; they outrank every member by default.

Node coordinates are numbers or restricted expressions over ``params`` (the
same whitelist language as ``ir.py`` refs, see ``expr.py``), so a frame stays
editable by name. Millimetres, Z up, like the rest of Shilpa.
"""

from __future__ import annotations

import math
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag, model_validator

from ..contracts import expr
from ..contracts.errors import ErrorCode, ShilpaError

Id = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
Coord = float | Annotated[str, Field(min_length=1, max_length=200)]
Vec3 = tuple[float, float, float]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoundTube(_Strict):
    """Round tube. ``od_start``/``od_end`` give a straight taper (constant wall)."""

    kind: Literal["round"] = "round"
    od: float = Field(gt=0)
    wall: float = Field(gt=0)
    od_start: float | None = Field(default=None, gt=0)
    od_end: float | None = Field(default=None, gt=0)

    @property
    def ods(self) -> tuple[float, float]:
        return (self.od_start or self.od, self.od_end or self.od)

    @model_validator(mode="after")
    def _wall_fits(self):
        if self.wall * 2 >= min(self.ods):
            raise ValueError(f"wall {self.wall} leaves no bore in a {min(self.ods)} mm tube")
        return self

    def label(self) -> str:
        a, b = self.ods
        od = f"{a:g}" if a == b else f"{a:g}-{b:g}"
        return f"round {od} x {self.wall:g}"


class RectTube(_Strict):
    """Rectangular hollow section. ``height`` runs along ``up`` projected square to the member axis."""

    kind: Literal["rect"] = "rect"
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    wall: float = Field(gt=0)
    up: Vec3 = (0.0, 0.0, 1.0)

    @model_validator(mode="after")
    def _wall_fits(self):
        if self.wall * 2 >= min(self.width, self.height):
            raise ValueError("rect tube wall leaves no bore")
        return self

    def label(self) -> str:
        return f"rect {self.width:g} x {self.height:g} x {self.wall:g}"


def _profile_kind(v: Any) -> str:
    kind = v.get("kind", "round") if isinstance(v, dict) else getattr(v, "kind", "round")
    return kind


# ``kind`` defaults to round so the common case reads {"od": 28.6, "wall": 0.9}.
Profile = Annotated[Union[Annotated[RoundTube, Tag("round")], Annotated[RectTube, Tag("rect")]], Discriminator(_profile_kind)]


class Member(_Strict):
    id: Id
    start_node: Id
    end_node: Id
    profile: Profile
    material: str = "steel"
    # Higher priority is never cut by lower; ties go to the member declared first.
    priority: int = 0


class Shell(_Strict):
    """A cylindrical sleeve, given either by two nodes or by a centre node, axis and length."""

    id: Id
    od: float = Field(gt=0)
    bore: float = Field(gt=0)
    start_node: Id | None = None
    end_node: Id | None = None
    node: Id | None = None
    axis: Vec3 | None = None
    length: float | None = Field(default=None, gt=0)
    material: str = "steel"
    priority: int = 100

    @model_validator(mode="after")
    def _placement(self):
        by_nodes = self.start_node is not None and self.end_node is not None
        by_axis = self.node is not None and self.axis is not None and self.length is not None
        if by_nodes == by_axis:
            raise ValueError(f"shell {self.id}: give start_node+end_node, or node+axis+length")
        if self.bore >= self.od:
            raise ValueError(f"shell {self.id}: bore must be smaller than od")
        return self


class PortSpec(_Strict):
    """A port at a node. ``z`` is a vector, or ``z_nodes`` = (a, b) means the direction a -> b."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    node: Id
    z: Vec3 | None = None
    z_nodes: tuple[Id, Id] | None = None
    x: Vec3 | None = None
    label: str = ""
    contract: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _one_axis(self):
        if (self.z is None) == (self.z_nodes is None):
            raise ValueError(f"port {self.name}: give exactly one of z or z_nodes")
        return self


class WeldmentSpec(_Strict):
    name: str = "weldment"
    params: dict[str, float] = Field(default_factory=dict)
    nodes: dict[Id, tuple[Coord, Coord, Coord]]
    members: list[Member] = Field(min_length=1)
    shells: list[Shell] = Field(default_factory=list)
    ports: list[PortSpec] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _references(self):
        ids = [m.id for m in self.members] + [s.id for s in self.shells]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            raise ValueError(f"duplicate member/shell ids: {sorted(dup)}")
        names = [p.name for p in self.ports]
        if len(set(names)) != len(names):
            raise ValueError("duplicate port names")
        used = [(m.id, n) for m in self.members for n in (m.start_node, m.end_node)]
        used += [(s.id, n) for s in self.shells for n in (s.start_node, s.end_node, s.node) if n]
        used += [(p.name, n) for p in self.ports for n in (p.node, *(p.z_nodes or ()))]
        for owner, n in used:
            if n not in self.nodes:
                raise ValueError(f"{owner}: unknown node {n!r}")
        for m in self.members:
            if m.start_node == m.end_node:
                raise ValueError(f"member {m.id}: start and end node are the same")
        return self

    def resolve_nodes(self) -> dict[str, Vec3]:
        """Evaluate every node coordinate to floats."""
        scope = {k: expr.Quantity(float(v), "length") for k, v in self.params.items()}
        out: dict[str, Vec3] = {}
        for name, coords in self.nodes.items():
            vals = []
            for c in coords:
                v = float(c) if not isinstance(c, str) else expr.evaluate(c, scope).value
                if not math.isfinite(v):
                    raise ShilpaError(ErrorCode.INVALID_PARAMETER, f"node {name}: non-finite coordinate", field=name)
                vals.append(v)
            out[name] = (vals[0], vals[1], vals[2])
        return out
