"""Typed part names to catalog parts, with no model call: ``lookup("M6x20 socket head")``.

Recognised (case-insensitive, spaces optional; standard numbers override the
part-type words):

* Screws: ``M6x20``, ``M6-1 x 20``, ``1/4-20 x 1"`` with a type word (socket
  head / SHCS / cap screw, button, countersunk / flat head / CSK, hex bolt /
  hex head, set / grub, pan, cheese, shoulder, flange, low profile) or a
  standard (``ISO 4762``, ``DIN 912``, ``DIN 933``, ``ISO 10642``, ``DIN 7991``,
  ...). A size and length with "screw" or "bolt" and no type is a socket head.
* Nuts and washers: ``M8 nut`` (flange, domed / acorn, square, thin / jam,
  heat-set insert), ``DIN 934 M6``, ``M6 washer``, ``DIN 125 M8``, ``large /
  fender washer`` (ISO 7093), ``lock washer`` (DIN 6797).
* Bearings: catalogue designations (``6204``, ``6204-2RS``, ``608ZZ``,
  ``7202``, ``NJ 202``, ``30302``) found in any bearing table.
* O-rings (``O-ring 210``, ``AS568-210``, ``O-ring 18.64 x 3.53``), circlips
  (``DIN 471 20``, ``20 mm external circlip``), keys (``key 6x6x32``,
  ``DIN 6885 A 8x7x40``).
* Gears (``spur gear m2 z20``, ``helical gear module 1.5 30 teeth``, ``rack m2``),
  V-slot (``2040 x 500``, ``C-beam 1000 mm``, ``V-slot wheel``, ``T-nut M5``).
* Pipe and flanges (``2 in sch 40 pipe x 1000``, ``NPS 4 class 300 weld neck
  flange``, ``1/2" type K copper tube``), sprockets (``#40 sprocket 20T``),
  worm drives (``worm wheel m2 z30``), OpenBuilds parts (``NEMA 17``, ``Tr8
  lead screw 400 mm``, ``gantry plate``, ``8 mm lock collar``).

Each match is validated against the generator's parameter model (nothing is
built) and comes back as ``{generator, params, label, matched, score}``, best
first.
"""

from __future__ import annotations

import csv
import re
from typing import Any

from pydantic import ValidationError

from . import _REGISTRY, warehouse
from .warehouse import DATA, standard_label

NUM = r"(\d+(?:[.,]\d+)?)"


def _f(x: str) -> float:
    return float(x.replace(",", "."))


def _valid(gen: str, params: dict) -> dict | None:
    try:
        return _REGISTRY[gen].params.model_validate(params).model_dump(mode="json")
    except (ValidationError, ValueError, KeyError):
        return None


def _enum(gen: str, field: str) -> list:
    return _REGISTRY[gen].params.model_json_schema()["properties"][field].get("enum", [])


def _coarse(gen: str, nominal: str, pitch: str | None = None, standard: str | None = None) -> str | None:
    """The bd_warehouse size for ``M6`` (coarse pitch unless given) in this generator's size list."""
    sizes = _enum(gen, "size")
    if standard:  # restrict to the sizes that standard lists, when the class can tell us
        cls = next((c for g, c, *_ in warehouse.SCREWS + warehouse.NUTS + warehouse.WASHERS if g == gen), None)
        if cls is not None and standard in cls.types():
            sizes = cls.sizes(standard)
    if pitch:
        want = f"{nominal}-{pitch:g}" if isinstance(pitch, float) else f"{nominal}-{pitch}"
        return next((s for s in sizes if s == want), None)
    if nominal in sizes:  # washers are listed by nominal ("M6")
        return nominal
    return next((s for s in sizes if s.startswith(f"{nominal}-")), None)


def _match(gen: str, params: dict, label: str, matched: str, score: float) -> dict | None:
    full = _valid(gen, params)
    if full is None:
        return None
    return {"generator": gen, "params": params, "label": label, "matched": matched.strip(), "score": score,
            "summary": _REGISTRY[gen].summary}


