"""Persistent names for the faces and edges of every body a recipe builds (CADIR-style).

The heuristic ``EdgeSelector`` re-queries geometry ("perpendicular_z, top, outer,
expected 4") and breaks when an edit adds a hole or moves a face onto the queried
level. A persistent name instead says which feature made an entity and what it is
to that feature, so it means the same thing after any parameter edit:

    extrude_1.top                 end cap of an extrude (larger coordinate along the sketch normal)
    extrude_1.side.x_max          side face swept from the sketch edge on the +X side
    extrude_1.side.seg[3]         side face swept from profile segment 3
    hole_1.wall[2]                bore of the third hole of a hole series
    pocket_2.floor                floor of a pocket
    fillet_3.face[0]              fillet face rolled along the first selected edge
    mirror_1[1].hole_1.wall[0]    the mirror image of hole_1.wall[0]
    shell_1.inner.extrude_1.top   the shell's inner wall offset from extrude_1.top

Edges are named by their two faces, ``A&B`` (``extrude_1.top&extrude_1.side.x_max``).
Faces that share a name (a face split in two by a cut) get ``#k`` suffixes in centroid
order; the name without the suffix still selects the whole group. Edges that share a
face pair get ``~k`` the same way.

Names are assigned while building. Each operation names the faces it creates (roles
from the IR: a hole knows its walls, an extrude its caps and sides) and the faces of
its inputs carry their names through the operation by OCCT history: build123d 0.13
records ``BRepAlgoAPI`` / ``BRepFilletAPI`` Modified / Generated / deleted answers on
each result (``Shape._history``). Operations without a history record (offset /
shell, mirror copies, revolve and sweep primitives) fall back to signature matching:
same underlying surface, touching, or the image of a face under the operation.

Reference grammar (``NamedSelector.ref``):

    ref     := term ("," term)*                 union
    term    := faces | faces ".edges" | faces "&" faces
    faces   := a name or name prefix; "hole_1.wall" matches hole_1.wall[0], hole_1.wall[1]#0, ...

``A.edges`` is every edge bounding a face of A (cylinder seams excluded); ``A&B`` is the
edges shared by a face of A and a face of B.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import build123d as bd
from OCP.TopLoc import TopLoc_Location

from . import refs
from .refs import matches
from .signature import Signature, edge_signature, face_signature, sort_key

TOL = 1e-5  # mm, "lies on" tolerance for role classification


def key(shape) -> int:
    """Identity of a sub-shape, insensitive to orientation (TopTools_ShapeMapHasher semantics)."""
    return hash(getattr(shape, "wrapped", shape))


def tshape_key(shape) -> int:
    """Identity of the underlying TShape, ignoring placement (a moved copy shares it)."""
    w = getattr(shape, "wrapped", shape)
    return hash(w.Located(TopLoc_Location()))


class NamingError(ValueError):
    pass


def base_name(name: str) -> str:
    """The name without its ``#k`` disambiguation suffix."""
    return name.split("#", 1)[0]


# ---------------------------------------------------------------- the name table


