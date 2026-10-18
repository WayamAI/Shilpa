"""Sheet-metal sub-IR (roadmap stage S2).

A sheet-metal part is a tree of flat *walls* joined by cylindrical *bends*. The
base flange is the root; every edge flange and hem hangs off a named edge of the
base or of an earlier flange. Edges are named by construction, never selected
geometrically:

- base: ``base.edge_<i>`` runs from outline vertex ``i`` to ``i + 1`` (outline is
  counter-clockwise seen from +Z). A rectangular base also answers to
  ``base.south`` / ``base.east`` / ``base.north`` / ``base.west`` (= edge 0..3).
- flange or hem ``<id>``: ``<id>.far`` (opposite the bend), ``<id>.side_a`` and
  ``<id>.side_b`` (the sides nearer the start / end vertex of the parent edge).

Conventions follow ``ir.py``: millimetres, degrees, Z up. The base lies in XY
with material from z = 0 to z = thickness; "up" bends toward +Z (toward the
wall's top face, for a flange its inner face after an up bend). The bend allowance
is always ``BA = angle * (R + K * T)`` with the angle in radians, so flat-pattern
sizes are closed-form.
"""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

WallId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")]
EdgeRef = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,47}\.[a-z][a-z0-9_]{0,31}$")]
Pt2 = tuple[float, float]

# Densities in kg/m^3. Used for mass only; unknown materials get no mass.
DENSITY = {
    "steel": 7850.0,
    "mild_steel": 7850.0,
    "galvanized_steel": 7850.0,
    "stainless": 8000.0,
    "stainless_steel": 8000.0,
    "aluminium": 2700.0,
    "aluminum": 2700.0,
    "copper": 8960.0,
    "brass": 8500.0,
}

K_MIN, K_MAX = 0.2, 0.5


def din6935_k(radius: float, thickness: float) -> float:
    """K-factor from the DIN 6935 correction factor, clamped to [0.2, 0.5].

    DIN 6935 gives the neutral-fibre position as ``k * T / 2`` with
    ``k = 0.65 + 0.5 * log10(R / T)`` for ``R / T < 5`` and ``k = 1`` beyond, so
    ``K = k / 2``. The log blows up for very tight radii (hems), hence the clamp.
    """
    if thickness <= 0:
        raise ValueError("thickness must be positive")
    rt = radius / thickness
    if rt >= 5 or rt <= 0:
        return K_MAX if rt >= 5 else K_MIN
    return min(K_MAX, max(K_MIN, (0.65 + 0.5 * math.log10(rt)) / 2))


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KFactorRow(_Strict):
    """One row of a shop K-factor table; the first matching row wins."""

    material: str | None = None  # None matches any material
    t_min: float = 0.0
    t_max: float = math.inf
    rt_min: float = 0.0  # inner radius / thickness
    rt_max: float = math.inf
    k: float = Field(gt=0, le=1)


class RectOutline(_Strict):
    """Rectangle centred on the origin; vertices CCW from (-w/2, -d/2)."""

    kind: Literal["rect"] = "rect"
    width: float = Field(gt=0)  # along X
    depth: float = Field(gt=0)  # along Y


class PolyOutline(_Strict):
    kind: Literal["polygon"] = "polygon"
    points: list[Pt2] = Field(min_length=3, max_length=64)

    @model_validator(mode="after")
    def _ccw(self):
        p = self.points
        area2 = sum(p[i][0] * p[(i + 1) % len(p)][1] - p[(i + 1) % len(p)][0] * p[i][1] for i in range(len(p)))
        if area2 <= 0:
            raise ValueError("base outline must be counter-clockwise with positive area")
        return self


class EdgeFlange(_Strict):
    """A wall bent off a named edge.

    ``length_type`` says what ``length`` measures, along the flange:
    ``outer`` from the outer virtual sharp (outer mould line) to the far edge,
    ``inner`` from the inner virtual sharp, ``flat`` the straight wall only
    (tangent line to far edge). ``position`` places the bend: ``outside`` starts
    the bend at the edge (the parent keeps its size), ``flush`` puts the outer
    virtual sharp on the edge (the parent is trimmed by the setback
    ``(R + T) * tan(angle / 2)``, so outer dimensions equal the given outline).
    ``offset_start`` / ``offset_end`` shrink (positive, with bend reliefs) or
    extend (negative) the flange at the start / end vertex of the edge.
    """

    id: WallId
    edge: EdgeRef
    length: float = Field(gt=0)
    angle: float = Field(default=90.0, gt=0, lt=180)
    direction: Literal["up", "down"] = "up"
    length_type: Literal["outer", "inner", "flat"] = "outer"
    position: Literal["outside", "flush"] = "outside"
    offset_start: float = 0.0
    offset_end: float = 0.0
    bend_radius: float | None = Field(default=None, ge=0)  # None = part default


