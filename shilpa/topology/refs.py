"""Parsing of persistent topology references (``NamedSelector.ref``). Pure strings, no kernel.

Kept apart from ``naming.py`` so the compiler can check references statically (every
reference must start with an earlier feature's id) without importing build123d.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# A face name or prefix: feature id, then roles separated by '.', each optionally indexed '[k]', optional '#k'.
_FACES = re.compile(r"^[a-z][a-z0-9_]*(\[(\d+|\*)\])?(\.[a-z][a-z0-9_]*(\[([a-z0-9_]+|\*)\])?)*(#\d+)?$")


class RefSyntaxError(ValueError):
    pass


@dataclass(frozen=True)
class Term:
    kind: str  # "faces" | "edges_of" | "shared"
    faces: tuple[str, ...]  # one face reference, or two for "shared"
    index: int | None = None  # "A&B~k": the k-th of several edges shared by the same two faces


def parse(ref: str) -> list[Term]:
    terms = []
    for raw in ref.split(","):
        t = raw.strip()
        if not t:
            continue
        if "&" in t:
            parts = tuple(p.strip() for p in t.split("&"))
            if len(parts) != 2:
                raise RefSyntaxError(f"{t!r}: an edge is shared by exactly two faces; write 'A&B'")
            index = None
            m = re.match(r"^(.*)~(\d+)$", parts[1])
            if m:
                parts, index = (parts[0], m.group(1)), int(m.group(2))
            term = Term("shared", parts, index)
        elif t.endswith(".edges"):
            term = Term("edges_of", (t[: -len(".edges")],))
        else:
            term = Term("faces", (t,))
        for f in term.faces:
            if not _FACES.match(f):
                raise RefSyntaxError(f"{f!r} is not a face name such as 'extrude_1.top' or 'hole_1.wall[0]'")
        terms.append(term)
    if not terms:
        raise RefSyntaxError("empty reference")
    return terms


def kind(ref: str) -> str:
    """"faces" or "edges": what a reference resolves to."""
    kinds = {"faces" if t.kind == "faces" else "edges" for t in parse(ref)}
    if len(kinds) > 1:
        raise RefSyntaxError(f"{ref!r} mixes faces and edges")
    return kinds.pop()


def feature_ids(ref: str) -> set[str]:
    """Feature ids a reference names (the leading component of every face name)."""
    return {re.match(r"[a-z][a-z0-9_]*", f).group(0) for t in parse(ref) for f in t.faces}


def matches(name: str, ref: str) -> bool:
    """A name matches a reference equal to it or to a prefix ending at '.', '[' or '#'.

    ``[*]`` in a reference matches any index: ``pattern_1[*].boss.top`` is the boss top of
    every pattern copy.
    """
    if "[*]" not in ref:
        return name == ref or (name.startswith(ref) and name[len(ref)] in ".[#")
    rx = re.escape(ref).replace(r"\[\*\]", r"\[\d+\]")
    return re.match(rx + r"($|[.\[#])", name) is not None


def generalize(name: str) -> str:
    """Forget instance numbers: 'hole_1.wall[2]#1' -> 'hole_1.wall', 'row[3].boss.top' -> 'row[*].boss.top'.

    A trailing index is dropped (the stem selects every instance); an inner one, such as a
    pattern copy number, becomes ``[*]``.
    """
    base = re.sub(r"\[\d+\]$", "", name.split("#", 1)[0])
    return re.sub(r"\[\d+\](?=\.)", "[*]", base)