# ---------------------------------------------------------------- screws, nuts, washers

# (pattern, generator, default standard)
SCREW_WORDS = [
    (r"socket\s*head|shcs|cap\s*screw|allen", "screw.socket_head", "iso4762"),
    (r"button(\s*head)?|bhcs", "screw.button_head", "iso7380_1"),
    (r"(raised|oval)\s*(countersunk|csk)", "screw.raised_countersunk", "iso2010"),
    (r"countersunk|counter\s*sunk|flat\s*head|csk|fhcs", "screw.countersunk", "iso10642"),
    (r"flange\s*(screw|bolt)|hex\s*flange", "screw.hex_flange", "din1662"),
    (r"hex(agon)?\s*(head|bolt|screw|cap)|\bbolt\b", "screw.hex_head", "iso4017"),
    (r"set\s*screw|grub", "screw.set", "iso4026"),
    (r"pan\s*head", "screw.pan_head", "iso14583"),
    (r"raised\s*cheese", "screw.raised_cheese_head", "iso7045"),
    (r"cheese\s*head", "screw.cheese_head", "iso1207"),
    (r"shoulder", "screw.shoulder", "iso7379"),
    (r"low\s*profile", "screw.low_profile", "OpenBuilds"),
]
# Standard numbers -> (generator, bd_warehouse type), including common DIN aliases of ISO standards.
STANDARDS = {
    "iso4762": ("screw.socket_head", "iso4762"), "din912": ("screw.socket_head", "iso4762"),
    "iso7380": ("screw.button_head", "iso7380_1"), "iso7380-1": ("screw.button_head", "iso7380_1"),
    "iso7380-2": ("screw.button_head_collar", "iso7380_2"),
    "iso10642": ("screw.countersunk", "iso10642"), "din7991": ("screw.countersunk", "iso10642"),
    "iso2009": ("screw.countersunk", "iso2009"), "iso7046": ("screw.countersunk", "iso7046"),
    "iso14581": ("screw.countersunk", "iso14581"), "iso14582": ("screw.countersunk", "iso14582"),
    "iso4017": ("screw.hex_head", "iso4017"), "din933": ("screw.hex_head", "iso4017"),
    "iso4014": ("screw.hex_head", "iso4014"), "din931": ("screw.hex_head", "din931"),
    "din1662": ("screw.hex_flange", "din1662"), "din1665": ("screw.hex_flange", "din1665"),
    "iso4026": ("screw.set", "iso4026"), "din913": ("screw.set", "iso4026"),
    "iso14583": ("screw.pan_head", "iso14583"), "iso1580": ("screw.pan_head", "iso1580"),
    "din967": ("screw.pan_head_collar", "din967"), "iso7045": ("screw.raised_cheese_head", "iso7045"),
    "iso1207": ("screw.cheese_head", "iso1207"), "iso14580": ("screw.cheese_head", "iso14580"),
    "iso7048": ("screw.cheese_head", "iso7048"), "iso7379": ("screw.shoulder", "iso7379"),
    "iso2010": ("screw.raised_countersunk", "iso2010"), "iso7047": ("screw.raised_countersunk", "iso7047"),
    "iso14584": ("screw.raised_countersunk", "iso14584"),
    "iso4032": ("nut.hex", "iso4032"), "din934": ("nut.hex", "iso4032"), "iso4033": ("nut.hex", "iso4033"),
    "iso4035": ("nut.hex", "iso4035"), "iso4036": ("nut.thin_hex", "iso4036"), "din439": ("nut.thin_hex", "iso4036"),
    "din1587": ("nut.domed", "din1587"), "din557": ("nut.square", "din557"),
    "iso7089": ("washer.plain", "iso7089"), "din125": ("washer.plain", "iso7089"),
    "iso7091": ("washer.plain", "iso7091"), "iso7093": ("washer.plain", "iso7093"),
    "din9021": ("washer.plain", "iso7093"), "iso7094": ("washer.plain", "iso7094"),
    "iso7090": ("washer.chamfered", "iso7090"), "iso7092": ("washer.cheese_head", "iso7092"),
    "din6797": ("washer.lock_internal", "din6797"),
}
NUT_WORDS = [
    (r"heat[-\s]*set|threaded\s*insert|\binsert\b", "nut.heat_set", "ruthex"),
    (r"flange\s*nut", "nut.hex_flange", "din1665"),
    (r"dom(e|ed)\s*(cap\s*)?nut|acorn|cap\s*nut", "nut.domed", "din1587"),
    (r"square\s*nut", "nut.square", "din557"),
    (r"(thin|jam)\s*nut", "nut.thin_hex", "iso4036"),
    (r"(?<!t-)(?<!t )\bnut\b", "nut.hex", "iso4032"),  # not the "nut" of a T-nut
]
WASHER_WORDS = [
    (r"(tooth\s*)?lock\s*washer", "washer.lock_internal", "din6797"),
    (r"(large|fender|penny)\s*washer", "washer.plain", "iso7093"),
    (r"chamfered\s*washer", "washer.chamfered", "iso7090"),
    (r"\bwasher\b", "washer.plain", "iso7089"),
]


