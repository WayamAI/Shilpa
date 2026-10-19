# Runs inside FreeCADCmd (FreeCAD's own Python). Self-contained: no Shilpa imports.
#
# Builds native, parametric PartDesign features from a lowered Shilpa plan, or applies a
# parameter edit to an existing FCStd. Job file path comes from SHILPA_FC_JOB; results
# are written as JSON to job["result"].
#
#   build: Params spreadsheet (one alias per IR parameter), one PartDesign Body,
#          sketches whose every vertex / radius is bound to expressions over Params,
#          Pad / Pocket / Revolution / Groove / Pipe / Helix / Loft / Thickness / Mirrored /
#          Linear and Polar Pattern / Fillet / Chamfer features, STEP export, FCStd save.
#   edit:  open FCStd, set Params cells, recompute, verify, export STEP, save, reopen, verify.

import json
import math
import os
import traceback

import FreeCAD as App
import Part
import Sketcher

JOB = json.load(open(os.environ["SHILPA_FC_JOB"], encoding="utf-8"))
RESULT = {"ok": False, "features": [], "error": None}
UNITS = {"length": "mm", "angle": "deg", "count": "", "ratio": ""}
V = App.Vector


def fail(msg, feature_id=None):
    raise RuntimeError(json.dumps({"message": msg, "feature_id": feature_id}))


# ------------------------------------------------------------------ parameters


def cell(value, unit):
    # The sheet reads a leading minus as text, so negative quantities are entered as formulas.
    text = f"{value!r} {unit}".strip()
    return "=" + text if value < 0 else text


def make_params(doc, params):
    sheet = doc.addObject("Spreadsheet::Sheet", "Params")
    for i, (name, p) in enumerate(params.items(), start=1):
        sheet.set(f"A{i}", name)
        sheet.set(f"B{i}", cell(p["value"], UNITS.get(p["kind"], "")))
        sheet.setAlias(f"B{i}", name)
    return sheet


# ------------------------------------------------------------------ sketches


def origin(body, role):
    return [f for f in body.Origin.OriginFeatures if f.Role == role][0]


def set_q(feat, prop, q):
    """Set a property to a value and, when parametric, bind it to its Params expression."""
    setattr(feat, prop, q["v"])
    if q.get("e"):
        feat.setExpression(prop, q["e"])


