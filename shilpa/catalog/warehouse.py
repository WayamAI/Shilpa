"""Standard parts from bd_warehouse's dimension tables (Apache-2.0, gumyr/bd_warehouse).

One generator per bd_warehouse class, data-driven: the standards a class
supports, the sizes each standard lists and the nominal lengths per size all
come from bd_warehouse's CSV tables, so nothing here retypes a dimension.

* Screws (``screw.*``): head bearing face at z = 0, shank down to z = -length
  (countersunk heads: the flush top at z = 0; set screws: the top end at z = 0).
  The shank is a plain cylinder at the nominal major diameter, as in the ISO
  4762 generator, so a screw in a simple nut or a nominal tapped hole touches
  it without overlapping; set and shoulder screws keep bd_warehouse's simple
  minor-diameter thread. ``length`` must be one of the standard's nominal
  lengths for that size (``auto`` picks the one nearest 2.5 d).
* Nuts (``nut.*``) and washers (``washer.*``): bearing face at z = 0 (normal -Z).
* Bearings (``bearing.*``): bd_warehouse models every ball and roller as its
  own solid; the catalog needs one solid per part for interference and mass,
  so these are the d x D x B envelope with the corner chamfer (like
  ``deep_groove_ball_bearing``), centred on z = 0, with the table's load
  ratings, speeds and mass. They are chosen by designation (``6204``,
  ``7204 BECBP``); ``bearing.deep_groove`` merges bd_warehouse's miniature
  range (3-10 mm bore) with Shilpa's 608 / 60xx / 62xx table (8-40 mm).
* Seals, rings, keys: ISO 3601 O-rings (torus centred on z = 0, with the
  static and dynamic gland sizes), DIN 471 / 472 circlips (z in [0, s]) and
  DIN 6885 parallel keys (z in [0, h], length along X).

Threads: metric sizes are written ``M6-1`` as in bd_warehouse; port contracts
use the ``M6x1`` designation of the other ISO fasteners so the two sets mate.
"""

from __future__ import annotations

import csv
import math
import re
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import bd_warehouse
import bd_warehouse.fastener as F
import build123d as bd
from bd_warehouse.o_rings import ORing
from bd_warehouse.retaining_ring import ExternalSnapRing, InternalSnapRing
from bd_warehouse.shaft_key import ShaftKey
from pydantic import Field, create_model, model_validator

from . import generator
from ..standards import table as standards_table
from ..contracts.errors import ErrorCode, ShilpaError
from ..contracts.ports import BuiltPart
from ._geom import CatalogParams, port

DATA = Path(bd_warehouse.__file__).resolve().parent / "data"


def _bad(name: str, message: str) -> ShilpaError:
    return ShilpaError(ErrorCode.INVALID_PARAMETER, f"{name}: {message}", feature_id=name)


def _one(obj) -> bd.Solid:
    solids = obj.solids()
    return solids[0] if len(solids) == 1 else obj


def thread_designation(size: str) -> str:
    """``M6-1`` -> ``M6x1`` (the ISO fasteners' contract form); imperial sizes unchanged."""
    m = re.fullmatch(r"M([\d.]+)-([\d.]+)", size)
    return f"M{m.group(1)}x{m.group(2)}" if m else size


def nominal_diameter(size: str) -> float | None:
    """Major diameter in mm from a bd_warehouse size: ``M6-1``, ``1/4-20``, ``#10-24``, ``M5-0.8-H4-D7``."""
    if m := re.match(r"M([\d.]+)", size):
        return float(m.group(1))
    if m := re.match(r"#(\d+)", size):
        return round((0.060 + 0.013 * int(m.group(1))) * 25.4, 3)
    if m := re.match(r"(\d+(?:\s+\d+)?/\d+|\d+(?:\.\d+)?)(?=-)", size):
        whole = sum(Fraction(p) for p in m.group(1).split())
        return round(float(whole) * 25.4, 3)
    return None


