"""Resolve @-mentions to parts, deterministically (spec 2.2, 4.3 step 1). No LLM.

Order of lookup for ``@name`` (case-insensitive):

1. **This composition.** Instances whose id is ``name`` or whose part slug is ``name``. One match
   is that instance; several (two brackets) is an *ambiguous* blocker listing each, never a guess.
   ``@name#k`` picks the k-th instance (1-based, in the order they were added).
2. **Native library.** Tenant models (single parts) whose slug is ``name``, pinned to their head
   version ([Assumption] spec 8.4: versions are always pinned). Several is ambiguous.
3. **Catalog.** Compose aliases (``shaft-20``), then the rule-based designation lookup
   (``ISO4032-M6`` -> ``nut.hex`` ISO 4032 M6-1). Only a unique best hit resolves.

A pinned chip (picked from the @ picker) skips the lookup but is still checked against the
library: an item outside the tenant's library, or a version not of that item, is refused.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from ..contracts.composition import Predicate, Ref, Selector
from . import mentions as mp
from .features import PartInfo, catalog_part, native_part, params_hash

CACHE_SIZE = 64
_parts: "OrderedDict[str, PartInfo]" = OrderedDict()
CATALOG_MIN_SCORE = 0.85


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s[:64] or "part"


def instance_base(slug: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", slug.lower()).strip("_") or "part"
    if not s[0].isalpha():
        s = "p_" + s
    return s[:56]


# [Assumption] spec 7 fixture names that the designation lookup does not know.
_ALIASES: list[tuple[re.Pattern, Any]] = [
    (re.compile(r"^shaft-(\d+)$"), lambda m: ("linear.shaft", {"diameter": int(m.group(1)), "length": 200.0},
                                             f"Linear shaft d{m.group(1)} x 200")),
]


@dataclass
class NativeItem:
    model_id: str
    name: str
    version_id: str
    recipe: dict
    slug: str = ""

    def __post_init__(self):
        self.slug = self.slug or slugify(self.name)


@dataclass
class InstanceState:
    id: str
    part_key: str
    slug: str
    label: str
    step_id: str
    grounded: bool = False
    placed: bool = False
    copy_of: str | None = None


@dataclass
class Library:
    """What a composition can mention: the tenant's native parts plus the catalog."""

    natives: list[NativeItem] = field(default_factory=list)  # head versions, the ones mentions resolve to
    pinned: dict[str, NativeItem] = field(default_factory=dict)  # older versions pinned by applied steps
    other_kinds: dict[str, str] = field(default_factory=dict)  # model id -> kind, for models Compose P0 cannot use

    def native(self, model_id: str) -> NativeItem | None:
        return next((n for n in self.natives if n.model_id == model_id), None)

    def part(self, ref: Ref) -> PartInfo:
        """The pinned part a resolved reference points at (cached by immutable key)."""
        if ref.source == "native" or (ref.item and not ref.item.startswith("catalog:")):
            nat = self.pinned.get(ref.version or "")
            if nat is None or nat.model_id != ref.item:
                nat = self.native(ref.item or "")
            if nat is None or (ref.version and ref.version != nat.version_id):
                raise LookupError(f"{ref.text}: that part version is not in your library")
            key = f"native:{nat.version_id}"
            return _cached(key, lambda: native_part(nat.recipe, item=nat.model_id, version=nat.version_id, label=nat.name, slug=nat.slug))
        gen, params = ref.generator, ref.params or {}
        if not gen:
            raise LookupError(f"{ref.text}: no catalog generator")
        key = f"catalog:{gen}:{params_hash(params)}"
        slug = slugify(ref.text.lstrip("@").split(".")[0].split("{")[0].split("#")[0])
        label = next((h["label"] for h in catalog_hits(slug) if h["generator"] == gen and h["params"] == params), None)             or _catalog_label(gen, params)
        return _cached(key, lambda: catalog_part(gen, params, label=label, slug=slug))


def _cached(key: str, make) -> PartInfo:
    part = _parts.get(key)
    if part is None:
        part = make()
        _parts[key] = part
        while len(_parts) > CACHE_SIZE:
            _parts.popitem(last=False)
    else:
        _parts.move_to_end(key)
    return part


def clear_cache() -> None:
    _parts.clear()