class SketchBuilder:
    def __init__(self, doc, body, sid, spec):
        self.sk = body.newObject("Sketcher::SketchObject", sid)
        plane = {"XY": "XY_Plane", "XZ": "XZ_Plane", "YZ": "YZ_Plane"}[spec.get("plane", "XY")]
        self.sk.AttachmentSupport = [(origin(body, plane), "")]
        self.sk.MapMode = "FlatFace"
        off = spec.get("offset")
        if off:
            self.sk.AttachmentOffset = App.Placement(V(0, 0, off["v"]), App.Rotation())
            if off.get("e"):
                self.sk.setExpression(".AttachmentOffset.Base.z", off["e"])
        # Geometry and constraints are collected and added in one call each (flush): the sketcher
        # re-solves on every single add, which made a 160-segment gear outline take minutes.
        self.geos, self.construction, self.cons = [], [], []

    def geo(self, g, construction=False):
        self.geos.append(g)
        if construction:
            self.construction.append(len(self.geos) - 1)
        return len(self.geos) - 1

    def _con(self, c, expr=None, name=None):
        self.cons.append((c, expr, name))
        return len(self.cons) - 1

    def flush(self):
        if self.geos:
            self.sk.addGeometry(self.geos, False)
        for i in self.construction:
            self.sk.setConstruction(i, True)
        if self.cons:
            self.sk.addConstraint([c for c, _, _ in self.cons])
        for idx, (_, expr, name) in enumerate(self.cons):
            if name:
                self.sk.renameConstraint(idx, name)
            if expr:
                self.sk.setExpression(f".Constraints.{name}" if name else f"Constraints[{idx}]", expr)

    def fix_point(self, geo, pos, x, y, tag):
        """Pin a vertex to expression-driven coordinates measured from the sketch origin."""
        for axis, q, ref_axis in (("X", x, -2), ("Y", y, -1)):
            if abs(q["v"]) < 1e-12 and not q.get("e"):
                self._con(Sketcher.Constraint("PointOnObject", geo, pos, ref_axis))  # on the opposite axis line
            else:
                self._con(Sketcher.Constraint(f"Distance{axis}", -1, 1, geo, pos, q["v"]), q.get("e"), f"{tag}_{axis.lower()}")

    def polygon(self, pts, tag):
        """Closed polygon with every vertex pinned (fully constrained, no redundancy)."""
        geos = []
        for i in range(len(pts)):
            a, b = pts[i], pts[(i + 1) % len(pts)]
            geos.append(self.geo(Part.LineSegment(V(a[0]["v"], a[1]["v"], 0), V(b[0]["v"], b[1]["v"], 0)), False))
        for i, g in enumerate(geos):
            self._con(Sketcher.Constraint("Coincident", g, 2, geos[(i + 1) % len(geos)], 1))
        for i, (x, y) in enumerate(pts):
            self.fix_point(geos[i], 1, x, y, f"{tag}_p{i}")
        return geos

    def rect(self, s, tag):
        cx, cy, w, h, r = s["cx"], s["cy"], s["w"], s["h"], s.get("r")

        def coord(c, size, sign, inset=None):
            # c + sign * (size / 2 - inset), as a value and (when parametric) an expression
            v = c["v"] + sign * (size["v"] / 2 - (inset["v"] if inset else 0))
            if not (c.get("e") or size.get("e") or (inset and inset.get("e"))):
                return {"v": v}
            half = f"({size.get('e') or repr(size['v'])}) / 2"
            if inset:
                half += f" - ({inset.get('e') or repr(inset['v'])})"
            return {"v": v, "e": combine(c, {"v": 0, "e": half}, sign)}

        corners = [(-1, -1), (1, -1), (1, 1), (-1, 1)]  # counter-clockwise
        if not r:
            self.polygon([(coord(cx, w, sx), coord(cy, h, sy)) for sx, sy in corners], tag)
            return
        # Rounded: each edge is a pinned segment inset by r at both ends; arcs of radius r join them.
        segs = []
        for i, (sx, sy) in enumerate(corners):
            nx, ny = corners[(i + 1) % 4]
            if sy == ny:  # horizontal edge
                segs.append(((coord(cx, w, sx, r), coord(cy, h, sy)), (coord(cx, w, nx, r), coord(cy, h, ny))))
            else:  # vertical edge
                segs.append(((coord(cx, w, sx), coord(cy, h, sy, r)), (coord(cx, w, nx), coord(cy, h, ny, r))))
        geos = []
        for i, (p1, p2) in enumerate(segs):
            g = self.geo(Part.LineSegment(V(p1[0]["v"], p1[1]["v"], 0), V(p2[0]["v"], p2[1]["v"], 0)), False)
            geos.append(g)
            self.fix_point(g, 1, p1[0], p1[1], f"{tag}_l{i}a")
            self.fix_point(g, 2, p2[0], p2[1], f"{tag}_l{i}b")
        for i in range(4):
            g1, g2 = geos[i], geos[(i + 1) % 4]
            end, start = segs[i][1], segs[(i + 1) % 4][0]
            sx, sy = corners[(i + 1) % 4]
            ccx = cx["v"] + sx * (w["v"] / 2 - r["v"])
            ccy = cy["v"] + sy * (h["v"] / 2 - r["v"])
            a1 = math.atan2(end[1]["v"] - ccy, end[0]["v"] - ccx)
            a2 = math.atan2(start[1]["v"] - ccy, start[0]["v"] - ccx)
            while a2 <= a1:
                a2 += 2 * math.pi
            arc = self.geo(Part.ArcOfCircle(Part.Circle(V(ccx, ccy, 0), V(0, 0, 1), r["v"]), a1, a2), False)
            self._con(Sketcher.Constraint("Coincident", arc, 1, g1, 2))
            self._con(Sketcher.Constraint("Coincident", arc, 2, g2, 1))
            self._con(Sketcher.Constraint("Radius", arc, r["v"]), r.get("e"), f"{tag}_r{i}")

    def circle(self, s, tag):
        g = self.geo(Part.Circle(V(s["cx"]["v"], s["cy"]["v"], 0), V(0, 0, 1), s["d"]["v"] / 2), False)
        self._con(Sketcher.Constraint("Diameter", g, s["d"]["v"]), s["d"].get("e"), f"{tag}_d")
        if abs(s["cx"]["v"]) < 1e-12 and abs(s["cy"]["v"]) < 1e-12 and not s["cx"].get("e") and not s["cy"].get("e"):
            self._con(Sketcher.Constraint("Coincident", g, 3, -1, 1))
        else:
            self.fix_point(g, 3, s["cx"], s["cy"], tag)

    def chain(self, s, tag):
        """Lines and arcs joined end to end (profiles, slots, sweep paths).

        Every vertex is pinned to its expressions; an arc is then fixed by a pinned through
        point (3-point arc), a radius constraint, or tangency to the previous segment.
        """
        segs = s["segs"]
        geos = []  # (geometry index, vertex index of the IR start, vertex index of the IR end)
        for seg in segs:
            p0, p1 = seg["p0"], seg["p1"]
            a, b = V(p0[0]["v"], p0[1]["v"], 0), V(p1[0]["v"], p1[1]["v"], 0)
            if seg["kind"] == "line":
                geos.append((self.geo(Part.LineSegment(a, b), False), 1, 2))
                continue
            c = V(seg["center"][0], seg["center"][1], 0)
            a0, a1 = math.atan2(a.y - c.y, a.x - c.x), math.atan2(b.y - c.y, b.x - c.x)
            if not seg["ccw"]:
                a0, a1 = a1, a0
            while a1 <= a0:
                a1 += 2 * math.pi
            g = self.geo(Part.ArcOfCircle(Part.Circle(c, V(0, 0, 1), seg["radius"]), a0, a1), False)
            # Sketcher arcs run counter-clockwise: a clockwise IR arc starts at the sketch arc's end vertex.
            geos.append((g, 1, 2) if seg["ccw"] else (g, 2, 1))
        n = len(geos)
        for i in range(n if s["closed"] else n - 1):
            (g1, _, e1), (g2, s2, _) = geos[i], geos[(i + 1) % n]
            kind = "Tangent" if segs[(i + 1) % n]["kind"] == "tangent" else "Coincident"
            self._con(Sketcher.Constraint(kind, g1, e1, g2, s2))
        for i, (g, st, _) in enumerate(geos):
            self.fix_point(g, st, segs[i]["p0"][0], segs[i]["p0"][1], f"{tag}_p{i}")
        if not s["closed"]:
            g, _, en = geos[-1]
            self.fix_point(g, en, segs[-1]["p1"][0], segs[-1]["p1"][1], f"{tag}_p{n}")
        for i, seg in enumerate(segs):
            g = geos[i][0]
            if seg["kind"] == "arc3":
                m = seg["mid"]
                pt = self.geo(Part.Point(V(m[0]["v"], m[1]["v"], 0)), True)
                self.fix_point(pt, 1, m[0], m[1], f"{tag}_m{i}")
                self._con(Sketcher.Constraint("PointOnObject", pt, 1, g))
            elif seg["kind"] == "radius":
                self._con(Sketcher.Constraint("Radius", g, seg["r"]["v"]), seg["r"].get("e"), f"{tag}_r{i}")

    def add(self, shape, tag):
        getattr(self, shape["type"])(shape, tag) if shape["type"] != "polyline" else self.polygon(shape["pts"], tag)


