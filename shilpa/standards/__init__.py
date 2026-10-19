"""Dimension tables Shilpa owns, as data files with their sources (no CAD imports).

Each ``data/*.csv`` table has an entry in ``data/sources.json`` saying which
standards it encodes, what the values are based on, where they came from and
under what terms. ``table(name)`` reads a CSV with numbers converted (empty
cells become ``None``; identifier columns in ``TEXT_COLUMNS`` stay strings);
``by(name, key)`` indexes it by a column. Adding a size is a CSV edit; a table
without a sources entry fails the test suite.

Tables that bd_warehouse already publishes (screws, nuts, bearings, O-rings...)
are read from bd_warehouse itself, not copied here.
"""

from __future__ import annotations

import csv
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parent / "data"
# Identifier columns stay text even when they look numeric ("608", "6204").
TEXT_COLUMNS = {"designation", "size", "standard", "thread", "dash_number"}


def _value(text: str) -> Any:
    text = text.strip()
    if text == "":
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


@lru_cache(maxsize=None)
def _rows(name: str) -> tuple[dict[str, Any], ...]:
    with open(DATA / name, encoding="utf-8", newline="") as fh:
        return tuple({k: (v.strip() if k in TEXT_COLUMNS else _value(v)) for k, v in row.items()}
                     for row in csv.DictReader(fh))


def table(name: str) -> list[dict[str, Any]]:
    """Rows of ``data/<name>`` (a fresh list; rows are shared, do not mutate them)."""
    return list(_rows(name))


def by(name: str, key: str) -> dict[Any, dict[str, Any]]:
    """Rows of ``data/<name>`` keyed by column ``key`` (first row wins on duplicates)."""
    out: dict[Any, dict[str, Any]] = {}
    for row in _rows(name):
        out.setdefault(row[key], row)
    return out


@lru_cache(maxsize=None)
def sources() -> dict[str, dict[str, Any]]:
    return json.loads((DATA / "sources.json").read_text(encoding="utf-8"))


def source(name: str) -> dict[str, Any]:
    return sources()[name]