@dataclass
class NameTable:
    """Names of one body state: every face, and every edge between two named faces."""

    feature_id: str
    shape: Any
    faces: list[tuple[str, bd.Face]]
    _face_by_key: dict[int, str] = field(default_factory=dict, repr=False)
    _edges: list | None = field(default=None, repr=False)

    @classmethod
    def from_faces(cls, fid: str, shape, names: dict[int, str]) -> "NameTable":
        """Disambiguate duplicate face names; edge names are derived on first use."""
        groups: dict[str, list] = {}
        for f in shape.faces():
            groups.setdefault(names.get(key(f)) or f"{fid}.face", []).append(f)
        out: list[tuple[str, bd.Face]] = []
        for name, fs in groups.items():
            if len(fs) == 1:
                out.append((name, fs[0]))
            else:
                fs.sort(key=lambda f: sort_key(face_signature(f)))
                out += [(f"{name}#{i}", f) for i, f in enumerate(fs)]
        return cls(fid, shape, sorted(out, key=lambda t: t[0]), {key(f): n for n, f in out})

    @property
    def edges(self) -> list[tuple[str, bd.Edge, tuple[str, str]]]:
        """(name, edge, (face name, face name)) for every edge between two named faces."""
        if self._edges is None:
            self._edges = self._edge_names()
        return self._edges

    def _edge_names(self):
        faces_of: dict[int, set] = {}
        edge_of: dict[int, bd.Edge] = {}
        for n, f in self.faces:
            for e in f.edges():
                faces_of.setdefault(key(e), set()).add(n)
                edge_of.setdefault(key(e), e)
        named: dict[str, list] = {}
        for k, fnames in faces_of.items():
            if len(fnames) != 2:
                continue  # a seam (one face on both sides) or a non-manifold edge
            pair = tuple(sorted(fnames))
            named.setdefault("&".join(pair), []).append((edge_of[k], pair))
        out = []
        for name, es in named.items():
            if len(es) == 1:
                out.append((name, es[0][0], es[0][1]))
            else:
                es.sort(key=lambda t: sort_key(edge_signature(t[0])))
                out += [(f"{name}~{i}", e, pair) for i, (e, pair) in enumerate(es)]
        return sorted(out, key=lambda t: t[0])

    # ------------------------------------------------------------ queries

    def face_name(self, face) -> str | None:
        return self._face_by_key.get(key(face))

    def names(self) -> dict[str, Signature]:
        out = {n: face_signature(f) for n, f in self.faces}
        out.update({n: edge_signature(e) for n, e, _ in self.edges})
        return out

    def match_faces(self, ref: str) -> list[tuple[str, bd.Face]]:
        return [(n, f) for n, f in self.faces if matches(n, ref.strip())]

    def resolve(self, ref: str) -> tuple[str, list]:
        """Resolve a reference to ("faces" | "edges", entities). Raises NamingError if a term matches nothing."""
        try:
            terms = refs.parse(ref)
            kind = refs.kind(ref)
        except refs.RefSyntaxError as exc:
            raise NamingError(str(exc)) from None
        found, seen = [], set()
        for term in terms:
            groups = []
            for fref in term.faces:
                names = {n for n, _ in self.match_faces(fref)}
                if not names:
                    raise NamingError(f"no face named {fref!r} on {self.feature_id!r}")
                groups.append(names)
            if term.kind == "faces":
                ents = [f for n, f in self.faces if n in groups[0]]
            elif term.kind == "edges_of":
                ents = [e for _, e, (p, q) in self.edges if p in groups[0] or q in groups[0]]
            else:
                a, b = groups
                ents = [e for n, e, (p, q) in self.edges if ((p in a and q in b) or (p in b and q in a))
                        and (term.index is None or n.endswith(f"~{term.index}"))]
            if not ents:
                raise NamingError(f"{'&'.join(term.faces)!r} matched no edges on {self.feature_id!r}")
            for e in ents:
                if key(e) not in seen:
                    seen.add(key(e))
                    found.append(e)
        return kind, found

    def names_of(self, entities) -> list[str]:
        """Names of resolved entities (faces or edges), in the given order."""
        edge_names = {key(e): n for n, e, _ in self.edges}
        return [self._face_by_key.get(key(x)) or edge_names.get(key(x)) or "?" for x in entities]


# ---------------------------------------------------------------- roles of sketch edges


def axis_role(d) -> str:
    """'x_max', 'y_min', ... for the global axis a direction points along most."""
    comps = (d.X, d.Y, d.Z)
    i = max(range(3), key=lambda k: abs(comps[k]))
    return f"{'xyz'[i]}_{'max' if comps[i] > 0 else 'min'}"