def make_sketch(doc, body, name, spec):
    sb = SketchBuilder(doc, body, name, spec)
    for i, shape in enumerate(spec["shapes"]):
        sb.add(shape, f"s{i}")
    sb.flush()
    sb.sk.Visibility = False
    return sb.sk


def combine(base, delta, sign):
    """Expression for base + sign * delta, or None when both are constants."""
    if not base.get("e") and not delta.get("e"):
        return None
    # Constant coordinates are lengths: FreeCAD rejects adding a unitless number to a length.
    d = delta.get("e") or f"{delta['v']!r} mm"
    op = "+" if sign > 0 else "-"
    if not base.get("e") and base["v"] == 0:
        return f"{'' if sign > 0 else '-'}({d})"
    b = base.get("e") or f"{base['v']!r} mm"
    return f"({b}) {op} ({d})"


# ------------------------------------------------------------------ edge selection (mirrors Shilpa's semantic selector)


def select_edges(shape, sel):
    bb = shape.BoundBox
    zt, zb = bb.ZMax, bb.ZMin
    names = []
    for i, e in enumerate(shape.Edges, start=1):
        kind = type(e.Curve).__name__
        is_line = kind in ("Line", "LineSegment")
        is_circle = kind == "Circle"
        if sel.get("curve") == "line" and not is_line:
            continue
        if sel.get("curve") == "circle" and not is_circle:
            continue
        dia = sel.get("diameter_value")
        if dia is not None and (not is_circle or abs(2 * e.Curve.Radius - dia) > 1e-6):
            continue
        p0, p1 = e.valueAt(e.FirstParameter), e.valueAt(e.LastParameter)
        mid = e.valueAt((e.FirstParameter + e.LastParameter) / 2)
        d = sel.get("direction", "any")
        if d == "parallel_z":
            if not is_line or abs(abs((p1 - p0).normalize().z) - 1) > 1e-6:
                continue
        elif d == "perpendicular_z":
            if max(abs(p0.z - mid.z), abs(p1.z - mid.z)) > 1e-6:
                continue
        zs = (p0.z, p1.z, mid.z)
        loc = sel.get("location", "any")
        if loc == "top" and not all(abs(z - zt) < 1e-6 for z in zs):
            continue
        if loc == "bottom" and not all(abs(z - zb) < 1e-6 for z in zs):
            continue
        if loc == "between" and (any(abs(z - zt) < 1e-6 for z in zs) or any(abs(z - zb) < 1e-6 for z in zs)):
            continue
        b = sel.get("boundary", "any")
        if b != "any":
            on_box = _circle_is_outer(shape, e) if is_circle else None
            if on_box is None:  # lines, and circles with no curved neighbour: on the bounding box
                on_box = min(abs(mid.x - bb.XMin), abs(mid.x - bb.XMax), abs(mid.y - bb.YMin), abs(mid.y - bb.YMax)) < 1e-6
                if is_circle and not on_box:
                    c = e.Curve.Center
                    on_box = abs(c.x - bb.Center.x) < 1e-6 and abs(e.Curve.Radius - bb.XLength / 2) < 1e-6
            if (b == "outer") != on_box:
                continue
        names.append(f"Edge{i}")
    return names


