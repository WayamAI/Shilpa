"""Stable content hash of a recipe (canonical JSON, private keys excluded)."""

from __future__ import annotations

import hashlib
import json


def recipe_hash(recipe: dict) -> str:
    clean = {k: v for k, v in recipe.items() if not k.startswith("_")}
    return hashlib.sha256(json.dumps(clean, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
