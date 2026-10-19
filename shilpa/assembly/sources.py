"""Part sources beyond typed recipes: catalog, weldment and sheet metal (roadmap layer 4).

Each source turns an instance's ``GeneratorRef`` into a ``BuiltPart``:

* ``catalog``: ``generator`` is a catalog name (``bike.hub``, ``iso4762``...),
  ``params`` its pydantic parameters; resolved by ``shilpa.catalog.resolve``.
* ``weldment``: ``generator`` is a weldment template (``bike.frame`` with
  ``FrameGeometry`` params, ``bike.fork`` with ``ForkGeometry`` params) or
  ``weldment`` with ``params = {"spec": <WeldmentSpec payload>}``. Templates
  build strictly: a frame whose coping fails is a part error, not a part. The
  cut list and the template's derived geometry land in ``meta``.
* ``sheet_metal``: ``params`` is a ``SheetMetalSpec`` payload (or
  ``{"spec": payload}``); ``generator`` is free text naming the part.

These are built-in *fallbacks*: ``build.py`` imports this module the first time
an instance needs one of the three kinds and nothing was registered for it, so
the heavy kernels load only on use and ``register_source`` can still install
a different builder for any kind. Built parts are memoised by
``(kind, generator, params)``: a router loop that changes one skeleton value
rebuilds only the parts whose parameters changed. The cache hands out shallow
copies because ``build_assembly`` overwrites a part's ``ports`` with the
instance's declared ones.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from ..contracts.assembly import GeneratorRef
from ..contracts.errors import ErrorCode, ShilpaError
from ..contracts.ports import BuiltPart

CACHE_SIZE = 64
_cache: OrderedDict[str, BuiltPart] = OrderedDict()
_stats = {"hits": 0, "misses": 0}


def _key(kind: str, ref: GeneratorRef) -> str:
    return json.dumps([kind, ref.generator, ref.params], sort_keys=True, default=str)


def _cached(kind: str, fn: Callable[[GeneratorRef], BuiltPart]) -> Callable[[GeneratorRef], BuiltPart]:
    def source(ref: GeneratorRef) -> BuiltPart:
        if not isinstance(ref, GeneratorRef):
            raise ShilpaError(ErrorCode.INVALID_PARAMETER, f"{kind} parts need a GeneratorRef")
        key = _key(kind, ref)
        part = _cache.get(key)
        if part is None:
            _stats["misses"] += 1
            part = fn(ref)
            _cache[key] = part
            while len(_cache) > CACHE_SIZE:
                _cache.popitem(last=False)
        else:
            _stats["hits"] += 1
            _cache.move_to_end(key)
        return replace(part, ports=dict(part.ports), meta=dict(part.meta))

    return source


def cache_stats() -> dict[str, int]:
    return {**_stats, "size": len(_cache)}


def clear_cache() -> None:
    _cache.clear()
    _stats.update(hits=0, misses=0)


# ---------------------------------------------------------------- catalog


def _catalog(ref: GeneratorRef) -> BuiltPart:
    from ..catalog import resolve

    return resolve(ref.generator, ref.params)


# ---------------------------------------------------------------- weldment


def _weldment_templates() -> dict[str, Callable[[dict[str, Any]], Any]]:
    from ..weldment import bike_frame as bf

    return {
        "bike.frame": lambda p: bf.frame_spec(bf.FrameGeometry.model_validate(p)),
        "bike.fork": lambda p: bf.fork_spec(bf.ForkGeometry.model_validate(p)),
    }


def _weldment(ref: GeneratorRef) -> BuiltPart:
    from pydantic import ValidationError

    from ..weldment import WeldmentSpec, build_weldment

    templates = _weldment_templates()
    try:
        if ref.generator in templates:
            spec = templates[ref.generator](ref.params)
        elif ref.generator == "weldment":
            spec = WeldmentSpec.model_validate(ref.params.get("spec", ref.params))
        else:
            raise ShilpaError(ErrorCode.UNSUPPORTED_OPERATION,
                              f"unknown weldment generator {ref.generator!r}; known: {sorted(templates) + ['weldment']}")
    except ValidationError as exc:
        raise ShilpaError(ErrorCode.INVALID_PARAMETER, f"{ref.generator}: {exc.errors()[0]['msg']}",
                          feature_id=ref.generator, details={"errors": exc.errors(include_url=False)}) from None
    res = build_weldment(spec, strict=True)
    part = res.part
    # ``pieces`` (coped solid per member, part-local) lets checks measure against single tubes, which
    # is far faster than BRepExtrema against the fused frame.
    part.meta.update(generator=ref.generator, params=ref.params, cut_list=res.cut_list, pieces=res.pieces,
                     weldment_checks=[c for c in res.checks if not c["passed"]])
    return part


# ---------------------------------------------------------------- sheet metal


def _sheet_metal(ref: GeneratorRef) -> BuiltPart:
    from pydantic import ValidationError

    from ..sheetmetal import SheetMetalSpec, build_part

    try:
        spec = SheetMetalSpec.model_validate(ref.params.get("spec", ref.params))
    except ValidationError as exc:
        raise ShilpaError(ErrorCode.INVALID_PARAMETER, f"sheet_metal {ref.generator}: {exc.errors()[0]['msg']}",
                          feature_id=ref.generator, details={"errors": exc.errors(include_url=False)}) from None
    part = build_part(spec)
    part.meta.setdefault("generator", ref.generator)
    return part


BUILTIN: dict[str, Callable[[GeneratorRef], BuiltPart]] = {
    "catalog": _cached("catalog", _catalog),
    "weldment": _cached("weldment", _weldment),
    "sheet_metal": _cached("sheet_metal", _sheet_metal),
}
