"""Per-request selection of golden recipe examples for the plan prompt.

Deterministic and dependency-free: each corpus fixture (evals/corpus/*.json) is described by the words of its
description, its family, its operation names and its parameter names; a request is scored against those by
idf-weighted keyword overlap with a small synonym table. Selection is greedy with diminishing returns so the k
examples cover different aspects of the request. The chosen examples are returned sorted by fixture id, so the
same request always yields the same text and similar requests share a stable prompt.
"""

from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path

from .schemas import from_recipe

CORPUS = Path(__file__).resolve().parents[2] / "evals" / "corpus"
# Used when a request overlaps nothing in the corpus (the first k of these).
DEFAULT_IDS = ("P01", "F03", "B03", "E02", "H03", "N02", "N07", "N08")

_STOP = {"the", "and", "with", "for", "from", "that", "this", "each", "are", "has", "have", "mm", "one", "two", "its",
         "into", "per", "all", "any", "not", "use", "using", "name", "value", "units", "evidence", "dimensions",
         "features", "summary", "family", "assumptions", "confirmed", "requirements", "unit", "true", "false", "null"}
# Request words that name an operation or fixture family without sharing its spelling.
_SYNONYMS = {
    "bolt": ("polar", "flange", "pattern"), "pcd": ("polar", "flange", "pattern"), "circle": ("polar",),
    "corner": ("corner", "pattern"), "corners": ("corner", "pattern"), "grid": ("linear", "pattern"),
    "row": ("linear", "pattern"), "array": ("linear", "pattern"), "pitch": ("linear", "pattern"),
    "bend": ("sweep", "path", "tube"), "pipe": ("sweep", "path", "tube"), "elbow": ("revolve", "tube"),
    "transition": ("loft", "duct"), "hopper": ("loft", "duct", "shell"), "nozzle": ("loft", "duct"),
    "turned": ("stepped", "shaft", "revolve"), "lathe": ("stepped", "shaft", "revolve"), "pin": ("shaft", "stepped"),
    "washer": ("spacer",), "bushing": ("spacer",), "sleeve": ("spacer",), "tapped": ("tapped", "hole"),
    "thread": ("tapped", "hole"), "counterbore": ("counterbored", "hole"), "countersink": ("countersunk", "hole"),
    "countersunk": ("countersunk", "hole"), "counterbored": ("counterbored", "hole"), "helical": ("helix", "sweep"),
    "coil": ("helix", "sweep"), "spring": ("helix", "sweep"), "housing": ("shell", "enclosure"),
    "case": ("enclosure", "shell"), "box": ("enclosure", "pocket"), "hollow": ("bore", "shell"),
    "symmetric": ("mirror",), "symmetrical": ("mirror",), "spoke": ("polar", "pattern"), "teeth": ("polar", "pattern"),
    "gear": ("polar", "pattern"), "slot": ("slot",), "boss": ("boolean", "pattern"), "rib": ("boolean",),
}


def _tokens(text: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-z]+", text.lower()):
        if len(w) < 3 or w in _STOP:
            continue
        out.append(w[:-1] if w.endswith("s") and len(w) > 3 and not w.endswith("ss") else w)
    return out


@lru_cache(maxsize=1)
def _fixtures() -> tuple[dict, ...]:
    """Every parseable corpus fixture: id, family, description, keyword set, rendered example text."""
    rows = []
    for p in sorted(CORPUS.glob("*.json")):
        try:
            fx = json.loads(p.read_text(encoding="utf-8"))
            recipe = fx["recipe"]
            text = f"Example - {fx['description']}:\n{json.dumps(from_recipe(recipe), separators=(',', ':'))}"
        except (OSError, ValueError, KeyError):
            continue
        feats = recipe.get("features", [])
        words = _tokens(" ".join([fx.get("description", ""), fx.get("family", ""),
                                  " ".join(f.get("op", "").replace("_", " ") for f in feats),
                                  " ".join(str(k).replace("_", " ") for k in recipe.get("parameters", {}))]))
        rows.append({"id": fx.get("id", p.stem), "family": (fx.get("family") or "").lower(), "words": set(words), "text": text})
    return tuple(rows)


@lru_cache(maxsize=1)
def _idf() -> dict[str, float]:
    fx = _fixtures()
    df: dict[str, int] = {}
    for f in fx:
        for w in f["words"]:
            df[w] = df.get(w, 0) + 1
    return {w: math.log(1 + len(fx) / n) for w, n in df.items()}


def _query_words(query: str) -> set[str]:
    words = set(_tokens(query))
    for w in list(words) + re.findall(r"[a-z]+", query.lower()):
        words.update(_SYNONYMS.get(w, ()))
    return words


def select_example_ids(query: str, k: int, family: str | None = None) -> list[str]:
    """The ids of the k fixtures most relevant to ``query`` (free text), sorted by id. k <= 0 selects none."""
    if k <= 0:
        return []
    fx, idf = _fixtures(), _idf()
    q = _query_words(query)
    weight = dict(idf)
    chosen: list[str] = []
    fam = (family or "").lower()
    for _ in range(min(k, len(fx))):
        best, best_score = None, 0.0
        for f in fx:
            if f["id"] in chosen:
                continue
            score = sum(weight[w] for w in f["words"] & q)
            if fam and f["family"] == fam:
                score += 1.5
            if score > best_score + 1e-9 or (best is not None and abs(score - best_score) <= 1e-9 and f["id"] < best["id"]):
                best, best_score = f, score
        if best is None or best_score <= 0:
            break
        chosen.append(best["id"])
        for w in best["words"] & q:  # diminishing returns: the next example should cover something else
            weight[w] *= 0.4
    for fid in DEFAULT_IDS:  # pad with defaults when the request matched fewer than k fixtures
        if len(chosen) >= min(k, len(fx)):
            break
        if fid not in chosen and any(f["id"] == fid for f in fx):
            chosen.append(fid)
    return sorted(chosen)


def examples_text(query: str, k: int, family: str | None = None) -> str:
    by_id = {f["id"]: f["text"] for f in _fixtures()}
    return "\n\n".join(by_id[i] for i in select_example_ids(query, k, family))