def _catalog_label(gen: str, params: dict) -> str:
    from ..catalog.designations import lookup

    std, size = params.get("standard"), params.get("size")
    if std and size:
        hits = lookup(f"{std} {str(size).split('-')[0]}")
        for h in hits:
            if h["generator"] == gen and h["params"] == params:
                return h["label"]
        return f"{str(std).upper().replace('ISO', 'ISO ')} {size}"
    if params.get("designation"):
        return str(params["designation"])
    if gen == "linear.shaft":
        return f"Linear shaft d{params.get('diameter')} x {params.get('length', 300):g}"
    return gen


def catalog_hits(name: str) -> list[dict]:
    """Catalog candidates for a slug, best first; [] when none."""
    from ..catalog.designations import lookup

    low = name.lower()
    for pat, make in _ALIASES:
        m = pat.match(low)
        if m:
            gen, params, label = make(m)
            return [{"generator": gen, "params": params, "label": label, "score": 1.0}]
    hits = [h for h in lookup(re.sub(r"[-_]+", " ", name)[:200]) if h["score"] >= CATALOG_MIN_SCORE]
    if not hits:
        return []
    top = hits[0]["score"]
    return [h for h in hits if h["score"] == top]


# ---------------------------------------------------------------- mentions


@dataclass
class Resolution:
    mention: str  # m1, m2 ...
    text: str
    status: str  # ok | ambiguous | unknown | invalid
    ref: Ref | None = None
    label: str = ""
    message: str = ""
    candidates: list[dict] = field(default_factory=list)  # for ambiguous: [{label, ref}]

    def card(self) -> dict:
        return {"id": self.mention, "text": self.text, "status": self.status, "label": self.label, "message": self.message,
                "ref": self.ref.model_dump(mode="json", exclude_none=True, by_alias=True) if self.ref else None,
                "candidates": self.candidates}


def predicates(m: mp.Mention) -> list[Predicate]:
    out = []
    for p in m.filter:
        if p.attr == "on":
            out.append(Predicate(attr="on", op="=", value=p.value))
        else:
            out.append(Predicate(attr=p.attr, op=p.op, value=p.value, unit=p.unit))
    return out


def selector_of(m: mp.Mention) -> Selector | None:
    path = m.path_text or None
    preds = predicates(m)
    if path is None and not preds:
        return None
    if path is None:
        path = "holes[*]"  # a filter on a bare part filters its holes ([Assumption] the only filterable group in P0)
    return Selector(path=path, filter=preds)


def _instance_candidates(name: str, index: int | None, instances: dict[str, InstanceState]) -> list[InstanceState]:
    low = name.lower()
    by_slug = [i for i in instances.values() if i.slug.lower() == low]
    if index is not None:
        if by_slug:
            return [by_slug[index - 1]] if index <= len(by_slug) else []
        return []
    exact = instances.get(low)
    if exact is not None and len(by_slug) <= 1:
        return [exact]
    if by_slug:
        return by_slug
    return [exact] if exact is not None else []


def resolve_mention(mid: str, m: mp.Mention, library: Library, instances: dict[str, InstanceState],
                    pinned: mp.PinnedRef | None = None) -> Resolution:
    text = m.text
    if len(m.parts) > 1:
        return Resolution(mid, text, "invalid", message=f"{text}: nested parts (a/b) arrive with complex parts in a later phase")
    name, index = m.part.name, m.part.index
    sel = selector_of(m)
    if pinned is not None:
        return _resolve_pinned(mid, m, pinned, library, instances, sel)

    cands = _instance_candidates(name, index, instances)
    if len(cands) == 1:
        i = cands[0]
        return Resolution(mid, text, "ok", Ref(text=text, mention=mid, source="instance", instance=i.id, selector=sel),
                          label=f"{i.label} ({i.id})")
    extra = {"selector": sel.model_dump(mode="json", exclude_none=True)} if sel else {}
    if len(cands) > 1:
        opts = [{"label": f"{c.id} (added in step {c.step_id})", "ref": {"source": "instance", "instance": c.id, **extra}} for c in cands]
        return Resolution(mid, text, "ambiguous", message=f"{text} matches {len(cands)} instances: "
                          + ", ".join(f"{name}#{k + 1} ({c.id})" for k, c in enumerate(cands)) + ". Pick one.", candidates=opts)
    if index is not None:
        return Resolution(mid, text, "unknown", message=f"{text}: there is no instance {index} of @{name} in this composition")

    natives = [n for n in library.natives if n.slug.lower() == name.lower()]
    if len(natives) == 1:
        n = natives[0]
        return Resolution(mid, text, "ok", Ref(text=text, mention=mid, source="native", item=n.model_id, version=n.version_id,
                                              selector=sel), label=n.name)
    if len(natives) > 1:
        opts = [{"label": f"{n.name} ({n.model_id[:8]})", "ref": {"source": "native", "item": n.model_id, "version": n.version_id, **extra}}
                for n in natives]
        return Resolution(mid, text, "ambiguous", message=f"{text} matches {len(natives)} parts in your library. Pick one.",
                          candidates=opts)

    hits = catalog_hits(name)
    if len(hits) == 1:
        h = hits[0]
        return Resolution(mid, text, "ok", Ref(text=text, mention=mid, source="catalog", item=f"catalog:{h['generator']}",
                                              version=params_hash(h["params"]), generator=h["generator"], params=h["params"],
                                              selector=sel), label=h["label"])
    if len(hits) > 1:
        opts = [{"label": h["label"], "ref": {"source": "catalog", "generator": h["generator"], "params": h["params"], **extra}} for h in hits]
        return Resolution(mid, text, "ambiguous", message=f"{text} matches {len(hits)} catalog parts equally well. Pick one.",
                          candidates=opts)
    return Resolution(mid, text, "unknown", message=f"{text} is not in this composition, your library or the catalog.")