def _standard_in(text: str) -> tuple[str, str, str] | None:
    """(generator, type, matched text) for the first ISO / DIN number the tables know."""
    for m in re.finditer(r"\b(iso|din|en\s*iso)\s*(\d{2,5})(?:\s*[-/]\s*(\d))?\b", text):
        org = "iso" if "iso" in m.group(1) else "din"
        key = f"{org}{m.group(2)}" + (f"-{m.group(3)}" if m.group(3) else "")
        hit = STANDARDS.get(key) or STANDARDS.get(f"{org}{m.group(2)}")
        if hit:
            return hit[0], hit[1], m.group(0)
    return None


def _screws(text: str) -> list[dict]:
    out = []
    std = _standard_in(text)
    m = re.search(r"\b(m\d+(?:\.\d+)?)(?:\s*-\s*" + NUM + r")?\s*[x×*]\s*" + NUM + r"\b", text)
    imp = re.search(r"(#\d+|\d+/\d+)\s*-\s*(\d+)\s*[x×*]\s*" + NUM + r"\s*(\"|in(?:ch)?\b)?", text)
    if not (m or imp):
        return out
    if std and std[0].startswith("screw."):
        gen, stype, words = std[0], std[1], std[2]
    else:
        hit = next(((g, t, w.group(0)) for p, g, t in SCREW_WORDS if (w := re.search(p, text))), None)
        if hit is None and not re.search(r"\b(screws?|bolts?)\b", text):
            return out
        gen, stype, words = hit or ("screw.socket_head", "iso4762", "")
    if m:
        nominal = m.group(1).upper()
        size = _coarse(gen, nominal, m.group(2), stype)
        length = _f(m.group(3))
        matched = m.group(0)
    else:
        size = f"{imp.group(1)}-{imp.group(2)}"
        length = round(_f(imp.group(3)) * 25.4, 3)
        matched = imp.group(0)
        if not stype.startswith("asme"):  # inch sizes live in the class's ASME standard, if it has one
            cls = next(c for g, c, *_ in warehouse.SCREWS if g == gen)
            stype = next((t for t in sorted(cls.types()) if t.startswith("asme")), stype)
    if size is None:
        return out
    params = {"standard": stype, "size": size, "length": length}
    cls = next(c for g, c, *_ in warehouse.SCREWS if g == gen)
    try:
        lengths = warehouse._screw_lengths(gen, cls, stype, size)
    except Exception:  # sizes without complete data in bd_warehouse
        lengths = ()
    if lengths:  # snap inch lengths (25.4 mm) onto the table's values; refuse non-nominal lengths
        near = min(lengths, key=lambda L: abs(L - length))
        if abs(near - length) > 0.06:
            return out
        params["length"] = near
    label = f"{standard_label(stype)} {size} x {params['length']:g}"
    hit = _match(gen, params, label, f"{matched} {words}", 0.9 if words or std else 0.7)
    return [hit] if hit else out