def standard_label(t: str) -> str:
    """bd_warehouse type key -> printed standard: ``iso7380_1`` -> ``ISO 7380-1``, ``asme_b_18.6.3`` -> ``ASME B18.6.3``."""
    if m := re.fullmatch(r"(iso|din)(\d+)(?:_(\d+))?", t):
        return f"{m.group(1).upper()} {m.group(2)}" + (f"-{m.group(3)}" if m.group(3) else "")
    if t.startswith("asme_"):
        return "ASME " + t[5:].replace("_", "").upper()
    return t


def _lit(values) -> Any:
    """A Literal over runtime values (pydantic writes it as a JSON-schema enum)."""
    return Literal[tuple(values)]  # type: ignore[valid-type]


def _all_sizes(cls) -> list[str]:
    out: list[str] = []
    for t in sorted(cls.types()):
        out += [s for s in cls.sizes(t) if s not in out]
    return out


def _default(options: list[str], prefer: tuple[str, ...]) -> str:
    exact = next((p for p in prefer if p in options), None)
    if exact:
        return exact
    for nominal in ("M6-", "M5-", "M6", "M5", "M4"):
        hit = next((o for o in options if o.startswith(nominal)), None)
        if hit:
            return hit
    return options[0]


def _check_size(gen: str, cls, standard: str, size: str) -> None:
    sizes = cls.sizes(standard)
    if size not in sizes:
        raise ValueError(f"{gen}: size {size} is not in {standard}; it lists {', '.join(sizes[:16])}"
                         + (" ..." if len(sizes) > 16 else ""))


def _standard_params(gen: str, cls, prefer_std: tuple[str, ...], prefer_size: tuple[str, ...], extra: dict,
                     material: str | None = "steel"):
    """A params model with ``standard`` and ``size`` enums from the class tables, checked together."""
    types = sorted(cls.types())
    sizes = _all_sizes(cls)
    std_default = _default(types, prefer_std)
    size_default = _default(cls.sizes(std_default), prefer_size)

    def check(self):
        _check_size(gen, cls, self.standard, self.size)
        return self

    model = create_model(
        f"{gen.replace('.', '_').title().replace('_', '')}Params",
        __base__=CatalogParams,
        __validators__={"_size_in_standard": model_validator(mode="after")(check)},
        standard=(_lit(types), std_default),
        size=(_lit(sizes), size_default),
        material=(str | None, material),
        **extra,
    )
    return model


# ---------------------------------------------------------------- screws

# generator, class, summary, head kind
SCREWS = [
    ("screw.socket_head", F.SocketHeadCapScrew, "Socket head cap screw", "head"),
    ("screw.button_head", F.ButtonHeadScrew, "Button head socket screw", "head"),
    ("screw.button_head_collar", F.ButtonHeadWithCollarScrew, "Button head socket screw with collar", "head"),
    ("screw.cheese_head", F.CheeseHeadScrew, "Cheese head screw", "head"),
    ("screw.countersunk", F.CounterSunkScrew, "Countersunk (flat) head screw", "csk"),
    ("screw.hex_head", F.HexHeadScrew, "Hex head bolt or screw", "head"),
    ("screw.hex_flange", F.HexHeadWithFlangeScrew, "Hex flange screw", "head"),
    ("screw.low_profile", F.LowProfileScrew, "Low-profile socket screw (OpenBuilds)", "head"),
    ("screw.pan_head", F.PanHeadScrew, "Pan head screw", "head"),
    ("screw.pan_head_collar", F.PanHeadWithCollarScrew, "Pan head screw with collar", "head"),
    ("screw.raised_cheese_head", F.RaisedCheeseHeadScrew, "Raised cheese head screw", "head"),
    ("screw.raised_countersunk", F.RaisedCounterSunkOvalHeadScrew, "Raised countersunk (oval) head screw", "raised_csk"),
    ("screw.set", F.SetScrew, "Hexagon socket set screw", "set"),
    ("screw.shoulder", F.ShoulderScrew, "Shoulder screw", "shoulder"),
]
PREFER_SCREW_STD = ("iso4762", "iso7380_1", "iso7380_2", "iso1207", "iso10642", "iso4017", "din1662", "OpenBuilds",
                    "iso14583", "din967", "iso7045", "iso2010", "iso4026", "iso7379")