def _corner_role(d) -> str:
    comps = (d.X, d.Y, d.Z)
    i, j = sorted(sorted(range(3), key=lambda k: -abs(comps[k]))[:2])
    return "corner." + "_".join(f"{'xyz'[k]}_{'max' if comps[k] > 0 else 'min'}" for k in (i, j))


def sketch_roles(cf, sketch, plane: bd.Plane) -> list[tuple[str, bd.Vector]]:
    """(role, a point in the middle of the edge) for each boundary edge of a sketch."""
    edges = list(sketch.edges())
    v = cf.values
    center = plane.from_local_coords((v.get("center_x_ref", 0.0), v.get("center_y_ref", 0.0)))
    out = []
    if cf.op == "profile":
        mids = []
        for s in cf.segments:
            m = s.mid if s.kind == "arc" else ((s.p0[0] + s.p1[0]) / 2, (s.p0[1] + s.p1[1]) / 2)
            mids.append((f"seg[{s.source}]" if s.source is not None else "seg[close]", plane.from_local_coords(m)))
        return mids
    for e in edges:
        m = e.position_at(0.5)
        d = m - center
        gt = e.geom_type.name
        if cf.op == "circle":
            role = "outer" if abs(e.radius - v["diameter_ref"] / 2) < TOL else "inner"
        elif cf.op == "slot":
            a = math.radians(v.get("rotation_angle_ref", 0.0))
            u = plane.x_dir * math.cos(a) + plane.y_dir * math.sin(a)
            w = plane.z_dir.cross(u)
            role = f"end_{'pos' if d.dot(u) > 0 else 'neg'}" if gt == "CIRCLE" else f"flank_{'pos' if d.dot(w) > 0 else 'neg'}"
        elif gt == "LINE":
            role = axis_role(d)
        else:
            role = _corner_role(d)
        out.append((role, m))
    return out


# ---------------------------------------------------------------- propagation


def _same_surface(a: Signature, b: Signature, signed: bool) -> bool:
    if a.geom != b.geom:
        return False
    if a.geom == "PLANE":
        dot = sum(x * y for x, y in zip(a.direction, b.direction))
        if (dot < 1 - 1e-6) and (signed or dot > -1 + 1e-6):
            return False
        return abs(sum(n * (p - q) for n, p, q in zip(a.direction, a.center, b.center))) < TOL
    if a.geom in ("CYLINDER", "CONE", "TORUS", "SPHERE"):
        if abs((a.radius or 0) - (b.radius or 0)) > TOL or math.dist(a.axis_point or (0, 0, 0), b.axis_point or (0, 0, 0)) > TOL:
            return False
        return a.direction is None or abs(sum(x * y for x, y in zip(a.direction, b.direction))) > 1 - 1e-6
    return False


def _touching(f, g) -> bool:
    try:
        return f.distance_to(g) < TOL
    except Exception:
        return False


def inherit(out, history, seeds: list[tuple[Any, str]]) -> dict[int, str]:
    """Names of result faces that are input faces, untouched or modified (earlier seeds win)."""
    names: dict[int, str] = {}
    keep = {key(f) for f in out.faces()}
    for f, n in reversed(seeds):
        if key(f) in keep:
            names[key(f)] = n
        if history is not None:
            for m in history.modified(getattr(f, "wrapped", f)):
                if key(m) in keep:
                    names[key(m)] = n
    # An untouched face beats a modified one that happens to share its key (none in practice).
    return names


def coincident(out, names: dict[int, str], seeds: list[tuple[Any, str]], signed: bool = True) -> None:
    """Fallback: name unnamed result faces after an input face on the same surface that touches them."""
    seed_sigs = [(f, n, face_signature(f)) for f, n in seeds]
    for f in out.faces():
        if key(f) in names:
            continue
        sf = face_signature(f)
        for g, n, sg in seed_sigs:
            if _same_surface(sf, sg, signed) and _touching(f, g):
                names[key(f)] = n
                break


