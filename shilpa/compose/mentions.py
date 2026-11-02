"""@-mention grammar (spec section 2.1), parsed deterministically. No LLM, no regex backtracking.

::

    mention      = "@" part_ref [ "." feature_path ] [ filter ]
    part_ref     = name [ "#" int ] { "/" name [ "#" int ] }
    feature_path = segment { "." segment }
    segment      = ident [ "[" index_expr "]" ]
    index_expr   = int | int ".." int | "*" | "first" | "last"
    filter       = "{" predicate { ("," | "and") predicate } "}"
    predicate    = attr op value [ unit ] | "kind" "=" ident | "thread" "=" ident | "on" ( mention | "." feature_path )

Part names are slugs (``ISO4032-M6``, ``shaft-20``, ``6204``) or instance names; matching is
case-insensitive later, in the resolver. A ``.`` that is not followed by a name character
ends the mention (sentence punctuation), as does whitespace or any other character.

The parser never raises on user text: problems come back as ``MentionError`` records with
the character offset, so the UI can underline them. Everything in a mention is data; a
part called "ignore previous instructions" is only a name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

MAX_MENTIONS = 32
MAX_NAME = 64
MAX_INDEX = 10_000
MAX_DEPTH = 3  # "on @x" nesting inside filters
UNITS = ("mm", "cm", "m", "in", "ft", "deg", "rad")
ATTRS = ("diameter", "depth", "length", "area", "x", "y", "z", "normal")
OPS = ("<=", ">=", "~=", "≈", "=", "<", ">", "~")
OP_CANON = {"~=": "≈", "~": "≈"}
# Singular spellings users type for groups: @bracket.hole[2] means the second of @bracket.holes.
GROUP_ALIASES = {"hole": "holes", "port": "ports", "faces": "face", "axes": "axis", "edges": "edge"}


@dataclass(frozen=True)
class Index:
    kind: str  # int | range | all | first | last
    a: int | None = None
    b: int | None = None

    def text(self) -> str:
        return {"int": f"{self.a}", "range": f"{self.a}..{self.b}", "all": "*", "first": "first", "last": "last"}[self.kind]


@dataclass(frozen=True)
class PartRef:
    name: str
    index: int | None = None  # @bolt#2: the second instance (1-based)


@dataclass(frozen=True)
class Segment:
    name: str
    index: Index | None = None

    def text(self) -> str:
        return self.name + (f"[{self.index.text()}]" if self.index else "")


@dataclass
class Pred:
    attr: str
    op: str
    value: Any
    unit: str | None = None
    on: "Mention | None" = None  # on @mention
    on_path: list[Segment] | None = None  # on .face.top (relative to the mention's own part)


@dataclass
class Mention:
    text: str
    start: int
    end: int
    parts: list[PartRef]
    path: list[Segment] = field(default_factory=list)
    filter: list[Pred] = field(default_factory=list)

    @property
    def part(self) -> PartRef:
        return self.parts[-1]

    @property
    def part_text(self) -> str:
        return "/".join(p.name + (f"#{p.index}" if p.index else "") for p in self.parts)

    @property
    def path_text(self) -> str:
        """Canonical feature path: singular group aliases folded (hole[2] -> holes[2])."""
        segs = list(self.path)
        if segs and segs[0].name.lower() in GROUP_ALIASES:
            segs[0] = Segment(GROUP_ALIASES[segs[0].name.lower()], segs[0].index)
        return ".".join(s.text() for s in segs)


@dataclass(frozen=True)
class MentionError:
    start: int
    message: str


@dataclass
class ParseResult:
    mentions: list[Mention]
    errors: list[MentionError]


class _Fail(Exception):
    def __init__(self, pos: int, message: str):
        super().__init__(message)
        self.pos, self.message = pos, message


def _is_name_char(c: str) -> bool:
    return c.isascii() and (c.isalnum() or c in "_-")


def _is_ident_start(c: str) -> bool:
    return c.isascii() and (c.isalpha() or c == "_")


def _is_ident_char(c: str) -> bool:
    return c.isascii() and (c.isalnum() or c == "_")


class _Scanner:
    def __init__(self, text: str):
        self.t = text
        self.n = len(text)

    def peek(self, i: int, k: int = 1) -> str:
        return self.t[i:i + k]

    def skip_ws(self, i: int) -> int:
        while i < self.n and self.t[i] in " \t":
            i += 1
        return i

    def name(self, i: int) -> tuple[str, int]:
        j = i
        while j < self.n and _is_name_char(self.t[j]):
            j += 1
        # A trailing hyphen is punctuation ("@plate- see"), not part of the name.
        while j > i and self.t[j - 1] == "-":
            j -= 1
        if j == i:
            raise _Fail(i, "expected a part name after @")
        if j - i > MAX_NAME:
            raise _Fail(i, f"part name longer than {MAX_NAME} characters")
        return self.t[i:j], j

    def ident(self, i: int) -> tuple[str, int]:
        if i >= self.n or not _is_ident_start(self.t[i]):
            raise _Fail(i, "expected a feature name")
        j = i + 1
        while j < self.n and _is_ident_char(self.t[j]):
            j += 1
        if j - i > MAX_NAME:
            raise _Fail(i, f"feature name longer than {MAX_NAME} characters")
        return self.t[i:j], j

    def integer(self, i: int) -> tuple[int, int]:
        j = i
        while j < self.n and self.t[j].isascii() and self.t[j].isdigit():
            j += 1
        if j == i:
            raise _Fail(i, "expected a whole number")
        if j - i > 5 or int(self.t[i:j]) > MAX_INDEX:
            raise _Fail(i, f"index larger than {MAX_INDEX}")
        return int(self.t[i:j]), j

    def number(self, i: int) -> tuple[float, int]:
        j = i
        if j < self.n and self.t[j] in "+-":
            j += 1
        digits = 0
        while j < self.n and (self.t[j].isascii() and self.t[j].isdigit() or self.t[j] == "."):
            if self.t[j] == "." and (j + 1 >= self.n or not self.t[j + 1].isdigit()):
                break
            digits += self.t[j] != "."
            j += 1
        if digits == 0:
            raise _Fail(i, "expected a number")
        if j - i > 20:
            raise _Fail(i, "number too long")
        try:
            return float(self.t[i:j]), j
        except ValueError:
            raise _Fail(i, "expected a number") from None

    # ------------------------------------------------------------ grammar

    def index_expr(self, i: int) -> tuple[Index, int]:
        if self.peek(i) == "*":
            return Index("all"), i + 1
        for word in ("first", "last"):
            if self.t[i:i + len(word)].lower() == word:
                return Index(word), i + len(word)
        a, i = self.integer(i)
        if self.peek(i, 2) == "..":
            b, i = self.integer(i + 2)
            if b < a:
                raise _Fail(i, "index range must run low..high")
            return Index("range", a, b), i
        return Index("int", a), i

    def segment(self, i: int) -> tuple[Segment, int]:
        name, i = self.ident(i)
        idx = None
        if self.peek(i) == "[":
            idx, i = self.index_expr(self.skip_ws(i + 1))
            i = self.skip_ws(i)
            if self.peek(i) != "]":
                raise _Fail(i, "expected ] to close the index")
            i += 1
        return Segment(name, idx), i

    def feature_path(self, i: int) -> tuple[list[Segment], int]:
        segs = []
        while True:
            seg, i = self.segment(i)
            segs.append(seg)
            if len(segs) > 6:
                raise _Fail(i, "feature path too deep")
            if self.peek(i) == "." and i + 1 < self.n and _is_ident_start(self.t[i + 1]):
                i += 1
                continue
            return segs, i

    def predicate(self, i: int, depth: int) -> tuple[Pred, int]:
        word, j = self.ident(i)
        low = word.lower()
        if low == "on":
            j = self.skip_ws(j)
            if self.peek(j) == "@":
                m, j = self.mention(j, depth + 1)
                return Pred("on", "=", m.text, on=m), j
            if self.peek(j) == "." and j + 1 < self.n and _is_ident_start(self.t[j + 1]):
                segs, j = self.feature_path(j + 1)
                return Pred("on", "=", "." + ".".join(s.text() for s in segs), on_path=segs), j
            raise _Fail(j, "expected @part or .feature after 'on'")
        if low not in ATTRS and low not in ("kind", "thread"):
            raise _Fail(i, f"unknown filter attribute {word!r}; use one of {', '.join(ATTRS + ('kind', 'thread', 'on'))}")
        j = self.skip_ws(j)
        op = next((o for o in OPS if self.t.startswith(o, j)), None)
        if op is None:
            raise _Fail(j, "expected a comparison (=, <, >, <=, >=, ≈)")
        op_c = OP_CANON.get(op, op)
        j = self.skip_ws(j + len(op))
        if low in ("kind", "thread"):
            if op_c != "=":
                raise _Fail(j, f"{low} only takes =")
            value, j = self.name(j) if j < self.n and _is_name_char(self.t[j]) else (None, j)
            if value is None:
                raise _Fail(j, f"expected a value for {low}")
            return Pred(low, "=", value), j
        value, j = self.number(j)
        k = self.skip_ws(j)
        unit = None
        for u in sorted(UNITS, key=len, reverse=True):
            if self.t[k:k + len(u)].lower() == u and not (k + len(u) < self.n and _is_ident_char(self.t[k + len(u)])):
                unit, j = u, k + len(u)
                break
        return Pred(low, op_c, value, unit), j

    def filter(self, i: int, depth: int) -> tuple[list[Pred], int]:
        preds = []
        i = self.skip_ws(i)
        while True:
            if len(preds) >= 8:
                raise _Fail(i, "at most 8 filter terms")
            p, i = self.predicate(i, depth)
            preds.append(p)
            i = self.skip_ws(i)
            if self.peek(i) == "}":
                return preds, i + 1
            if self.peek(i) == ",":
                i = self.skip_ws(i + 1)
                continue
            if self.t[i:i + 3].lower() == "and" and i + 3 < self.n and not _is_ident_char(self.t[i + 3]):
                i = self.skip_ws(i + 3)
                continue
            if i >= self.n:
                raise _Fail(i, "expected } to close the filter")
            raise _Fail(i, "expected , or and between filter terms, or } to close")

    def mention(self, i: int, depth: int = 0) -> tuple[Mention, int]:
        if depth > MAX_DEPTH:
            raise _Fail(i, "mentions nested too deeply")
        start = i
        i += 1  # "@"
        parts = []
        while True:
            name, i = self.name(i)
            idx = None
            if self.peek(i) == "#":
                idx, i = self.integer(i + 1)
                if idx < 1:
                    raise _Fail(i, "instance numbers start at 1")
            parts.append(PartRef(name, idx))
            if self.peek(i) == "/" and i + 1 < self.n and _is_name_char(self.t[i + 1]):
                i += 1
                if len(parts) >= 4:
                    raise _Fail(i, "part path too deep")
                continue
            break
        path: list[Segment] = []
        if self.peek(i) == "." and i + 1 < self.n and _is_ident_start(self.t[i + 1]):
            path, i = self.feature_path(i + 1)
        preds: list[Pred] = []
        if self.peek(i) == "{":
            preds, i = self.filter(i + 1, depth)
        if i - start > 300:
            raise _Fail(start, "mention longer than 300 characters")
        return Mention(self.t[start:i], start, i, parts, path, preds), i


def _at_boundary(text: str, i: int) -> bool:
    """An @ starts a mention at the start of text or after a non-name character (so a@b.com is not one)."""
    return i == 0 or not (_is_name_char(text[i - 1]) or text[i - 1] in ".@")


def parse(text: str) -> ParseResult:
    """Every mention in ``text``, left to right, plus syntax errors. Never raises."""
    sc = _Scanner(text or "")
    mentions: list[Mention] = []
    errors: list[MentionError] = []
    i = 0
    while i < sc.n:
        if sc.t[i] != "@" or not _at_boundary(sc.t, i):
            i += 1
            continue
        if len(mentions) >= MAX_MENTIONS:
            errors.append(MentionError(i, f"at most {MAX_MENTIONS} mentions per prompt"))
            break
        try:
            m, j = sc.mention(i)
            mentions.append(m)
            i = j
        except _Fail as exc:
            errors.append(MentionError(exc.pos, exc.message))
            # resume after the broken mention's run of non-space characters
            j = i + 1
            while j < sc.n and not sc.t[j].isspace():
                j += 1
            i = j
    return ParseResult(mentions, errors)


def parse_one(text: str) -> Mention:
    """Exactly one mention spanning all of ``text``; ValueError otherwise."""
    r = parse(text)
    if r.errors:
        raise ValueError(r.errors[0].message)
    if len(r.mentions) != 1 or r.mentions[0].text != text.strip():
        raise ValueError(f"{text!r} is not a single mention")
    return r.mentions[0]


# ---------------------------------------------------------------- pinning (spec section 2.2)


class PinnedRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item: str | None = Field(default=None, max_length=200)
    version: str | None = Field(default=None, max_length=80)
    instance: str | None = Field(default=None, max_length=64)
    feature_uid: str | None = Field(default=None, max_length=200)
    path: str | None = Field(default=None, max_length=200)
    generator: str | None = Field(default=None, max_length=100)
    params: dict[str, Any] | None = None


class PinnedMention(BaseModel):
    """A chip the user picked: readable text plus the stored reference."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=2, max_length=300)
    ref: PinnedRef


def pin_map(tokens: list[dict] | list[PinnedMention] | None) -> dict[str, PinnedRef]:
    """Validated {mention text: ref}. A token whose text is not one well-formed mention is rejected."""
    out: dict[str, PinnedRef] = {}
    for raw in tokens or []:
        try:
            tok = raw if isinstance(raw, PinnedMention) else PinnedMention.model_validate(raw)
        except ValidationError as exc:
            raise ValueError(f"invalid pinned mention: {exc.errors()[0]['msg']}") from None
        parse_one(tok.text)
        if tok.ref.item is None and tok.ref.instance is None:
            raise ValueError(f"pinned mention {tok.text!r} names neither an item nor an instance")
        out[tok.text] = tok.ref
    return out