PREFER_SIZE = ("M6-1", "M5-0.8", "M4-0.7", "M8-1.25")


@lru_cache(maxsize=512)
def _screw_lengths(gen: str, cls, standard: str, size: str) -> tuple[float, ...]:
    """The standard's nominal lengths for this size (bd_warehouse reports them on an instance)."""
    try:
        probe = cls(size, 20.0, standard, simple=True)
    except ValueError as exc:  # shoulder screws reject a probe length and name the valid ones
        if m := re.search(r"one of \[([^\]]+)\]", str(exc)):
            return tuple(sorted(round(float(x), 3) for x in m.group(1).split(",")))
        raise _bad(gen, str(exc)) from None
    except KeyError as exc:
        raise _bad(gen, f"bd_warehouse has no complete {standard} data for {size} ({exc})") from None
    return tuple(sorted({round(float(x), 3) for x in (probe.nominal_lengths or [])}))


def _make_screw(gen: str, cls, summary: str, kind: str):
    params = _standard_params(gen, cls, PREFER_SCREW_STD, PREFER_SIZE, {
        "length": (float | None, Field(None, gt=0, description="nominal length, mm; empty picks a standard length")),
    })
    standards = ", ".join(standard_label(t) for t in sorted(cls.types()))

    def build(p) -> BuiltPart:
        lengths = _screw_lengths(gen, cls, p.standard, p.size)
        d = nominal_diameter(p.size)
        if p.length is None:
            length = min(lengths, key=lambda L: abs(L - 2.5 * (d or 6))) if lengths else 20.0
        else:
            length = p.length
            if lengths and not any(abs(length - L) <= 0.01 for L in lengths):
                raise _bad(gen, f"{p.size} x {length:g} is not a nominal {p.standard} length; "
                                f"lengths: {', '.join(f'{L:g}' for L in lengths)}")
        try:
            s = cls(p.size, length, p.standard, simple=True)
        except (ValueError, KeyError) as exc:
            raise _bad(gen, str(exc)) from None
        solid = _one(s)
        thread = thread_designation(p.size)
        nominal = kind in ("head", "csk", "raised_csk") and d is not None
        if nominal:  # plain shank at the major diameter, as in the ISO 4762 generator
            shank = bd.Solid.make_cylinder(d / 2, length, bd.Plane.XY.offset(-length))
            solid = _one(solid.fuse(shank).clean())
        bb = solid.bounding_box()
        common = {"thread": thread, **({"nominal_d": d} if nominal else {})}
        ports = {
            "thread_axis": port("thread_axis", (0, 0, 0), (0, 0, -1), label="screw axis, pointing into the joint",
                                kind="axis", **common, length=length),
            "thread_tip": port("thread_tip", (0, 0, bb.min.Z), (0, 0, -1), label="thread end", kind="face", **common),
        }
        if kind in ("head", "shoulder"):
            ports["head_seat"] = port("head_seat", (0, 0, 0), (0, 0, -1), label="head underside, mates the clamped face",
                                      kind="face", **common, head_d=round(bb.size.X, 3))
        elif kind == "csk":
            ports["flush_top"] = port("flush_top", (0, 0, 0), (0, 0, 1), label="head top, flush with the countersunk face",
                                      kind="face", **common, head_d=round(bb.size.X, 3))
        elif kind == "raised_csk":
            ports["flush_plane"] = port("flush_plane", (0, 0, 0), (0, 0, 1), kind="point",
                                        label="countersink rim plane centre (the raised head sits above it)", **common)
        elif kind == "set":
            ports["drive_end"] = port("drive_end", (0, 0, 0), (0, 0, 1), label="socket end", kind="face", **common)
        if kind == "shoulder":
            ports["shoulder_end"] = port("shoulder_end", (0, 0, -length), (0, 0, -1), kind="face",
                                         label="shoulder end, clamps the thread side", **common)
        meta = {"standard": standard_label(p.standard), "size": p.size,
                "designation": f"{standard_label(p.standard)} {p.size} x {length:g}", "thread": thread,
                "length": length, "nominal_lengths": list(lengths), "head_d": round(bb.size.X, 3),
                "provenance": "bd_warehouse"}
        return BuiltPart(name=re.sub(r"[^a-z0-9]+", "_", f"{gen}_{p.size}_{length:g}".lower()).strip("_"),
                         solid=solid, ports=ports, source="catalog", meta=meta)

    generator(gen, params, f"{summary} ({standards})", standards)(build)


