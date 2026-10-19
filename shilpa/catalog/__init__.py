"""Standard-parts catalog (roadmap layer 4): buy parts that never go through an LLM.

``resolve(generator, params)`` validates ``params`` against the generator's
pydantic model and returns a ``BuiltPart`` (source ``"catalog"``) whose ports
carry dimension contracts. ``list_generators()`` gives every generator's name,
standard and JSON parameter schema, which is what a planner is shown.

Port conventions used across the catalog (``ports.py`` fixes only the frame):

* Seat / face ports: ``z`` is the outward normal of the contact face, so two
  faces that mate have opposed ``z``.
* Axis ports (bores, spindles, axles, steerers): ``z`` runs along the part
  axis; coaxial mates align ``z``.
* Bicycle parts with a lateral axis (BB, hubs, cranks, bars) put local +Z on
  the rider's left (non-drive) side, matching the frame's +Y.

Meta always has ``standard``, ``size`` and ``designation``; with a ``material``
param it also has ``mass_g`` and ``mass_basis`` (``"geometry"`` for true
solids, ``"envelope"`` for interface envelopes that overstate mass, or
``"catalog"`` for published masses).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from ..contracts.errors import ErrorCode, ShilpaError
from ..contracts.ports import BuiltPart
from .materials import mass_g


@dataclass(frozen=True)
class Generator:
    name: str
    params: type[BaseModel]
    build: Callable[[Any], BuiltPart]
    summary: str
    standard: str
    mass_basis: str = "geometry"
    listed: bool = True  # False: still resolvable (templates, saved specs) but not offered when browsing


_REGISTRY: dict[str, Generator] = {}


def generator(name: str, params: type[BaseModel], summary: str, standard: str, mass_basis: str = "geometry",
              listed: bool = True):
    """Decorator registering a catalog generator."""

    def deco(fn: Callable[[Any], BuiltPart]):
        if name in _REGISTRY:
            raise ValueError(f"catalog generator {name!r} registered twice")
        _REGISTRY[name] = Generator(name, params, fn, summary, standard, mass_basis, listed)
        return fn

    return deco


def list_generators(listed_only: bool = False) -> list[dict[str, Any]]:
    return [
        {"name": g.name, "summary": g.summary, "standard": g.standard, "params": g.params.model_json_schema(),
         "listed": g.listed}
        for g in sorted(_REGISTRY.values(), key=lambda g: g.name) if g.listed or not listed_only
    ]


def resolve(generator: str, params: dict[str, Any] | None = None) -> BuiltPart:
    try:
        gen = _REGISTRY[generator]
    except KeyError:
        raise ShilpaError(ErrorCode.UNSUPPORTED_OPERATION,
                          f"unknown catalog generator {generator!r}; known: {sorted(_REGISTRY)}") from None
    try:
        p = gen.params.model_validate(params or {})
    except ValidationError as exc:
        raise ShilpaError(ErrorCode.INVALID_PARAMETER, f"{generator}: {exc.errors()[0]['msg']}",
                          feature_id=generator, details={"errors": exc.errors(include_url=False, include_context=False)}) from None
    part = gen.build(p)
    if not part.solid.is_valid:
        raise ShilpaError(ErrorCode.VALIDATION_FAILED, f"{generator} produced an invalid solid", feature_id=generator)
    part.meta.setdefault("generator", generator)
    part.meta.setdefault("params", p.model_dump(mode="json"))
    part.meta["volume_mm3"] = round(part.solid.volume, 3)
    material = getattr(p, "material", None)
    if material and "mass_g" not in part.meta:
        part.meta["mass_g"] = mass_g(part.solid.volume, material)
        part.meta["mass_basis"] = gen.mass_basis
    return part


# Registration side effects.
from . import bearings, bicycle, fasteners, gears, mechanical, vslot, warehouse  # noqa: E402,F401