def _nuts_and_washers(text: str) -> list[dict]:
    out = []
    m = re.search(r"\b(m\d+(?:\.\d+)?)\b(?!\s*[x×*]\s*\d)", text)
    if not m:
        return out
    nominal = m.group(1).upper()
    std = _standard_in(text)
    cands = []
    if std and std[0].startswith(("nut.", "washer.")):
        cands.append((std[0], std[1], std[2], 0.95))
    else:
        for p, g, t in NUT_WORDS + WASHER_WORDS:
            if w := re.search(p, text):
                cands.append((g, t, w.group(0), 0.85))
                break
    for gen, stype, words, score in cands:
        size = _coarse(gen, nominal, None, stype)
        if size is None and not std:  # the default standard (an insert maker) lacks this size: try the others
            cls = next(c for g, c, *_ in warehouse.NUTS + warehouse.WASHERS if g == gen)
            stype, size = next(((t, s) for t in sorted(cls.types()) if (s := _coarse(gen, nominal, None, t))),
                               (stype, None))
        if size is None:
            continue
        hit = _match(gen, {"standard": stype, "size": size}, f"{standard_label(stype)} {size}",
                     f"{m.group(0)} {words}", score)
        if hit:
            out.append(hit)
    return out


# ---------------------------------------------------------------- bearings

def _norm(s: str) -> str:
    return re.sub(r"[\s\-]", "", s.upper())


def _bearings(text: str) -> list[dict]:
    out = []
    tables = {g: _enum(g, "designation") for g in _REGISTRY if g.startswith("bearing.")}
    for m in re.finditer(r"\b((?:nj|nu|nup|n)\s*\d{3,4}|\d{3,5}(?:/\d+)?)(?:\s*[-\s]?\s*(2rs1?|2rsh|rs|2z|zz|z))?\b",
                         text):
        base, seal = m.group(1), (m.group(2) or "").lower()
        nb = _norm(base)
        full = _norm(m.group(0))
        if seal:  # an exact sealed designation (623-2Z) wins
            for des in tables.get("bearing.deep_groove_sealed", []):
                if _norm(des) == full:
                    hit = _match("bearing.deep_groove_sealed", {"designation": des}, des, m.group(0), 0.95)
                    if hit:
                        return [hit]
        if base in tables.get("bearing.deep_groove", []):
            s = "2RS" if seal.startswith(("2rs", "rs")) else "2Z" if seal in ("2z", "zz", "z") else "open"
            label = base + ("" if s == "open" else f"-{s}")
            hit = _match("bearing.deep_groove", {"designation": base, "seal": s}, label, m.group(0), 0.9)
            if hit:
                out.append(hit)
            continue
        for gen in ("bearing.angular_contact", "bearing.cylindrical_roller", "bearing.tapered_roller"):
            des = next((d for d in tables[gen] if _norm(d).startswith(nb) and not _norm(d)[len(nb):len(nb) + 1].isdigit()),
                       None)
            if des:
                hit = _match(gen, {"designation": des}, des, m.group(0), 0.85)
                if hit:
                    out.append(hit)
    return out


# ---------------------------------------------------------------- seals, rings, keys