for _g, _c, _s, _k in SCREWS:
    _make_screw(_g, _c, _s, _k)


# ---------------------------------------------------------------- nuts and washers

NUTS = [
    ("nut.hex", F.HexNut, "Hex nut", True),
    ("nut.hex_flange", F.HexNutWithFlange, "Hex flange nut", False),
    ("nut.domed", F.DomedCapNut, "Domed cap nut", False),
    ("nut.square", F.SquareNut, "Square nut", True),
    ("nut.thin_hex", F.UnchamferedHexagonNut, "Thin hex nut, unchamfered", True),
    ("nut.heat_set", F.HeatSetNut, "Heat-set threaded insert for plastics", False),
]
WASHERS = [
    ("washer.plain", F.PlainWasher, "Plain washer", True),
    ("washer.chamfered", F.ChamferedWasher, "Plain washer, chamfered", True),
    ("washer.cheese_head", F.CheeseHeadWasher, "Washer for cheese head screws", True),
    ("washer.lock_internal", F.InternalToothLockWasher, "Internal tooth lock washer", False),
]


def _top_plane(solid) -> float | None:
    zs = [f.center().Z for f in solid.faces().filter_by(bd.GeomType.PLANE) if f.normal_at().Z > 0.999]
    return max(zs) if zs else None


def _make_nut(gen: str, cls, summary: str, reversible: bool):
    params = _standard_params(gen, cls, ("iso4032", "din1665", "din1587", "din557", "iso4036", "ruthex"),
                              ("M6-1", "M5-0.8"), {})
    standards = ", ".join(sorted(cls.types()))

    def build(p) -> BuiltPart:
        try:
            n = cls(p.size, p.standard, simple=True)
        except (ValueError, KeyError) as exc:
            raise _bad(gen, str(exc)) from None
        solid = _one(n)
        bb = solid.bounding_box()
        thread = thread_designation(p.size.split("-H")[0])
        ports = {
            "face_a": port("face_a", (0, 0, 0), (0, 0, -1), label="bearing face", kind="face", thread=thread),
            "thread_axis": port("thread_axis", (0, 0, 0), (0, 0, 1), label="nut axis", kind="axis", thread=thread),
        }
        top = _top_plane(solid)
        if reversible and top is not None:
            ports["face_b"] = port("face_b", (0, 0, top), (0, 0, 1), label="bearing face (reversible)", kind="face",
                                   thread=thread)
        elif gen == "nut.heat_set" and top is not None:
            ports["top"] = port("top", (0, 0, top), (0, 0, 1), label="top, flush with the part surface", kind="face",
                                thread=thread)
        meta = {"standard": standard_label(p.standard), "size": p.size,
                "designation": f"{standard_label(p.standard)} {p.size}", "thread": thread,
                "height": round(bb.size.Z, 3), "across": round(bb.size.Y, 3), "provenance": "bd_warehouse"}
        return BuiltPart(name=re.sub(r"[^a-z0-9]+", "_", f"{gen}_{p.size}".lower()).strip("_"), solid=solid,
                         ports=ports, source="catalog", meta=meta)

    generator(gen, params, f"{summary} ({standards})", standards)(build)


