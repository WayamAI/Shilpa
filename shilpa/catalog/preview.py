"""Catalog browsing for the studio: families, one-part previews and STEP downloads.

``browse()`` lists every generator with its family, summary, standard and JSON
parameter schema. ``preview(generator, params)`` builds one part and returns its
mesh (the same base64 float32/uint32 encoding the assembly viewer reads), its
ports with their inferred kind and whether each sits on the geometry, and the
part's meta (designation, standard, mass). ``step(generator, params)`` exports
the part as STEP. Builds are cached by (generator, params): catalog parts are
deterministic and a preview is rebuilt as the user edits a single field.
"""

from __future__ import annotations

import json
import tempfile
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import list_generators, resolve
from .materials import DENSITY_G_CM3

FAMILIES = [  # (name prefix, family title), first match wins
    ("screw.", "Screws"),
    ("nut.", "Nuts"),
    ("washer.", "Washers"),
    ("bearing.", "Bearings"),
    ("deep_groove", "Bearings"),
    ("seal.", "Seals, circlips and keys"),
    ("ring.", "Seals, circlips and keys"),
    ("key.", "Seals, circlips and keys"),
    ("gear.", "Gears"),
    ("vslot.", "V-slot extrusion"),
    ("iso", "Template fastener set (M3-M12)"),
    ("bike.", "Bicycle parts"),
]


def family(name: str) -> str:
    return next((title for prefix, title in FAMILIES if name.startswith(prefix)), "Other")


def browse() -> dict:
    order = {title: k for k, (_, title) in enumerate(FAMILIES)}
    gens = [{**g, "family": family(g["name"])} for g in list_generators()]
    gens.sort(key=lambda g: (order.get(g["family"], len(order)), g["name"]))
    return {"families": list(dict.fromkeys(t for _, t in FAMILIES)), "generators": gens, "materials": sorted(DENSITY_G_CM3)}


def _key(params: dict | None) -> str:
    return json.dumps(params or {}, sort_keys=True, separators=(",", ":"))


@lru_cache(maxsize=64)
def _built(generator: str, key: str):
    return resolve(generator, json.loads(key))


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def preview(generator: str, params: dict | None = None) -> dict:
    from ..validators.ports import check_ports, port_kind
    from ..workers.kinds import mesh_of

    t0 = time.perf_counter()
    part = _built(generator, _key(params))
    build_ms = (time.perf_counter() - t0) * 1000
    t1 = time.perf_counter()
    mesh = mesh_of(part.solid)
    checks = {c.name: c for c in check_ports(part)}
    ports = []
    for p in part.ports.values():
        kind = port_kind(p)
        c = checks.get(f"port_{p.name}_{kind}")
        ports.append({"name": p.name, "label": p.label, "kind": kind, "origin": list(p.origin), "z": list(p.z),
                      "x": list(p.x), "contract": _jsonable(p.contract), "on_geometry": bool(c and c.passed),
                      "note": c.note if c else None})
    bb = part.solid.bounding_box()
    meta = _jsonable({k: v for k, v in part.meta.items() if k != "params"})
    return {"generator": generator, "family": family(generator), "name": part.name,
            "params": _jsonable(part.meta.get("params")), "meta": meta, "ports": ports, "mesh": mesh,
            "size": [round(bb.size.X, 4), round(bb.size.Y, 4), round(bb.size.Z, 4)],
            "volume_mm3": round(part.solid.volume, 3),
            "timings_ms": {"build": round(build_ms, 1), "mesh_and_ports": round((time.perf_counter() - t1) * 1000, 1)}}


def step(generator: str, params: dict | None = None) -> tuple[bytes, str]:
    """STEP bytes and a file name for one catalog part."""
    import build123d as bd

    part = _built(generator, _key(params))
    name = str(part.meta.get("designation") or part.name)
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name).strip("_") or "part"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{safe}.step"
        bd.export_step(part.solid, str(path))
        return path.read_bytes(), path.name