def _circle_is_outer(shape, edge):
    """Mirrors Shilpa's rule: a circle on a convex cylinder or cone is outside, on a concave one a hole."""
    c = edge.Curve.Center
    for f in shape.Faces:
        if type(f.Surface).__name__ not in ("Cylinder", "Cone"):
            continue
        if not any(edge.isSame(fe) for fe in f.Edges):
            continue
        p = f.CenterOfMass
        u, v = f.Surface.parameter(p)
        n = f.normalAt(u, v)
        rx, ry = p.x - c.x, p.y - c.y
        if abs(rx) + abs(ry) < 1e-9:
            continue
        return n.x * rx + n.y * ry > 0
    return None


# ------------------------------------------------------------------ face selection (mirrors Shilpa's side selector)

SIDES = {"top": (2, 1), "bottom": (2, -1), "x_max": (0, 1), "x_min": (0, -1), "y_max": (1, 1), "y_min": (1, -1)}


def select_faces(shape, side):
    """Planar faces lying on one side of the shape's bounding box."""
    axis, sign = SIDES[side]
    bb = shape.BoundBox
    at = (bb.XMax, bb.YMax, bb.ZMax)[axis] if sign > 0 else (bb.XMin, bb.YMin, bb.ZMin)[axis]
    names = []
    for i, f in enumerate(shape.Faces, start=1):
        if type(f.Surface).__name__ != "Plane":
            continue
        n, c = f.Surface.Axis, f.CenterOfMass
        if abs(abs((n.x, n.y, n.z)[axis]) - 1) < 1e-6 and abs((c.x, c.y, c.z)[axis] - at) < 1e-4:
            names.append(f"Face{i}")
    return names


# ------------------------------------------------------------------ named references (signatures from the build123d build)

