"""Feature tables for composable parts, and ports derived from features (spec 1.3 and 4.3 step 1).

A ``PartInfo`` is what the resolver knows about one pinned part: its bounding box and its
features, each with a frame (origin, outward/axis direction) and attributes. Two sources:

* **catalog** generators: every port becomes a feature (``port.<name>``) with aliases
  (``axis.main`` for the first axis port, ``face.end[0]``/``face.end[1]`` for ``end_a``/``end_b``).
* **native** parts (a model version's recipe): the recipe is built with the trusted adapter and
  hole walls are read from the persistent topology names (``<hole op>.wall[k]``), so a hole's
  identity is its recipe feature id plus index, exactly as spec 1.5 asks for native parts.

Both get the six bounding-box faces (``face.top``, ``face.bottom``, ``face.x_min`` ...): the
centre of each side of the part's box with its outward normal ([Assumption] P0 uses box sides,
not recognised planar faces).

Group order is deterministic: features of a group sort by the (z, y, x) of their origin,
rounded to 1 µm ([Assumption] spec 2.1).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from typing import Any

from ..contracts.ports import Port

Vec = tuple[float, float, float]
ND = 6
BOX_ROLES: dict[str, Vec] = {"top": (0, 0, 1), "bottom": (0, 0, -1), "x_min": (-1, 0, 0), "x_max": (1, 0, 0),
                             "y_min": (0, -1, 0), "y_max": (0, 1, 0)}
DRILL = {"top": (0, 0, -1), "bottom": (0, 0, 1), "x_min": (1, 0, 0), "x_max": (-1, 0, 0), "y_min": (0, 1, 0), "y_max": (0, -1, 0)}
_WALL = re.compile(r"^(?P<fid>[A-Za-z_][A-Za-z0-9_]*)\.wall\[(?P<k>\d+)\](?:#\d+)?$")
_INDEXED = re.compile(r"^(?P<group>.+)\[(?P<k>\d+)\]$")


def _r(v) -> Vec:
    return tuple(round(float(c), ND) + 0.0 for c in v)  # type: ignore[return-value]


def _dot(a, b) -> float:
    return sum(x * y for x, y in zip(a, b))


def _unit(v) -> Vec:
    n = math.sqrt(_dot(v, v))
    return _r(c / n for c in v)


def perpendicular_x(z: Vec) -> Vec:
    """A deterministic x axis for a frame with axis z: world X projected off z, or world Y when z is near X."""
    ref = (1.0, 0.0, 0.0) if abs(z[0]) < 0.9 else (0.0, 1.0, 0.0)
    d = _dot(ref, z)
    return _unit(tuple(r - d * c for r, c in zip(ref, z)))


@dataclass
class Feature:
    uid: str  # stable: "corner.wall[0]" (native hole), "port:face_a" (catalog port), "box:top"
    names: list[str]  # canonical first: "holes[0]", "face.top", "port.face_a", "axis.main", "face.end[0]"
    type: str  # hole | face | axis | port
    origin: Vec
    z: Vec  # outward normal (faces, hole entry) or axis direction
    x: Vec | None = None
    attrs: dict[str, Any] = field(default_factory=dict)
    port_name: str | None = None  # the part's own port this feature is (catalog)

    @property
    def name(self) -> str:
        return self.names[0]

    def to_dict(self) -> dict:
        return {"uid": self.uid, "name": self.name, "aliases": self.names[1:], "type": self.type, "origin": list(self.origin),
                "z": list(self.z), "attrs": self.attrs}


@dataclass
class PartInfo:
    key: str  # "native:<version id>" | "catalog:<generator>:<params hash>"
    source: str  # native | catalog
    label: str  # "plate", "ISO 4032 M6-1"
    slug: str
    item: str
    version: str
    bbox: tuple[Vec, Vec]
    features: list[Feature]
    generator: str | None = None
    params: dict[str, Any] | None = None
    recipe: dict | None = None
    meta: dict[str, Any] = field(default_factory=dict)  # standard, designation, thread, bore_d ...

    @property
    def size_mm(self) -> float:
        lo, hi = self.bbox
        return max(b - a for a, b in zip(lo, hi))

    @property
    def center(self) -> Vec:
        lo, hi = self.bbox
        return _r((a + b) / 2 for a, b in zip(lo, hi))

    def groups(self) -> dict[str, list[Feature]]:
        """{group name: ordered features} for every indexed alias (holes[k], face.end[k]) plus type groups."""
        out: dict[str, list[tuple[int, Feature]]] = {}
        for f in self.features:
            for n in f.names:
                m = _INDEXED.match(n)
                if m:
                    out.setdefault(m.group("group"), []).append((int(m.group("k")), f))
        groups = {g: [f for _, f in sorted(v, key=lambda t: t[0])] for g, v in out.items()}
        for kind, gname in (("face", "face"), ("axis", "axis"), ("port", "port")):
            members = [f for f in self.features if f.type == kind or (kind == "port" and f.port_name)]
            if members:
                groups.setdefault(gname, members)
        groups.setdefault("holes", [])
        return groups

    def by_name(self) -> dict[str, Feature]:
        return {n: f for f in self.features for n in f.names}

    def summary(self) -> dict:
        """What the composer and the card are told about the part: counts per group, never geometry to compute with."""
        g = self.groups()
        holes = g.get("holes", [])
        diam: dict[str, int] = {}
        for h in holes:
            k = f"{h.attrs['diameter']:g}"
            diam[k] = diam.get(k, 0) + 1
        return {"label": self.label, "source": self.source, "size_mm": round(self.size_mm, 3),
                "holes": len(holes), "hole_diameters_mm": diam,
                "features": sorted({f.name for f in self.features})[:60]}


def params_hash(params: dict | None) -> str:
    return "p:" + hashlib.sha256(json.dumps(params or {}, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _sort_key(f: Feature):
    return (round(f.origin[2], 3), round(f.origin[1], 3), round(f.origin[0], 3), f.uid)


def _box_features(bbox: tuple[Vec, Vec]) -> list[Feature]:
    lo, hi = bbox
    c = [(a + b) / 2 for a, b in zip(lo, hi)]
    size = [b - a for a, b in zip(lo, hi)]
    out = []
    for role, n in BOX_ROLES.items():
        axis = next(i for i in range(3) if n[i])
        o = list(c)
        o[axis] = hi[axis] if n[axis] > 0 else lo[axis]
        others = [size[i] for i in range(3) if i != axis]
        out.append(Feature(f"box:{role}", [f"face.{role}"], "face", _r(o), _r(n), perpendicular_x(_r(n)),
                           {"role": role, "area": round(others[0] * others[1], 6), "from": "bounding box"}))
    return out


# ---------------------------------------------------------------- catalog


def _thread_of(contract: dict, params: dict) -> str | None:
    t = contract.get("thread") or contract.get("bolt")
    if not t:
        size = str((params or {}).get("size") or "")
        m = re.match(r"^(M\d+(?:\.\d+)?)", size)
        t = m.group(1) if m else None
    if not t:
        return None
    m = re.match(r"^(M\d+(?:\.\d+)?)", str(t))
    return m.group(1) if m else None


def catalog_part(generator: str, params: dict, label: str | None = None, slug: str | None = None) -> PartInfo:
    from ..catalog import resolve

    part = resolve(generator, params)
    bb = part.solid.bounding_box()
    bbox = (_r((bb.min.X, bb.min.Y, bb.min.Z)), _r((bb.max.X, bb.max.Y, bb.max.Z)))
    feats: list[Feature] = []
    first_axis = True
    ab: dict[str, dict[str, Port]] = {}
    for name, p in part.ports.items():
        kind = str(p.contract.get("kind") or "")
        is_axis = kind == "axis" or name.endswith("_axis") or name == "axis"
        is_face = not is_axis and (kind == "face" or "face" in name or name.startswith("end"))
        names = [f"port.{name}"]
        if is_axis:
            stem = name[:-5] if name.endswith("_axis") else name
            if first_axis:
                names.append("axis.main")
                first_axis = False
            names.append(f"axis.{stem}")
        m = re.match(r"^(?P<stem>.+)_(?P<s>[ab])$", name)
        if m:
            ab.setdefault(m.group("stem"), {})[m.group("s")] = p
        elif is_face:
            stem = name[:-5] if name.endswith("_face") else name
            names.append(f"face.{stem}")
        feats.append(Feature(f"port:{name}", names, "axis" if is_axis else "face" if is_face else "port", _r(p.origin), _r(p.z),
                             _r(p.x), {"label": p.label, "contract": dict(p.contract), "port": name}, port_name=name))
    for stem, sides in ab.items():
        for k, s in enumerate(("a", "b")):
            if s in sides:
                f = next(f for f in feats if f.port_name == f"{stem}_{s}")
                f.names.append(f"face.{stem}[{k}]")
    feats += _box_features(bbox)
    meta = {k: part.meta.get(k) for k in ("standard", "size", "designation") if part.meta.get(k) is not None}
    thread = next((t for t in (_thread_of(p.contract, params) for p in part.ports.values()) if t), None)
    if thread:
        meta["thread"] = thread
    bores = sorted({float(p.contract["bore_d"]) for p in part.ports.values() if "bore_d" in p.contract})
    if bores:
        meta["bore_d"] = bores[0]
    return PartInfo(key=f"catalog:{generator}:{params_hash(params)}", source="catalog", label=label or generator, slug=slug or generator,
                    item=f"catalog:{generator}", version=params_hash(params), bbox=bbox, features=feats, generator=generator,
                    params=dict(params), meta=meta)


# ---------------------------------------------------------------- native


def native_part(recipe: dict, *, item: str, version: str, label: str, slug: str) -> PartInfo:
    """Features of a recipe part: holes from the persistent topology names, plus box faces."""
    from ..adapters import build123d_adapter as adapter
    from ..contracts.compile import parse_recipe
    from ..contracts.errors import ShilpaError
    from ..topology import naming as tn

    rec = parse_recipe(dict(recipe))
    res = adapter.build(rec)
    if not res.ok:
        raise ShilpaError(res.error.info.code, f"part {label!r} does not build: {res.error.info.message}")
    bb = res.shape.bounding_box()
    bbox = (_r((bb.min.X, bb.min.Y, bb.min.Z)), _r((bb.max.X, bb.max.Y, bb.max.Z)))
    hole_ops = {f.id: f for f in rec.features if f.op in ("hole", "corner_hole_pattern", "linear_hole_pattern", "polar_hole_pattern")}
    walls: dict[tuple[str, int], list] = {}
    for name, face in tn.output_table(res).faces:
        m = _WALL.match(name)
        if m and m.group("fid") in hole_ops:
            walls.setdefault((m.group("fid"), int(m.group("k"))), []).append(tn.face_signature(face))
    holes: list[Feature] = []
    for (fid, k), sigs in sorted(walls.items()):
        sig = sigs[0]
        if sig.geom != "CYLINDER" or sig.direction is None or sig.axis_point is None:
            continue
        d, p0 = sig.direction, sig.axis_point
        ts = []
        for s in sigs:
            lo, hi = s.bbox
            for corner in [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]:
                ts.append(_dot([c - q for c, q in zip(corner, p0)], d))
        t0, t1 = min(ts), max(ts)
        op = hole_ops[fid]
        drill = DRILL.get(op.face, (0, 0, -1)) if op.entry_face is None else tuple(-c for c in d)
        entry_t, exit_t = (t1, t0) if _dot(drill, d) < 0 else (t0, t1)
        entry = _r(q + entry_t * c for q, c in zip(p0, d))
        exit_ = _r(q + exit_t * c for q, c in zip(p0, d))
        out_entry = _unit(tuple(-c for c in drill))
        attrs = {"diameter": round(2 * sig.radius, 6), "depth": round(t1 - t0, 6),
                 "kind": "through" if op.mode == "through_all" else "blind", "hole_type": op.hole_type,
                 "entry": list(entry), "exit": list(exit_), "drill": list(_unit(drill)), "feature": fid, "index": k}
        if op.hole_type == "tapped" and op.standard_size:
            attrs["thread"] = op.standard_size
        holes.append(Feature(f"{fid}.wall[{k}]", [], "hole", entry, out_entry, perpendicular_x(out_entry), attrs))
    holes.sort(key=_sort_key)
    for i, h in enumerate(holes):
        h.names = [f"holes[{i}]"]
    feats = holes + _box_features(bbox)
    return PartInfo(key=f"native:{version}", source="native", label=label, slug=slug, item=item, version=version, bbox=bbox,
                    features=feats, recipe=dict(recipe))


# ---------------------------------------------------------------- ports from features


def _port_name(text: str) -> str:
    s = re.sub(r"[^a-z0-9_]+", "_", text.lower()).strip("_")
    return ("c_" + s)[:64]


def port_for(part: PartInfo, f: Feature, seat: str | None = None) -> Port:
    """The port a mate uses for feature ``f``. Catalog ports are used as they are; others are derived:

    * hole, seat ``entry``: origin at the entry centre, z out of the material there;
    * hole, seat ``exit``: origin at the exit centre, z out of the material there (along the drill);
    * hole, seat ``axis``: origin at the entry centre, z along the drill direction (into the material);
    * face: origin at the face centre, z the outward normal.
    """
    if f.port_name and seat in (None, "port"):
        p = next(f2 for f2 in part.features if f2.port_name == f.port_name)
        return Port(name=f.port_name, origin=p.origin, z=p.z, x=p.x or perpendicular_x(p.z), label=p.attrs.get("label", ""),
                    contract=dict(p.attrs.get("contract", {})))
    if f.type == "hole":
        k = f.names[0].split("[")[1].rstrip("]")
        drill = tuple(f.attrs["drill"])
        if seat == "exit":
            o, z = tuple(f.attrs["exit"]), drill
        elif seat == "axis":
            o, z = tuple(f.attrs["entry"]), drill
        else:
            seat = "entry"
            o, z = tuple(f.attrs["entry"]), tuple(-c for c in drill)
        z = _unit(z)
        contract = {"kind": "face" if seat != "axis" else "axis", "hole_d": f.attrs["diameter"]}
        return Port(name=_port_name(f"h{k}_{seat}"), origin=_r(o), z=z, x=perpendicular_x(z),
                    label=f"hole {k} {seat}", contract=contract)
    role = f.attrs.get("role") or f.name.replace(".", "_")
    return Port(name=_port_name(f"{f.type}_{role}" if f.type != "face" else role), origin=f.origin, z=_unit(f.z),
                x=f.x or perpendicular_x(_unit(f.z)), label=f.name, contract={"kind": f.type if f.type in ("face", "axis") else "face"})


def box_face(part: PartInfo, normal: Vec) -> Feature:
    """The bounding-box face whose outward normal is ``normal`` (a world axis direction)."""
    n = _r(normal)
    return next(f for f in part.features if f.uid.startswith("box:") and f.z == n)