class Hem(_Strict):
    """A 180 degree fold back over the parent. ``length`` is the flat return.

    A closed hem is modelled with a small non-zero gap (default 0.1 T) so the
    solid stays manifold; an open hem defaults to a gap of one thickness. The
    inner bend radius is ``gap / 2``.
    """

    id: WallId
    edge: EdgeRef
    length: float = Field(gt=0)
    kind: Literal["open", "closed"] = "open"
    gap: float | None = Field(default=None, gt=0)
    direction: Literal["up", "down"] = "up"
    offset_start: float = 0.0
    offset_end: float = 0.0


class Cutout(_Strict):
    """A through cut on one flat wall, in that wall's flat coordinates.

    Base: the outline's XY. Flange or hem: ``u`` along the bend line (origin at
    the midpoint of the flange's bend edge, positive toward ``side_a``), ``v``
    away from the bend, measured from the bend tangent line.
    """

    id: WallId
    face: WallId = "base"
    shape: Literal["circle", "rect", "slot", "polygon"] = "circle"
    center: Pt2 = (0.0, 0.0)
    diameter: float | None = Field(default=None, gt=0)  # circle; slot width
    width: float | None = Field(default=None, gt=0)  # rect
    height: float | None = Field(default=None, gt=0)  # rect
    length: float | None = Field(default=None, gt=0)  # slot centre-to-centre
    angle: float = 0.0  # rect / slot rotation, degrees
    points: list[Pt2] | None = None  # polygon, relative to center
    mounting: bool = True  # circular holes become ports

    @model_validator(mode="after")
    def _fields(self):
        need = {"circle": ("diameter",), "rect": ("width", "height"), "slot": ("diameter", "length"), "polygon": ("points",)}
        missing = [f for f in need[self.shape] if getattr(self, f) is None]
        if missing:
            raise ValueError(f"cutout {self.id}: {self.shape} needs {', '.join(missing)}")
        return self


class BendRelief(_Strict):
    """Relief cut into the parent at each end of a partial-width flange.

    Auto sizes: width = T, depth = R + T beyond the bend tangent line.
    """

    kind: Literal["rect", "obround"] = "rect"
    width: float | None = Field(default=None, gt=0)
    depth: float | None = Field(default=None, gt=0)


class CornerRelief(_Strict):
    """Relief where two full-width flanges meet at a corner of the same wall.

    Each flange is inset by ``size`` at that corner and the wall loses a square
    (rhombus on a non-square corner) or a circle of that size at the vertex.
    Auto size: T.
    """

    kind: Literal["none", "square", "circle"] = "none"
    size: float | None = Field(default=None, gt=0)


class SheetMetalSpec(_Strict):
    name: str = "sheet_metal_part"
    material: str = "steel"
    density: float | None = Field(default=None, gt=0)  # kg/m^3; None = table lookup
    thickness: float = Field(gt=0)
    bend_radius: float = Field(ge=0)  # default inner bend radius
    k_factor: float | None = Field(default=None, gt=0, le=1)  # fixed K overrides the table
    k_table: list[KFactorRow] = Field(default_factory=list)
    base: RectOutline | PolyOutline
    flanges: list[EdgeFlange] = Field(default_factory=list, max_length=64)
    hems: list[Hem] = Field(default_factory=list, max_length=32)
    cutouts: list[Cutout] = Field(default_factory=list, max_length=200)
    relief: BendRelief = Field(default_factory=BendRelief)
    corner_relief: CornerRelief = Field(default_factory=CornerRelief)

    @model_validator(mode="after")
    def _ids(self):
        ids = [f.id for f in self.flanges] + [h.id for h in self.hems]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup or "base" in ids:
            raise ValueError(f"flange/hem ids must be unique and not 'base': {sorted(dup) or ['base']}")
        cut_ids = [c.id for c in self.cutouts]
        if len(set(cut_ids)) != len(cut_ids):
            raise ValueError("cutout ids must be unique")
        return self

    def k_for(self, radius: float) -> float:
        """K-factor for one bend: fixed value, else first table match, else DIN 6935."""
        if self.k_factor is not None:
            return self.k_factor
        rt = radius / self.thickness
        for row in self.k_table:
            if row.material not in (None, self.material):
                continue
            if row.t_min <= self.thickness <= row.t_max and row.rt_min <= rt <= row.rt_max:
                return row.k
        return din6935_k(radius, self.thickness)

    def density_kg_m3(self) -> float | None:
        return self.density if self.density is not None else DENSITY.get(self.material.lower())


def bend_allowance(angle_deg: float, radius: float, k: float, thickness: float) -> float:
    """Neutral-fibre arc length: BA = angle * (R + K * T)."""
    return math.radians(angle_deg) * (radius + k * thickness)