def _make_washer(gen: str, cls, summary: str, bore_cylinder: bool):
    params = _standard_params(gen, cls, ("iso7089", "iso7090", "iso7092", "din6797"), ("M6", "#6", "M5"), {})
    standards = ", ".join(sorted(cls.types()))

    def build(p) -> BuiltPart:
        try:
            w = cls(p.size, p.standard)
        except (ValueError, KeyError) as exc:
            raise _bad(gen, str(exc)) from None
        solid = _one(w)
        bb = solid.bounding_box()
        top = _top_plane(solid) or bb.max.Z
        data = getattr(w, "washer_data", {}) or {}
        d1 = data.get("d1")
        contract = {"for": p.size, "outer_d": round(bb.size.X, 3), "thickness": round(top, 3)}
        if bore_cylinder and d1:
            contract["inner_d"] = float(d1)
        ports = {
            "face_a": port("face_a", (0, 0, 0), (0, 0, -1), label="washer face", kind="face", **contract),
            "face_b": port("face_b", (0, 0, top), (0, 0, 1), label="washer face", kind="face", **contract),
            "bore_axis": port("bore_axis", (0, 0, 0), (0, 0, 1), label="washer axis", kind="axis", **contract),
        }
        meta = {"standard": standard_label(p.standard), "size": p.size,
                "designation": f"{standard_label(p.standard)} {p.size}", **contract,
                "provenance": "bd_warehouse"}
        return BuiltPart(name=re.sub(r"[^a-z0-9]+", "_", f"{gen}_{p.size}".lower()).strip("_"), solid=solid,
                         ports=ports, source="catalog", meta=meta)

    generator(gen, params, f"{summary} ({standards})", standards)(build)


for _g, _c, _s, _r in NUTS:
    _make_nut(_g, _c, _s, _r)
for _g, _c, _s, _b in WASHERS:
    _make_washer(_g, _c, _s, _b)


# ---------------------------------------------------------------- bearings (envelopes with catalogue data)

BEARINGS = [
    ("bearing.deep_groove", "single_row_deep_groove_ball_bearing_parameters.csv", "Deep-groove ball bearing", "B"),
    ("bearing.deep_groove_sealed", "single_row_capped_deep_groove_ball_bearing_parameters.csv",
     "Deep-groove ball bearing, sealed or shielded", "B"),
    ("bearing.angular_contact", "single_row_angular_contact_ball_bearing_parameters.csv",
     "Angular-contact ball bearing", "B"),
    ("bearing.cylindrical_roller", "single_row_cylindrical_roller_bearing_parameters.csv",
     "Cylindrical roller bearing", "B"),
    ("bearing.tapered_roller", "single_row_tapered_roller_bearing_parameters.csv", "Tapered roller bearing", "T"),
]


def _num(v: str | None) -> float | None:
    try:
        return float(v) if v not in (None, "", "–", "-") else None
    except ValueError:
        return None