CURVES = {"LINE": ("Line", "LineSegment"), "CIRCLE": ("Circle",)}
SURFACES = {"PLANE": ("Plane",), "CYLINDER": ("Cylinder",), "CONE": ("Cone",), "SPHERE": ("Sphere",), "TORUS": ("Toroid",)}


def select_by_signature(shape, sigs, kind, tol=1e-4):
    """Subelement names whose type, centre of mass and size match each signature."""
    items = shape.Edges if kind == "edge" else shape.Faces
    prefix = "Edge" if kind == "edge" else "Face"
    names = []
    for sig in sigs:
        types = (CURVES if kind == "edge" else SURFACES).get(sig["geom"])
        best, best_d = None, None
        for i, it in enumerate(items, start=1):
            geo = it.Curve if kind == "edge" else it.Surface
            if types and type(geo).__name__ not in types:
                continue
            size = it.Length if kind == "edge" else it.Area
            if abs(size - sig["size"]) > tol * max(1.0, sig["size"]):
                continue
            c = it.CenterOfMass
            d = ((c.x - sig["center"][0]) ** 2 + (c.y - sig["center"][1]) ** 2 + (c.z - sig["center"][2]) ** 2) ** 0.5
            if best_d is None or d < best_d:
                best, best_d = f"{prefix}{i}", d
        if best is None or best_d > 1e-3 or best in names:
            fail(f"no {kind} in the FreeCAD model matches the named reference's {sig['geom']} at {sig['center']}")
        names.append(best)
    return names


def mirror_plane(body, fid, plane, off):
    """Origin plane, or a datum plane moved along the plane's own axis (XZ's normal is -Y)."""
    base = origin(body, {"XY": "XY_Plane", "XZ": "XZ_Plane", "YZ": "YZ_Plane"}[plane])
    if not off or (abs(off["v"]) < 1e-12 and not off.get("e")):
        return (base, [""])
    sign = -1 if plane == "XZ" else 1
    dp = body.newObject("PartDesign::Plane", f"{fid}_plane")
    dp.AttachmentSupport = [(base, "")]
    dp.MapMode = "FlatFace"
    dp.AttachmentOffset = App.Placement(V(0, 0, sign * off["v"]), App.Rotation())
    if off.get("e"):
        dp.setExpression(".AttachmentOffset.Base.z", f"{'-' if sign < 0 else ''}({off['e']})")
    dp.Visibility = False
    return (dp, [""])


def qexpr(q, unit="mm"):
    return q.get("e") or f"{q['v']!r} {unit}".strip()


# ------------------------------------------------------------------ build

SKETCHED = ("Pad", "Pocket", "Revolution", "Groove", "AdditivePipe", "SubtractivePipe", "AdditiveHelix", "SubtractiveHelix")
LOFTS = ("AdditiveLoft", "SubtractiveLoft")
TRANSFORMS = ("Mirrored", "LinearPattern", "PolarPattern")


def build_sketched(doc, body, op, fid, kind):
    sk = make_sketch(doc, body, f"{fid}_sketch", op["sketch"])
    spine = make_sketch(doc, body, f"{fid}_spine", op["spine"]) if "spine" in op else None
    doc.recompute()
    feat = body.newObject(f"PartDesign::{kind}", fid)
    feat.Profile = sk
    if kind in ("Revolution", "Groove"):
        feat.ReferenceAxis = (sk, [op.get("axis", "V_Axis")])
        set_q(feat, "Angle", op.get("angle") or {"v": 360.0})
    elif kind in ("AdditivePipe", "SubtractivePipe"):
        feat.Spine = (spine, [f"Edge{i}" for i in range(1, len(spine.Shape.Edges) + 1)])
    elif kind in ("AdditiveHelix", "SubtractiveHelix"):
        feat.ReferenceAxis = (sk, ["V_Axis"])  # the XZ sketch's vertical axis is global +Z
        feat.Mode = "pitch-height-angle"
        set_q(feat, "Pitch", op["pitch"])
        set_q(feat, "Height", op["height"])
        feat.LeftHanded = bool(op.get("left_handed"))
    elif op.get("through_all"):
        feat.Type = "ThroughAll"
        set_symmetric(feat, True)
    else:
        feat.Type = "Length"
        set_q(feat, "Length", op["length"])
        set_symmetric(feat, bool(op.get("midplane")))
        feat.Reversed = bool(op.get("reversed"))
        if op.get("taper"):
            set_q(feat, "TaperAngle", op["taper"])
    return feat


