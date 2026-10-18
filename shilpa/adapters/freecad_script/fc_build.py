# Runs inside FreeCADCmd (FreeCAD's own Python). Self-contained: no Shilpa imports.
#
# Builds native, parametric PartDesign features from a lowered Shilpa plan, or applies a
# parameter edit to an existing FCStd. Job file path comes from SHILPA_FC_JOB; results
# are written as JSON to job["result"].
#
#   build: Params spreadsheet (one alias per IR parameter), one PartDesign Body,
#          sketches whose every vertex / radius is bound to expressions over Params,
#          Pad / Pocket / Revolution / Fillet / Chamfer features, STEP export, FCStd save.
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


def make_params(doc, params):
    sheet = doc.addObject("Spreadsheet::Sheet", "Params")
    for i, (name, p) in enumerate(params.items(), start=1):
        sheet.set(f"A{i}", name)
        unit = UNITS.get(p["kind"], "")
        sheet.set(f"B{i}", f"{p['value']!r} {unit}".strip())
        sheet.setAlias(f"B{i}", name)
    return sheet


# ------------------------------------------------------------------ sketches


class SketchBuilder:
    def __init__(self, doc, body, sid, spec):
        self.sk = body.newObject("Sketcher::SketchObject", sid)
        plane = {"XY": "XY_Plane", "XZ": "XZ_Plane", "YZ": "YZ_Plane"}[spec.get("plane", "XY")]
        origin_feature = [f for f in body.Origin.OriginFeatures if f.Role == plane][0]
        self.sk.AttachmentSupport = [(origin_feature, "")]
        self.sk.MapMode = "FlatFace"
        off = spec.get("offset")
        if off:
            self.sk.AttachmentOffset = App.Placement(V(0, 0, off["v"]), App.Rotation())
            if off.get("e"):
                self.sk.setExpression(".AttachmentOffset.Base.z", off["e"])
        self.n = 0

    def _con(self, c, expr=None, name=None):
        idx = self.sk.addConstraint(c)
        if name:
            self.sk.renameConstraint(idx, name)
        if expr:
            self.sk.setExpression(f".Constraints.{name}" if name else f"Constraints[{idx}]", expr)
        return idx

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
            geos.append(self.sk.addGeometry(Part.LineSegment(V(a[0]["v"], a[1]["v"], 0), V(b[0]["v"], b[1]["v"], 0)), False))
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
            g = self.sk.addGeometry(Part.LineSegment(V(p1[0]["v"], p1[1]["v"], 0), V(p2[0]["v"], p2[1]["v"], 0)), False)
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
            arc = self.sk.addGeometry(Part.ArcOfCircle(Part.Circle(V(ccx, ccy, 0), V(0, 0, 1), r["v"]), a1, a2), False)
            self._con(Sketcher.Constraint("Coincident", arc, 1, g1, 2))
            self._con(Sketcher.Constraint("Coincident", arc, 2, g2, 1))
            self._con(Sketcher.Constraint("Radius", arc, r["v"]), r.get("e"), f"{tag}_r{i}")

    def circle(self, s, tag):
        g = self.sk.addGeometry(Part.Circle(V(s["cx"]["v"], s["cy"]["v"], 0), V(0, 0, 1), s["d"]["v"] / 2), False)
        self._con(Sketcher.Constraint("Diameter", g, s["d"]["v"]), s["d"].get("e"), f"{tag}_d")
        if abs(s["cx"]["v"]) < 1e-12 and abs(s["cy"]["v"]) < 1e-12 and not s["cx"].get("e") and not s["cy"].get("e"):
            self._con(Sketcher.Constraint("Coincident", g, 3, -1, 1))
        else:
            self.fix_point(g, 3, s["cx"], s["cy"], tag)

    def add(self, shape, tag):
        getattr(self, shape["type"])(shape, tag) if shape["type"] != "polyline" else self.polygon(shape["pts"], tag)


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
        on_box = min(abs(mid.x - bb.XMin), abs(mid.x - bb.XMax), abs(mid.y - bb.YMin), abs(mid.y - bb.YMax)) < 1e-6
        if is_circle and not on_box:
            c = e.Curve.Center
            on_box = abs(c.x - bb.Center.x) < 1e-6 and abs(e.Curve.Radius - bb.XLength / 2) < 1e-6
        b = sel.get("boundary", "any")
        if b == "outer" and not on_box:
            continue
        if b == "inner" and on_box:
            continue
        names.append(f"Edge{i}")
    return names


# ------------------------------------------------------------------ build


def build():
    doc = App.newDocument("ShilpaModel")
    make_params(doc, JOB["params"])
    body = doc.addObject("PartDesign::Body", "ShilpaBody")
    tip = None
    for op in JOB["ops"]:
        fid, kind = op["id"], op["pd"]
        try:
            if kind in ("Pad", "Pocket", "Revolution"):
                sb = SketchBuilder(doc, body, f"{fid}_sketch", op["sketch"])
                for i, shape in enumerate(op["sketch"]["shapes"]):
                    sb.add(shape, f"s{i}")
                sk = sb.sk
                doc.recompute()
                if kind == "Revolution":
                    feat = body.newObject("PartDesign::Revolution", fid)
                    feat.Profile = sk
                    feat.ReferenceAxis = (sk, ["V_Axis"])
                    feat.Angle = 360.0
                else:
                    feat = body.newObject(f"PartDesign::{kind}", fid)
                    feat.Profile = sk
                    if op.get("through_all"):
                        feat.Type = "ThroughAll"
                        set_symmetric(feat, True)
                    else:
                        feat.Type = "Length"
                        feat.Length = op["length"]["v"]
                        if op["length"].get("e"):
                            feat.setExpression("Length", op["length"]["e"])
                        set_symmetric(feat, bool(op.get("midplane")))
                        feat.Reversed = bool(op.get("reversed"))
                sk.Visibility = False
            elif kind in ("Fillet", "Chamfer"):
                doc.recompute()
                edges = select_edges(tip.Shape, op["selector"])
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
        cell = sheet.getCellFromAlias(name)
        if not cell:
            fail(f"parameter {name!r} is not in the Params sheet")
        old = sheet.get(name)
        unit = str(old).split(" ", 1)[1] if " " in str(old) else ""
        sheet.set(cell, f"{value!r} {unit}".strip())
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