@lru_cache(maxsize=None)
def bearing_table(filename: str) -> dict[str, dict[str, dict[str, str]]]:
    """size -> maker prefix (``SKT``, ``OpenBuilds``) -> column -> value, for the rows that maker fills."""
    out: dict[str, dict[str, dict[str, str]]] = {}
    with open(DATA / filename, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            size = row.pop("Size").strip()
            for key, value in row.items():
                if ":" not in key or value is None or not value.strip():
                    continue
                maker, col = key.split(":", 1)
                out.setdefault(size, {}).setdefault(maker.strip(), {})[col.strip()] = value.strip()
    return out


def bearing_records(gen: str, filename: str, width_col: str) -> dict[str, dict[str, Any]]:
    """designation -> envelope dimensions and catalogue data, from bd_warehouse's table (one record per maker
    row) and, for plain deep-groove bearings, Shilpa's 8-40 mm table (``shilpa/standards``); sorted by size."""
    recs: dict[str, dict[str, Any]] = {}
    for size, makers in bearing_table(filename).items():
        for maker, row in makers.items():
            d, D, B = _num(row.get("d")), _num(row.get("D")), _num(row.get(width_col))
            if None in (d, D, B):
                continue
            des = (row.get("Designation") or "").strip().lstrip("*").strip()
            if des in ("", "–", "-"):  # the tables write a missing designation as a dash
                des = f"{maker} {d:g}x{D:g}x{B:g}"
            if des in recs:
                des = f"{des} ({maker})"
            mass = _num(row.get("mass")) or _num(row.get("kg"))
            recs[des] = {"d": d, "D": D, "B": B, "r": _num(row.get("r12")) or 0.3,
                         "mass_g": round(mass * 1000, 1) if mass else None,
                         "C": _num(row.get("C")) if width_col == "B" else _num(row.get("Cl")),
                         "C0": _num(row.get("C0") or row.get("Cl0")), "Pu": _num(row.get("Pu")),
                         "speed_reference": _num(row.get("Speed-reference") or row.get("speed-reference")),
                         "speed_limit": _num(row.get("Speed-limit") or row.get("speed-limit")),
                         "maker": maker, "source": f"bd_warehouse {filename}"}
    if gen == "bearing.deep_groove":
        for row in standards_table("deep_groove_ball_bearings.csv"):
            recs.setdefault(row["designation"], {
                "d": float(row["d"]), "D": float(row["D"]), "B": float(row["B"]), "r": float(row["r_s_min"]),
                "mass_g": float(row["mass_g"]), "C": row["dynamic_load_kN"], "C0": None, "Pu": None,
                "speed_reference": None, "speed_limit": None, "maker": "SKF (rounded)",
                "source": "shilpa/standards/data/deep_groove_ball_bearings.csv"})
    return dict(sorted(recs.items(), key=lambda kv: (kv[1]["d"], kv[1]["D"], kv[1]["B"], kv[0])))


def _make_bearing(gen: str, filename: str, summary: str, width_col: str):
    recs = bearing_records(gen, filename, width_col)
    names = list(recs)
    prefer = next((n for n in ("6204", "7204 BECBP", "NJ 204 ECP", "30204 J2") if n in recs), None) or next(
        (n for n in names if recs[n]["d"] >= 20), names[-1])
    standard = "ISO 355" if gen == "bearing.tapered_roller" else "ISO 15"
    extra = {"seal": (Literal["open", "2RS", "2Z"], "open")} if gen == "bearing.deep_groove" else {}
    params = create_model(f"{gen.replace('.', '_').title().replace('_', '')}Params", __base__=CatalogParams,
                          designation=(_lit(names), prefer), material=(str | None, None), **extra)

    def build(p) -> BuiltPart:
        rec = recs[p.designation]
        d, D, B = rec["d"], rec["D"], rec["B"]
        plane = bd.Plane.XY.offset(-B / 2)
        solid = bd.Solid.make_cylinder(D / 2, B, plane).cut(bd.Solid.make_cylinder(d / 2, B, plane))
        r = min(rec["r"], (D - d) / 6, B / 4)
        solid = solid.chamfer(r, None, list(solid.edges().filter_by(bd.GeomType.CIRCLE))).solid()
        seal = getattr(p, "seal", "open")
        designation = p.designation + ("" if seal == "open" else f"-{seal}")
        dims = {"designation": designation, "d": d, "D": D, "B": B}
        ports = {
            "bore_axis": port("bore_axis", (0, 0, 0), (0, 0, 1), label="bore, fits a shaft", bore_d=d, fit="shaft",
                              **dims),
            "outer": port("outer", (0, 0, 0), (0, 0, 1), label="outside diameter, fits a housing", od=D,
                          fit="housing", **dims),
            "face_a": port("face_a", (0, 0, -B / 2), (0, 0, -1), label="side face", **dims),
            "face_b": port("face_b", (0, 0, B / 2), (0, 0, 1), label="side face", **dims),
        }
        meta = {"standard": standard, "size": f"{d:g}x{D:g}x{B:g}", **dims, "dynamic_load_kN": rec["C"],
                "static_load_kN": rec["C0"], "fatigue_limit_kN": rec["Pu"],
                "speed_reference_rpm": rec["speed_reference"], "speed_limit_rpm": rec["speed_limit"],
                "maker": rec["maker"], "provenance": rec["source"] + "; envelope geometry (no rolling elements)"}
        if rec["mass_g"]:
            meta.update(mass_g=rec["mass_g"], mass_basis="catalog")
        return BuiltPart(name=re.sub(r"[^a-z0-9]+", "_", f"{gen}_{designation}".lower()).strip("_"), solid=solid,
                         ports=ports, source="catalog", meta=meta)

    generator(gen, params, summary, standard, mass_basis="catalog")(build)


for _g, _f, _s, _w in BEARINGS:
    _make_bearing(_g, _f, _s, _w)


# ---------------------------------------------------------------- O-rings, circlips, keys

O_RING_SIZES = ORing.sizes()


class ORingParams(CatalogParams):
    size: _lit(O_RING_SIZES) = "210"  # ISO 3601 / AS568 dash number
    material: str | None = "rubber"


@generator("seal.o_ring", ORingParams, "O-ring with its gland (groove) sizes (ISO 3601)", "ISO 3601")
def o_ring(p: ORingParams) -> BuiltPart:
    o = ORing(p.size)
    solid = _one(o)
    cs, idia = float(o.width), float(o.inner_diameter)
    data = {"dash_number": p.size, "o_ring_id": idia, "cross_section": cs, "o_ring_od": round(idia + 2 * cs, 3)}
    # bd_warehouse fills gland_width / gland_depth when a gland profile is made: record all three designs.
    for key, make in (("static_axial", lambda: o.static_gland_profile(axial=True)),
                      ("static_radial", lambda: o.static_gland_profile(axial=False)),
                      ("dynamic", o.dynamic_gland_profile)):
        try:
            make()
        except ValueError:
            continue  # no gland data for this cross-section
        data[f"gland_{key}_width"] = round(float(o.gland_width), 4)
        data[f"gland_{key}_depth"] = round(float(o.gland_depth), 4)
    ports = {"ring_axis": port("ring_axis", (0, 0, 0), (0, 0, 1), label="ring axis, centred in its gland", kind="axis",
                               **data)}
    meta = {"standard": "ISO 3601", "size": f"{idia:g} x {cs:g}", "designation": f"O-ring {p.size} ({idia:g} x {cs:g})",
            **data, "provenance": "bd_warehouse"}
    return BuiltPart(name=f"o_ring_{p.size}", solid=solid, ports=ports, source="catalog", meta=meta)


def _ring_sizes(cls) -> list[str]:
    return [str(s) for s in cls.sizes()]


def _band_radius(solid, bb) -> float:
    """Radius along X at which the ring band is solid (circlips open on the Y side), for straddle points."""
    z = bb.min.Z + 0.5 * bb.size.Z
    for k in range(1, 40):
        r = bb.max.X - k * bb.max.X / 80
        if solid.is_inside(bd.Vector(r, 0, z)) and solid.is_inside(bd.Vector(-r, 0, z)):
            return round(r, 3)
    return round(bb.max.X * 0.95, 3)


def _make_circlip(gen: str, cls, summary: str, standard: str, fits: str):
    sizes = _ring_sizes(cls)
    params = create_model(f"{gen.replace('.', '_').title().replace('_', '')}Params", __base__=CatalogParams,
                          size=(_lit(sizes), "20" if "20" in sizes else sizes[0]), material=(str | None, "steel"))

    def build(p) -> BuiltPart:
        ring = cls(p.size)
        solid = _one(ring)
        bb = solid.bounding_box()
        data = {k: _num(str(v)) for k, v in (ring.ring_dict or {}).items() if _num(str(v)) is not None}
        contract = {fits: float(p.size), "thickness": round(bb.size.Z, 3), "groove_d": data.get("d2")}
        contract = {k: v for k, v in contract.items() if v is not None}
        band = _band_radius(solid, bb)
        ports = {
            "face_a": port("face_a", (0, 0, 0), (0, 0, -1), (0, 1, 0), label="ring face (centre of the open ring)",
                           kind="point", straddle=band, **contract),
            "face_b": port("face_b", (0, 0, bb.max.Z), (0, 0, 1), (0, 1, 0), label="ring face (centre of the open ring)",
                           kind="point", straddle=band, **contract),
            "ring_axis": port("ring_axis", (0, 0, 0), (0, 0, 1), label="ring axis, sits in the groove", kind="axis",
                              **contract),
        }
        meta = {"standard": standard, "size": p.size, "designation": f"{standard} {p.size}", **contract,
                "groove_width": data.get("m"), "provenance": "bd_warehouse"}
        return BuiltPart(name=f"{gen.replace('.', '_')}_{p.size}", solid=solid, ports=ports, source="catalog",
                         meta={k: v for k, v in meta.items() if v is not None})

    generator(gen, params, summary, standard)(build)


_make_circlip("ring.external", ExternalSnapRing, "External circlip for a shaft groove (DIN 471)", "DIN 471", "for_shaft")
_make_circlip("ring.internal", InternalSnapRing, "Internal circlip for a bore groove (DIN 472)", "DIN 472", "for_bore")

KEY_SHAFTS = sorted({int(float(s)) for s in ShaftKey.sizes()})


class KeyParams(CatalogParams):
    shaft_d: _lit(KEY_SHAFTS) = 20  # nominal shaft diameter, mm
    length: float | None = Field(None, gt=0, description="key length, mm; empty picks 1.5 x the shaft diameter")
    form: Literal["A", "B"] = "A"  # A: round ends, B: square ends
    material: str | None = "steel"


@generator("key.parallel", KeyParams, "Parallel key and its keyseat depths (DIN 6885)", "DIN 6885")
def parallel_key(p: KeyParams) -> BuiltPart:
    probe = ShaftKey(p.shaft_d, 100, p.form)
    width = float(probe.width)
    length = p.length if p.length is not None else max(math.ceil(1.5 * p.shaft_d), round(2 * width))
    try:
        k = ShaftKey(p.shaft_d, length, p.form)
    except (ValueError, KeyError) as exc:
        raise _bad("key.parallel", str(exc)) from None
    solid = _one(k)
    h = float(k.key_height)
    data = {k2: _num(str(v)) for k2, v in (k.key_dict or {}).items() if _num(str(v)) is not None}
    # bd_warehouse's table: t4 is the shaft keyseat depth, t2 the hub keyway depth (DIN 6885 t1 / t2).
    contract = {"key_b": width, "key_h": h, "shaft_depth_t1": data.get("t4"),
                "hub_depth_t2": data.get("t2")}
    contract = {k2: v for k2, v in contract.items() if v is not None}
    ports = {
        "seat": port("seat", (0, 0, 0), (0, 0, -1), label="bottom, sits in the shaft keyseat", kind="face",
                     x=(1, 0, 0), **contract),
        "top": port("top", (0, 0, h), (0, 0, 1), label="top, in the hub keyway", kind="face", **contract),
    }
    meta = {"standard": "DIN 6885", "size": f"{width:g} x {h:g} x {length:g}",
            "designation": f"DIN 6885 {p.form} {width:g} x {h:g} x {length:g}", "for_shaft_d": p.shaft_d,
            "length": length, **contract, "provenance": "bd_warehouse"}
    return BuiltPart(name=f"key_{p.form.lower()}_{width:g}x{h:g}x{length:g}".replace(".", "_"), solid=solid,
                     ports=ports, source="catalog", meta=meta)