def build_transform(doc, body, op, fid, kind):
    feat = body.newObject(f"PartDesign::{kind}", fid)
    if op.get("originals"):
        feat.TransformMode = "Features"
        feat.Originals = [doc.getObject(n) for n in op["originals"]]
    else:
        feat.TransformMode = "Whole shape"
    if kind == "Mirrored":
        feat.MirrorPlane = mirror_plane(body, fid, op["plane"], op.get("offset"))
    elif kind == "LinearPattern":
        feat.Direction = (origin(body, f"{op['direction']}_Axis"), [""])
        feat.Mode = "Extent"
        n, s = op["count"], op["spacing"]
        set_q(feat, "Length", {"v": (n["v"] - 1) * s["v"], **({"e": f"(({qexpr(n, '')}) - 1) * ({qexpr(s)})"} if n.get("e") or s.get("e") else {})})
        set_q(feat, "Occurrences", {"v": int(n["v"]), **({"e": n["e"]} if n.get("e") else {})})
    else:
        feat.Axis = (origin(body, f"{op['axis']}_Axis"), [""])
        feat.Mode = "Extent"
        set_q(feat, "Angle", op["angle"])
        set_q(feat, "Occurrences", {"v": int(op["count"]["v"]), **({"e": op["count"]["e"]} if op["count"].get("e") else {})})
    # A whole-shape transform has no Originals, which the Body does not count as a solid feature,
    # so it would not become the Tip and later features would skip it.
    body.Tip = feat
    return feat


def build():
    doc = App.newDocument("ShilpaModel")
    make_params(doc, JOB["params"])
    body = doc.addObject("PartDesign::Body", "ShilpaBody")
    tip = None
    for op in JOB["ops"]:
        fid, kind = op["id"], op["pd"]
        try:
            if kind in SKETCHED:
                feat = build_sketched(doc, body, op, fid, kind)
            elif kind in LOFTS:
                secs = [make_sketch(doc, body, f"{fid}_sec{i}", s) for i, s in enumerate(op["sections"])]
                doc.recompute()
                feat = body.newObject(f"PartDesign::{kind}", fid)
                feat.Profile = secs[0]
                feat.Sections = secs[1:]
                feat.Ruled = bool(op.get("ruled"))
            elif kind == "Thickness":
                doc.recompute()
                faces = select_by_signature(tip.Shape, op["face_signatures"], "face") if op.get("face_signatures") else []
                for sel in op["faces"]:
                    found = select_faces(tip.Shape, sel["side"])
                    if len(found) != sel["expected_count"]:
                        fail(f"face selector {sel['side']} matched {len(found)} faces, expected {sel['expected_count']}", fid)
                    faces += found
                feat = body.newObject("PartDesign::Thickness", fid)
                feat.Base = (tip, faces)
                feat.Mode = "Skin"
                feat.Join = "Intersection"
                feat.Reversed = bool(op["inward"])  # Reversed means "thickness inwards" in PartDesign
                set_q(feat, "Value", op["size"])
            elif kind in TRANSFORMS:
                doc.recompute()
                feat = build_transform(doc, body, op, fid, kind)
            elif kind in ("Fillet", "Chamfer"):
                doc.recompute()
                sel = op["selector"]
                edges = select_by_signature(tip.Shape, sel["signatures"], "edge") if sel.get("signatures") else select_edges(tip.Shape, sel)
                if len(edges) != op["selector"]["expected_count"]:
                    fail(f"edge selector matched {len(edges)} edges, expected {op['selector']['expected_count']}", fid)
                feat = body.newObject(f"PartDesign::{kind}", fid)
                feat.Base = (tip, edges)
                prop = "Radius" if kind == "Fillet" else "Size"
                setattr(feat, prop, op["size"]["v"])
                if op["size"].get("e"):
                    feat.setExpression(prop, op["size"]["e"])
            else:
                fail(f"unknown lowered operation {kind}", fid)
            for name, value in (op.get("meta") or {}).items():
                # Cosmetic facts (e.g. a tapped hole's thread spec) travel with the feature.
                feat.addProperty("App::PropertyString", name, "Shilpa", "Shilpa metadata")
                setattr(feat, name, value)
            doc.recompute()
            check_feature(feat, fid)
            tip = feat
            RESULT["features"].append({"id": fid, "pd": kind, "status": "ok", "volume": feat.Shape.Volume})
        except Exception as exc:
            RESULT["features"].append({"id": fid, "pd": kind, "status": "failed", "error": str(exc)})
            raise
    finish(doc, body, JOB["out_fcstd"], JOB["out_step"])