_KIND_TEXT = {"sheet_metal": "sheet metal", "assembly": "an assembly", "product": "a product"}


def _resolve_pinned(mid, m, pinned: mp.PinnedRef, library: Library, instances, sel) -> Resolution:
    text = m.text
    if pinned.path and sel is None:
        sel = Selector(path=pinned.path)
    if pinned.instance:
        if pinned.instance not in instances:
            return Resolution(mid, text, "unknown", message=f"{text}: instance {pinned.instance!r} is not in this composition")
        i = instances[pinned.instance]
        return Resolution(mid, text, "ok", Ref(text=text, mention=mid, source="instance", instance=i.id,
                                              feature_uid=pinned.feature_uid, selector=sel), label=f"{i.label} ({i.id})")
    item = pinned.item or ""
    if item.startswith("catalog:"):
        gen = item.split(":", 1)[1]
        from ..catalog import _REGISTRY

        if gen not in _REGISTRY or pinned.params is None:
            return Resolution(mid, text, "unknown", message=f"{text}: unknown catalog part")
        if pinned.version and pinned.version != params_hash(pinned.params):
            return Resolution(mid, text, "invalid", message=f"{text}: pinned parameters do not match their version")
        return Resolution(mid, text, "ok", Ref(text=text, mention=mid, source="catalog", item=item, version=params_hash(pinned.params),
                                              generator=gen, params=dict(pinned.params), feature_uid=pinned.feature_uid,
                                              selector=sel), label=_catalog_label(gen, pinned.params))
    n = library.native(item)
    if n is None:
        kind = library.other_kinds.get(item)
        if kind:
            return Resolution(mid, text, "invalid", message=f"{text}: Compose can only use plain parts and catalog parts for now, "
                              f"and this one is {_KIND_TEXT.get(kind, kind)}")
        return Resolution(mid, text, "unknown", message=f"{text}: that part is not in your library")
    if pinned.version and pinned.version != n.version_id:
        return Resolution(mid, text, "invalid", message=f"{text}: version {pinned.version[:8]} is not the pinned head of {n.name} "
                          "(older versions arrive with the library in P1)")
    return Resolution(mid, text, "ok", Ref(text=text, mention=mid, source="native", item=n.model_id, version=n.version_id,
                                          feature_uid=pinned.feature_uid, selector=sel), label=n.name)


def resolve_prompt(prompt: str, library: Library, instances: dict[str, InstanceState],
                   pins: dict[str, mp.PinnedRef] | None = None) -> tuple[list[Resolution], list[mp.MentionError]]:
    """Every mention in the prompt, resolved; identical texts share one id (m1, m2 ... in order of first use)."""
    parsed = mp.parse(prompt)
    out: list[Resolution] = []
    seen: dict[str, str] = {}
    for m in parsed.mentions:
        if m.text in seen:
            continue
        mid = f"m{len(seen) + 1}"
        seen[m.text] = mid
        out.append(resolve_mention(mid, m, library, instances, (pins or {}).get(m.text)))
    return out, parsed.errors