def leftovers(out, names: dict[int, str], fid: str, role: str = "face") -> None:
    """Name faces no rule claimed ``<fid>.<role>[k]`` in centroid order."""
    rest = [f for f in out.faces() if key(f) not in names]
    rest.sort(key=lambda f: sort_key(face_signature(f)))
    for i, f in enumerate(rest):
        names[key(f)] = f"{fid}.{role}[{i}]"


def seeds_of(table: NameTable | None) -> list[tuple[Any, str]]:
    return [(f, base_name(n)) for n, f in table.faces] if table else []


# ---------------------------------------------------------------- per-operation naming


def name_primitive(fid: str, part, roles: list[tuple[str, bd.Vector]], caps) -> dict[int, str]:
    """Faces of a fresh solid: caps by the caller's rule, sides by the sketch edge they were swept from."""
    names: dict[int, str] = {}
    for f in part.faces():
        cap = caps(f)
        if cap:
            names[key(f)] = f"{fid}.{cap}"
            continue
        bb = f.bounding_box()
        for role, m in roles:
            # Cheap box test first: a 400-segment profile would otherwise cost 400 distance queries per face.
            if not (bb.min.X - TOL <= m.X <= bb.max.X + TOL and bb.min.Y - TOL <= m.Y <= bb.max.Y + TOL
                    and bb.min.Z - TOL <= m.Z <= bb.max.Z + TOL):
                continue
            if f.distance_to(m) < TOL:
                names[key(f)] = f"{fid}.side.{role}"
                break
    return names


def extrude_caps(normal: bd.Vector, part):
    planes = [f for f in part.faces() if f.geom_type.name == "PLANE" and abs(abs(f.normal_at().dot(normal)) - 1) < 1e-9]
    levels = [f.center().dot(normal) for f in planes]
    mid = (min(levels) + max(levels)) / 2 if levels else 0.0
    cap_keys = {key(f): ("top" if f.center().dot(normal) > mid else "bottom") for f in planes}
    return lambda f: cap_keys.get(key(f))


def section_caps(part, first: list, last: list | None):
    """Start / end caps of a sweep, loft or partial revolve: planar faces matching a section."""
    def like(f, sections) -> bool:
        return any(abs(f.area - s.area) < TOL * max(1.0, s.area) and (f.center() - s.center()).length < TOL for s in sections)

    def cap(f):
        if f.geom_type.name != "PLANE":
            return None
        if like(f, first):
            return "start"
        if last is not None and like(f, last):
            return "end"
        return None
    return cap


def name_revolve_end(part, names: dict[int, str], fid: str) -> None:
    """A partial revolve's (or sweep's) far cap: the remaining planar face(s)."""
    for f in part.faces():
        if key(f) not in names and f.geom_type.name == "PLANE":
            names[key(f)] = f"{fid}.end"


def name_stepped_shaft(fid: str, part, radii: list[float], z_ends: list[float], z0: float, bore: float) -> dict[int, str]:
    names: dict[int, str] = {}
    for f in part.faces():
        gt, c = f.geom_type.name, f.center()
        if gt == "CYLINDER":
            r = f.radius
            if bore and abs(r - bore) < TOL:
                names[key(f)] = f"{fid}.bore"
                continue
            lo = f.bounding_box().min.Z
            for i, (ri, z_top) in enumerate(zip(radii, z_ends)):
                if abs(r - ri) < TOL and lo < z_top - TOL:
                    names[key(f)] = f"{fid}.section[{i}]"
                    break
        elif gt == "PLANE":
            if abs(c.Z - z0) < TOL:
                names[key(f)] = f"{fid}.bottom"
            elif abs(c.Z - z_ends[-1]) < TOL:
                names[key(f)] = f"{fid}.top"
            else:
                for i, z in enumerate(z_ends[:-1]):
                    if abs(c.Z - z) < TOL:
                        names[key(f)] = f"{fid}.shoulder[{i}]"
                        break
    leftovers(part, names, fid)
    return names