def set_symmetric(feat, on):
    # FreeCAD 1.1 replaced Midplane with SideType; keep older versions working.
    if hasattr(feat, "SideType"):
        feat.SideType = "Symmetric" if on else "One side"
    else:
        feat.Midplane = on


def check_feature(feat, fid):
    if "Touched" in feat.State:
        feat.Document.recompute()  # "Touched" only means a recompute is pending
    state = [s for s in feat.State if s in ("Invalid", "Error")]
    if state or not feat.isValid():
        fail(f"FreeCAD feature {feat.Name} is {state or 'invalid'}", fid)
    if feat.Shape.isNull() or not feat.Shape.isValid() or len(feat.Shape.Solids) != 1:
        fail(f"FreeCAD feature {feat.Name} did not produce one valid solid", fid)


def finish(doc, body, out_fcstd, out_step):
    doc.recompute()
    bad = [o.Name for o in doc.Objects if "Invalid" in o.State or "Error" in o.State]
    if bad:
        fail(f"objects failed to recompute: {bad}")
    shape = body.Shape
    # Which subelements each selection holds after the (re)compute: the edit check compares them.
    RESULT["selections"] = [{"id": f.Name, "subs": list(f.Base[1])} for f in body.Group
                            if f.TypeId in ("PartDesign::Fillet", "PartDesign::Chamfer", "PartDesign::Thickness")]
    shape.exportStep(out_step)
    doc.saveAs(out_fcstd)
    bb = shape.BoundBox
    RESULT.update(ok=True, volume=shape.Volume, bbox=[bb.XLength, bb.YLength, bb.ZLength],
                  solids=len(shape.Solids), valid=shape.isValid(), freecad=".".join(App.Version()[:3]))


# ------------------------------------------------------------------ edit


def edit():
    doc = App.openDocument(JOB["fcstd"])
    sheet = doc.getObject("Params")
    for name, value in JOB["set"].items():
        cell_name = sheet.getCellFromAlias(name)
        if not cell_name:
            fail(f"parameter {name!r} is not in the Params sheet")
        old = sheet.get(name)
        unit = str(old).split(" ", 1)[1] if " " in str(old) else ""
        sheet.set(cell_name, cell(value, unit))
    doc.recompute()
    body = doc.getObject("ShilpaBody")
    for f in body.Group:
        if f.TypeId.startswith("PartDesign::") and f.TypeId != "PartDesign::Body":
            check_feature(f, f.Name) if f.TypeId not in ("PartDesign::Plane", "PartDesign::Line") else None
    finish(doc, body, JOB["out_fcstd"], JOB["out_step"])
    App.closeDocument(doc.Name)
    # Reopen the saved file and recompute from scratch: the edit must survive a round trip.
    doc2 = App.openDocument(JOB["out_fcstd"])
    for o in doc2.Objects:
        o.touch()
    doc2.recompute()
    bad = [o.Name for o in doc2.Objects if "Invalid" in o.State or "Error" in o.State]
    RESULT["reopen_ok"] = not bad and doc2.getObject("ShilpaBody").Shape.isValid()
    RESULT["reopen_volume"] = doc2.getObject("ShilpaBody").Shape.Volume
    if bad:
        fail(f"reopened document failed to recompute: {bad}")


try:
    build() if JOB["mode"] == "build" else edit()
except Exception as exc:
    msg = str(exc)
    try:
        RESULT["error"] = json.loads(msg)
    except Exception:
        RESULT["error"] = {"message": msg, "trace": traceback.format_exc()[-2000:]}
finally:
    with open(JOB["result"], "w", encoding="utf-8") as fh:
        json.dump(RESULT, fh, indent=2, default=str)
