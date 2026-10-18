"""Shared interface types for multi-part products (roadmap layer 3).

A *port* is a named local frame on a part: an origin, a primary axis (``z``,
the mating direction or rotation axis) and a reference axis (``x``) that fixes
rotation about it, plus a semantic label and a dimension contract such as
``{"standard": "BSA", "shell_width": 68}``. Ports are what mates connect, so
every part source (typed recipe, catalog standard part, tube weldment, sheet
metal) must hand back a ``BuiltPart``: the solid plus its ports, both in the
part's own coordinates.

Conventions follow ``ir.py``: millimetres, Z up. Port axes are unit vectors;
``x`` must be perpendicular to ``z``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PortName = str
Vec3 = tuple[float, float, float]

PartSource = Literal["recipe", "catalog", "weldment", "sheet_metal"]


class Port(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: PortName = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    origin: Vec3 = (0.0, 0.0, 0.0)
    z: Vec3 = (0.0, 0.0, 1.0)
    x: Vec3 = (1.0, 0.0, 0.0)
    label: str = ""
    contract: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _orthonormal(self):
        for axis in (self.z, self.x):
            if abs(math.sqrt(sum(c * c for c in axis)) - 1.0) > 1e-6:
                raise ValueError(f"port {self.name}: axes must be unit vectors")
        if abs(sum(a * b for a, b in zip(self.z, self.x))) > 1e-6:
            raise ValueError(f"port {self.name}: x must be perpendicular to z")
        return self


@dataclass
class BuiltPart:
    """A part's geometry and interfaces, in part-local coordinates."""

    name: str
    solid: Any  # build123d Solid/Compound; Any keeps this module kernel-free
    ports: dict[PortName, Port]
    source: PartSource
    meta: dict[str, Any] = field(default_factory=dict)  # standard, size, part numbers, provenance

    def port(self, name: PortName) -> Port:
        try:
            return self.ports[name]
        except KeyError:
            raise KeyError(f"part {self.name!r} has no port {name!r}; has {sorted(self.ports)}") from None
