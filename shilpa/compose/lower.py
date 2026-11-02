"""Lower an expanded composition to the existing ``AssemblySpec`` (spec 4.3 step 3). Deterministic, LLM-free.

* Each instance becomes an ``Instance``: native parts carry their pinned recipe (``RecipeRef``),
  catalog parts their generator and parameters (``GeneratorRef``); copies made by ``insert``
  are ``copy_of`` the first, so the geometry is built once and the BOM counts them on one line.
* Ports derived from features (hole entry/exit/axis, box faces) are declared on the root of each
  copy chain, so every copy has them. Catalog ports are used by their own names.
* Mates keep the IR order; ids are ``<step id>_m<n>``.

``spec_json`` is the canonical serialisation (sorted keys, fixed separators): replaying the same
IR against the same pinned versions gives the same bytes.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..contracts.assembly import AssemblySpec
from .expand import Program
from .features import port_for

ROUND = 9


def _num(v: float) -> float:
    r = round(float(v), ROUND)
    return 0.0 if r == 0 else r


def _port_dict(p) -> dict:
    return {"name": p.name, "origin": [_num(c) for c in p.origin], "z": [_num(c) for c in p.z], "x": [_num(c) for c in p.x],
            "label": p.label, "contract": dict(sorted(p.contract.items()))}


def lower(prog: Program, name: str | None = None) -> dict[str, Any]:
    """The AssemblySpec payload (a plain dict, validated) for an expanded program."""
    declared: dict[str, dict[str, dict]] = {}  # root instance -> port name -> port

    def root(iid: str) -> str:
        inst = prog.instances[iid]
        while inst.copy_of:
            inst = prog.instances[inst.copy_of]
        return inst.id

    mates = []
    for m in prog.mates:
        ends = []
        for iid, feat, seat in ((m.a, m.a_feat, m.a_seat), (m.b, m.b_feat, m.b_seat)):
            part = prog.part_of(iid)
            port = port_for(part, feat, seat)
            if not feat.port_name or seat not in (None, "port"):
                declared.setdefault(root(iid), {})[port.name] = _port_dict(port)
            ends.append(f"{iid}.{port.name}")
        mate: dict[str, Any] = {"id": m.id, "a": ends[0], "b": ends[1], "type": m.type}
        if m.align:
            mate["align"] = m.align
        if m.offset:
            mate["offset"] = _num(m.offset)
        if m.angle:
            mate["angle"] = _num(m.angle)
        if m.limits:
            mate["limits"] = [_num(m.limits[0]), _num(m.limits[1])]
        if m.intent:
            mate["intent"] = m.intent
        mates.append(mate)

    instances = []
    for inst in prog.instances.values():
        out: dict[str, Any] = {"id": inst.id}
        part = prog.part_of(inst.id)
        if inst.copy_of:
            out["copy_of"] = inst.copy_of
        else:
            ports = [declared[inst.id][k] for k in sorted(declared.get(inst.id, {}))]
            if part.source == "native":
                out["source"] = "recipe"
                out["ref"] = {"recipe": part.recipe, "ports": ports}
            else:
                out["source"] = "catalog"
                out["ref"] = {"generator": part.generator, "params": part.params, "ports": ports}
        if inst.grounded:
            out["grounded"] = True
        instances.append(out)

    spec: dict[str, Any] = {"schema_version": "1.0", "units": "mm", "instances": instances, "mates": mates}
    if name:
        spec["name"] = name[:200]
    press = [(m.a, m.b) for m in prog.mates if m.intent == "press_fit"]
    if press:
        spec["interference_allowed"] = [{"a": a, "b": b, "max_volume": 1.0, "reason": "press_fit"} for a, b in press]
    AssemblySpec.model_validate(spec)  # a lowering bug fails here, before any job exists
    return spec


def spec_json(spec: dict) -> str:
    return json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def spec_hash(spec: dict) -> str:
    return hashlib.sha256(spec_json(spec).encode("utf-8")).hexdigest()