def hole_tool_roles(fid: str, k: int, tool, axis: int, sign: int, entry: float, h: dict) -> list[tuple[Any, str]]:
    """Roles of the faces of one hole's cutting tool (they become the hole's faces after the cut)."""
    out = []
    for f in tool.faces():
        gt = f.geom_type.name
        role = "face"
        if gt == "CYLINDER":
            role = "wall" if abs(f.radius - h["r"]) < TOL else "cbore_wall" if h.get("cbore_r") and abs(f.radius - h["cbore_r"]) < TOL else "face"
        elif gt == "CONE":
            role = "csk"
        elif gt == "PLANE":
            c = f.center()
            depth = (entry - (c.X, c.Y, c.Z)[axis]) * sign  # along the drilling direction from the entry face
            if depth < -TOL:
                role = "cap"
            elif h.get("cbore_depth") is not None and abs(depth - h["cbore_depth"]) < TOL:
                role = "cbore_floor"
            elif h.get("blind_depth") is not None and abs(depth - h["blind_depth"]) < TOL:
                role = "floor"
            else:
                role = "exit_cap"
        out.append((f, f"{fid}.{role}[{k}]"))
    return out


def pocket_tool_roles(fid: str, tool, floor_z: float, center: bd.Vector) -> list[tuple[Any, str]]:
    out = []
    for f in tool.faces():
        gt, c = f.geom_type.name, f.center()
        if gt == "PLANE" and abs(f.normal_at().Z) > 1 - 1e-9:
            role = "floor" if abs(c.Z - floor_z) < TOL else "cap"
        elif gt == "PLANE":
            role = "wall." + axis_role(f.normal_at())
        else:
            d = bd.Vector(c.X - center.X, c.Y - center.Y, 0)
            role = "wall." + _corner_role(d)
        out.append((f, f"{fid}.{role}"))
    return out


def image_names(fid: str, k: int, body_table: NameTable, image, point_map) -> list[tuple[Any, str]]:
    """Names for a transformed copy of a body: each image face after the body face it is the image of."""
    out = []
    src = [(n, f, face_signature(f)) for n, f in body_table.faces]
    for g in image.faces():
        sg = face_signature(g)
        best, best_d = None, math.inf
        for n, f, sf in src:
            if sf.geom != sg.geom or abs(sf.size - sg.size) > TOL * max(1.0, sf.size):
                continue
            d = (point_map(bd.Vector(*sf.center)) - bd.Vector(*sg.center)).length
            if d < best_d:
                best, best_d = n, d
        if best is not None and best_d < 1e-4:
            out.append((g, f"{fid}[{k}].{base_name(best)}"))
    return out


def name_shell(fid: str, body_table: NameTable, out, openings: list, t: float, inward: bool) -> dict[int, str]:
    """Shell (offset) faces have no kernel history: match them to the body's faces by surface."""
    names: dict[int, str] = {}
    open_keys = {key(f) for f in openings}
    src = [(f, base_name(n), face_signature(f)) for n, f in body_table.faces]
    for f in out.faces():
        sf = face_signature(f)
        for g, n, sg in src:
            if _same_surface(sf, sg, signed=False) and _touching(f, g):
                names[key(f)] = f"{fid}.rim.{n}" if key(g) in open_keys else n
                break
        else:
            for g, n, sg in src:
                if key(g) in open_keys or not _is_offset(sf, sg, t):
                    continue
                names[key(f)] = f"{fid}.{'inner' if inward else 'outer'}.{n}"
                break
    leftovers(out, names, fid)
    return names