def _o_rings(text: str) -> list[dict]:
    if not re.search(r"o[-\s]?rings?|as\s*568", text):
        return []
    if m := re.search(r"(?:as\s*568\s*[-\s]?|o[-\s]?rings?\s*(?:size\s*|dash\s*|-)?)(\d{3})\b", text):
        hit = _match("seal.o_ring", {"size": m.group(1)}, f"O-ring {m.group(1)}", m.group(0), 0.95)
        return [hit] if hit else []
    if m := re.search(NUM + r"\s*[x×*]\s*" + NUM, text):
        idia, cs = _f(m.group(1)), _f(m.group(2))
        best = None
        with open(DATA / "o-ring_parameters.csv", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                d1, w = float(row["iso3601:id"]), float(row["iso3601:w"])
                err = abs(d1 - idia) / max(idia, 1) + abs(w - cs) / max(cs, 0.5)
                if best is None or err < best[0]:
                    best = (err, row["Size"], d1, w)
        if best and best[0] < 0.08:
            hit = _match("seal.o_ring", {"size": best[1]}, f"O-ring {best[1]} ({best[2]:g} x {best[3]:g})",
                         m.group(0), 0.9 if best[0] < 0.02 else 0.7)
            return [hit] if hit else []
    return []


def _circlips(text: str) -> list[dict]:
    if not re.search(r"circlip|snap\s*ring|retaining\s*ring|din\s*47[12]|seeger", text):
        return []
    internal = bool(re.search(r"din\s*472|internal|\bbore\b|housing", text))
    m = re.search(r"din\s*47[12]\s*[-x]?\s*(\d+)", text) or re.search(r"\b(\d+)\s*mm\b", text) or \
        re.search(r"\b(\d{1,3})\b", text)
    if not m:
        return []
    gen = "ring.internal" if internal else "ring.external"
    hit = _match(gen, {"size": m.group(1)}, f"{'DIN 472' if internal else 'DIN 471'} {m.group(1)}", m.group(0), 0.9)
    return [hit] if hit else []


def _keys(text: str) -> list[dict]:
    m = re.search(r"(?:din\s*6885\s*)?(?:\b([ab])\s*)?(\d+)\s*[x×*]\s*(\d+)\s*[x×*]\s*" + NUM, text)
    if not m or not re.search(r"\bkeys?\b|din\s*6885|keyway", text):
        return []
    b, h, length = int(m.group(2)), int(m.group(3)), _f(m.group(4))
    with open(DATA / "shaft_key_parameters.csv", encoding="utf-8") as fh:
        shaft = next((int(float(r["Size"])) for r in csv.DictReader(fh)
                      if float(r["din6885:b"]) == b and float(r["din6885:h"]) == h), None)
    if shaft is None:
        return []
    form = (m.group(1) or "a").upper()
    hit = _match("key.parallel", {"shaft_d": shaft, "length": length, "form": form},
                 f"DIN 6885 {form} {b} x {h} x {length:g}", m.group(0), 0.9)
    return [hit] if hit else []


# ---------------------------------------------------------------- gears and V-slot

def _gears(text: str) -> list[dict]:
    if not re.search(r"gears?|\brack\b|pinion", text):
        return []
    mod = re.search(r"\bm(?:od(?:ule)?)?\s*=?\s*" + NUM + r"\b", text)
    teeth = re.search(r"\bz\s*=?\s*(\d+)\b|\b(\d+)\s*(?:t\b|teeth|tooth)", text)
    kind = "gear.rack" if re.search(r"\brack\b", text) else "gear.helical" if "helical" in text or "herringbone" in text \
        else "gear.bevel" if "bevel" in text else "gear.ring" if re.search(r"\bring\b|internal", text) else "gear.spur"
    params: dict[str, Any] = {}
    if mod:
        params["module"] = _f(mod.group(1))
    if teeth:
        params["teeth"] = int(teeth.group(1) or teeth.group(2))
    if kind == "gear.helical" and "herringbone" in text:
        params["herringbone"] = True
    if not params:
        return []
    label = f"{kind.split('.')[1]} gear" + (f" m{params['module']:g}" if "module" in params else "") + (
        f" z{params['teeth']}" if "teeth" in params else "")
    hit = _match(kind, params, label, " ".join(x.group(0) for x in (mod, teeth) if x), 0.85)
    return [hit] if hit else []


def _vslot(text: str) -> list[dict]:
    out = []
    if m := re.search(r"\b(2020|2040|2060|2080|4040|4080|c[-\s]?beam)\b(?:\s*(?:rail|extrusion|profile|v[-\s]?slot))?"
                      r"(?:\s*[x×*]\s*" + NUM + r"|\s+" + NUM + r"\s*mm)?", text):
        length = m.group(2) or m.group(3)
        if m.group(1).startswith("c"):  # the OpenBuilds C-beam profile, not the V-slot cell approximation
            params: dict[str, Any] = {"length": _f(length)} if length else {}
            hit = _match("openbuilds.c_beam_rail", params, "C-beam" + (f" x {_f(length):g} mm" if length else ""),
                         m.group(0), 0.85)
        else:
            params = {"profile": m.group(1), **({"length": _f(length)} if length else {})}
            hit = _match("vslot.rail", params, f"V-slot {m.group(1)}" + (f" x {_f(length):g} mm" if length else ""),
                         m.group(0), 0.85)
        if hit and not re.search(r"plate|mount|gantry", text) and (
                length or re.search(r"v[-\s]?slot|extrusion|rail|profile|c[-\s]?beam", text)):
            out.append(hit)
    if re.search(r"v[-\s]?(slot\s*)?wheel|mini\s*wheel", text):
        size = "mini" if "mini" in text else "standard"
        hit = _match("vslot.wheel", {"size": size}, f"V-slot {size} wheel", "wheel", 0.85)
        if hit:
            out.append(hit)
    if m := re.search(r"t[-\s]?nut\s*(m[345])\b|\b(m[345])\s*t[-\s]?nut", text):
        thread = (m.group(1) or m.group(2)).upper()
        hit = _match("vslot.tnut", {"thread": thread}, f"V-slot T-nut {thread}", m.group(0), 0.9)
        if hit:
            out.append(hit)
    return out


# ---------------------------------------------------------------- pipes, flanges, drives, OpenBuilds

# A pipe size never sticks to a letter ("M6" is a thread, not NPS 6).
_NPS = r"(?:nps\s*)?(?<![a-z\d./])(\d+\s+\d/\d|\d/\d|\d+(?:\.\d+)?)\s*(?:\"|in(?:ch(?:es)?)?\b)?"


def _nps_value(raw: str) -> str:
    raw = re.sub(r"\s+", " ", raw.strip())
    return {"0.5": "1/2", "0.75": "3/4", "1.25": "1 1/4", "1.5": "1 1/2", "2.5": "2 1/2"}.get(raw, raw.rstrip(".0") if
                                                                                              raw.endswith(".0") else raw)


def _pipes(text: str) -> list[dict]:
    if not re.search(r"\bpipe\b|\btube\b", text) or "flange" in text:
        return []
    m = re.search(_NPS + r"\s*(?:sch(?:edule)?\s*(\w+)|type\s*([klm])\b)?", text)
    if not m:
        return []
    nps = _nps_value(m.group(1))
    ident = (m.group(2) or m.group(3) or "").upper() or None
    mat = next((x for x in ("stainless", "copper", "pvc", "iron", "abs", "steel") if x in text),
               "copper" if ident in ("K", "L", "M") else "steel")
    ident = ident or ("40" if mat == "steel" else "40S" if mat == "stainless" else None)
    params: dict[str, Any] = {"nps": nps, "material": mat}
    if ident:
        params["identifier"] = ident
    if lm := re.search(r"[x×*]\s*" + NUM + r"\s*(mm|m\b)?|\b" + NUM + r"\s*(mm|m)\s*(?:long|length)?", text):
        val, unit = (lm.group(1), lm.group(2)) if lm.group(1) else (lm.group(3), lm.group(4))
        params["length"] = _f(val) * (1000 if unit == "m" else 1)
    from .mechanical import schedule_label

    label = f"NPS {nps} {schedule_label(ident) if ident else ''} {mat} pipe".replace("  ", " ")
    hit = _match("pipe.straight", params, label, m.group(0), 0.85)
    return [hit] if hit else []


FLANGE_WORDS = [(r"weld(?:ing)?[-\s]?neck|\bwn\b", "flange.weld_neck"), (r"slip[-\s]?on|\bso\b", "flange.slip_on"),
                (r"socket[-\s]?weld|\bsw\b", "flange.socket_weld"), (r"blind|\bblrf\b", "flange.blind"),
                (r"lap(?:ped)?[-\s]?(?:joint)?|\blj\b", "flange.lapped")]


def _flanges(text: str) -> list[dict]:
    if "flange" not in text or re.search(r"\b(nut|screw|bolt)s?\b", text):
        return []
    gen = next((g for p, g in FLANGE_WORDS if re.search(p, text)), "flange.weld_neck")
    m = re.search(_NPS, text)
    if not m:
        return []
    cls = re.search(r"(?:class|cl\.?)\s*(150|300)|\b(150|300)\s*(?:#|lb)", text)
    params: dict[str, Any] = {"nps": _nps_value(m.group(1))}
    if cls:
        params["flange_class"] = int(cls.group(1) or cls.group(2))
    for face in ("raised", "flat", "ring", "tongue", "groove", "male", "female"):
        if re.search(rf"\b{face}\b|\b{face[0]}f\b" if face in ("raised", "flat") else rf"\b{face}\b", text) and \
                gen != "flange.lapped":
            params["face_type"] = face.title()
            break
    label = f"{gen.split('.')[1].replace('_', '-')} flange NPS {params['nps']} class {params.get('flange_class', 150)}"
    hit = _match(gen, params, label, m.group(0), 0.9)
    return [hit] if hit else []


def _drives(text: str) -> list[dict]:
    out = []
    if "sprocket" in text:
        chain = re.search(r"(?:ansi\s*|#|no\.?\s*)?\b(25|35|40|41|50|60|80)\b(?!\s*(?:t\b|teeth|tooth))", text)
        teeth = re.search(r"\b(\d+)\s*(?:t\b|teeth|tooth)", text)
        params: dict[str, Any] = {}
        if chain:
            params["chain"] = chain.group(1)
        if teeth:
            params["teeth"] = int(teeth.group(1))
        if params:
            hit = _match("drive.sprocket", params, f"ANSI {params.get('chain', '40')} sprocket "
                         f"{params.get('teeth', 20)}T", "sprocket", 0.85)
            if hit:
                out.append(hit)
    if "worm" in text:
        gen = "drive.worm_wheel" if re.search(r"worm\s*(wheel|gear)", text) else "drive.worm"
        params = {}
        if mod := re.search(r"\bm(?:od(?:ule)?)?\s*=?\s*" + NUM + r"\b", text):
            params["module"] = _f(mod.group(1))
        if gen == "drive.worm_wheel" and (z := re.search(r"\bz\s*=?\s*(\d+)\b|\b(\d+)\s*(?:t\b|teeth)", text)):
            params["teeth"] = int(z.group(1) or z.group(2))
        if st := re.search(r"\b(\d)\s*[-\s]?start", text):
            params["starts"] = int(st.group(1))
        label = gen.split(".")[1].replace("_", " ") + (f" m{params['module']:g}" if "module" in params else "") + (
            f" z{params['teeth']}" if "teeth" in params else "") + (f" {params['starts']}-start" if "starts" in params
                                                                     else "")
        hit = _match(gen, params, label, "worm", 0.85)
        if hit:
            out.append(hit)
    return out


OPENBUILDS_WORDS = [
    (r"nema\s*-?\s*17", "openbuilds.stepper_motor", {"motor_type": "Nema17"}, "NEMA 17 stepper"),
    (r"nema\s*-?\s*23", "openbuilds.stepper_motor", {"motor_type": "Nema23"}, "NEMA 23 stepper"),
    (r"(?:x\s*-?\s*large|xl)\s*(?:c[-\s]?beam\s*)?gantry\s*plate", "openbuilds.cbeam_gantry_plate_xl", {},
     "C-beam gantry plate XL"),
    (r"gantry\s*plate", "openbuilds.cbeam_gantry_plate", {}, "C-beam gantry plate"),
    (r"end\s*mount", "openbuilds.cbeam_end_mount", {}, "C-beam end mount"),
    (r"riser\s*plate", "openbuilds.cbeam_riser_plate", {}, "C-beam riser plate"),
    (r"spacer\s*block", "openbuilds.spacer_block", {}, "spacer block"),
    (r"\bl[-\s]?bracket|angle\s*bracket", "openbuilds.l_bracket", {}, "L-bracket"),
    (r"eccentric\s*spacer", "openbuilds.eccentric_spacer", {}, "eccentric spacer"),
    (r"(?:anti[-\s]?backlash|lead\s*screw)\s*nut", "openbuilds.anti_backlash_nut_block", {}, "anti-backlash nut block"),
    (r"flex(?:ible)?\s*coupl", "openbuilds.flexible_coupler", {}, "flexible coupler"),
    (r"lock\s*collar|shaft\s*collar", "openbuilds.lock_collar", {}, "lock collar"),
    (r"xtreme", "openbuilds.xtreme_v_wheel", {}, "Xtreme solid V-wheel"),
    (r"shim", "openbuilds.shim_washer", {}, "shim washer"),
]


def _openbuilds(text: str) -> list[dict]:
    out = []
    for pat, gen, params, label in OPENBUILDS_WORDS:
        if m := re.search(pat, text):
            params = dict(params)
            if gen == "openbuilds.lock_collar" and (d := re.search(r"\b(5|8)\s*mm\b", text)):
                params["inside_diameter"] = f"{d.group(1)}mm"
            hit = _match(gen, params, label, m.group(0), 0.9)
            if hit:
                out.append(hit)
            break
    if m := re.search(r"\btr\s*8(?:\s*x\s*8)?\b|lead\s*screw(?!\s*nut)", text):
        params = {}
        if lm := re.search(r"(?:[x×*]|length)\s*" + NUM + r"(?!\s*x)|\b" + NUM + r"\s*mm", text):
            length = _f(lm.group(1) or lm.group(2))
            if length >= 20:
                params["length"] = length
        hit = _match("openbuilds.lead_screw", params, f"Tr8x8 lead screw" + (f" x {params['length']:g}" if params
                                                                               else ""), m.group(0), 0.85)
        if hit:
            out.append(hit)
    if m := re.search(r"alumin(?:i)?um\s*spacer\s*(\d+(?:\.\d+)?)\s*mm|spacer\s*(\d+(?:\.\d+)?)\s*mm", text):
        size = f"{m.group(1) or m.group(2)}mm"
        hit = _match("openbuilds.aluminium_spacer", {"length": size}, f"aluminium spacer {size}", m.group(0), 0.85)
        if hit:
            out.append(hit)
    return out


RULES = (_screws, _nuts_and_washers, _bearings, _o_rings, _circlips, _keys, _gears, _vslot, _pipes, _flanges,
         _drives, _openbuilds)


def lookup(text: str, limit: int = 5) -> list[dict]:
    """Catalog parts a typed name refers to, best first (empty when nothing is recognised)."""
    low = " " + text.lower().strip() + " "
    seen, out = set(), []
    for rule in RULES:
        for hit in rule(low):
            key = (hit["generator"], repr(sorted(hit["params"].items())))
            if key not in seen:
                seen.add(key)
                out.append(hit)
    out.sort(key=lambda h: -h["score"])
    return out[:limit]