def _is_offset(a: Signature, b: Signature, t: float) -> bool:
    """Is surface a the surface b offset by distance t (either side)?"""
    if a.geom != b.geom:
        return False
    if a.geom == "PLANE":
        if abs(abs(sum(x * y for x, y in zip(a.direction, b.direction))) - 1) > 1e-6:
            return False
        gap = abs(sum(n * (p - q) for n, p, q in zip(b.direction, a.center, b.center)))
        return abs(gap - t) < TOL
    if a.geom in ("CYLINDER", "SPHERE", "TORUS"):
        return (math.dist(a.axis_point or (0, 0, 0), b.axis_point or (0, 0, 0)) < TOL
                and abs(abs((a.radius or 0) - (b.radius or 0)) - t) < TOL)
    return False


def name_generated(fid: str, out, history, sources: list[tuple[Any, str]], names: dict[int, str], role: str = "face") -> None:
    """Faces a fillet or chamfer rolled along selected edges: ``<fid>.face[k]``, k in edge-name order."""
    if history is None:
        return
    keep = {key(f) for f in out.faces()}
    for k, (e, _) in enumerate(sorted(sources, key=lambda t: t[1])):
        for g in history.generated(e.wrapped):
            if key(g) in keep and key(g) not in names:
                names[key(g)] = f"{fid}.{role}[{k}]"


# ---------------------------------------------------------------- public API


def output_table(build) -> NameTable:
    """The name table of a build's output body (accepts a BuildResult or a NameTable)."""
    if isinstance(build, NameTable):
        return build
    names = getattr(build, "names", None) or {}
    table = names.get(build.compiled.output_id) if hasattr(build, "compiled") else None
    if table is None:
        raise NamingError("this build carries no topology names (did it fail, or was naming disabled?)")
    return table


def name_map(build) -> dict[str, Signature]:
    """{name: signature} for every named face and edge of a build's output."""
    return output_table(build).names()


def resolve(ref: str, shape, signatures: dict[str, Signature | dict] | None = None, tol: float = 1e-3) -> list:
    """Entities a reference names in ``shape``.

    ``shape`` may be a BuildResult or NameTable (names are exact, from the build history) or
    any build123d shape together with ``signatures`` from an earlier ``name_map``: then each
    named entity is found again by its signature (a STEP reimport or a re-tessellated copy of
    the same geometry; ``tol`` bounds the signature distance).
    """
    if isinstance(shape, NameTable) or hasattr(shape, "compiled"):
        return output_table(shape).resolve(ref)[1]
    if signatures is None:
        raise NamingError("resolving a name in a bare shape needs the signatures from name_map()")
    from .signature import distance

    sigs = {n: (s if isinstance(s, Signature) else Signature.from_dict(s)) for n, s in signatures.items()}
    face_names = [n for n, s in sigs.items() if s.kind == "face"]
    wanted: list[str] = []
    for term in refs.parse(ref):
        groups = [{n for n in face_names if matches(n, f)} for f in term.faces]
        if term.kind == "faces":
            wanted += sorted(groups[0])
            continue
        for n, s in sigs.items():
            if s.kind != "edge" or "&" not in n:
                continue
            p, q = n.split("~", 1)[0].split("&", 1)
            if term.kind == "edges_of":
                hit = p in groups[0] or q in groups[0]
            else:
                hit = (p in groups[0] and q in groups[1]) or (p in groups[1] and q in groups[0])
            if hit and (term.index is None or n.endswith(f"~{term.index}")):
                wanted.append(n)
    if not wanted:
        raise NamingError(f"{ref!r} names nothing in the given signatures")
    scale = max(shape.bounding_box().diagonal, 1e-9)
    cands = {"face": [(f, face_signature(f)) for f in shape.faces()], "edge": [(e, edge_signature(e)) for e in shape.edges()]}
    out, used = [], set()
    for n in wanted:
        s = sigs[n]
        best, best_d = None, math.inf
        for ent, cs in cands[s.kind]:
            if key(ent) in used:
                continue
            d = distance(s, cs, scale)
            if d < best_d:
                best, best_d = ent, d
        if best is None or best_d > tol:
            raise NamingError(f"{n!r} has no match in the shape (best signature distance {best_d:.3g})")
        used.add(key(best))
        out.append(best)
    return out
