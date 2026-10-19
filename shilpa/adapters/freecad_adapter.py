"""FreeCAD adapter: native, parametric PartDesign documents (blueprint section 7, backlog B030/B031).

Shilpa's IR is a dataflow graph; a PartDesign Body is a linear feature history. ``lower``
turns a compiled recipe into a linear plan (Pad, Pocket, Revolution, Groove, Additive /
Subtractive Pipe, Helix and Loft, Thickness, Mirrored, Linear / Polar Pattern, Fillet,
Chamfer) whose every dimension is an expression over a ``Params`` spreadsheet, so editing
a parameter in FreeCAD regenerates the part with the same design intent. Standalone tool
bodies wait until a boolean merges them; a cut turns the additive feature into its
subtractive twin. Recipes that do not fit a linear history return a typed unsupported
error before FreeCAD runs.

Named references (IR 1.2) lower to explicit subelements: the build123d build resolves
the reference and records the selected entities' signatures, and fc_build.py picks the
FreeCAD edges / faces with the same signatures (identical geometry in both kernels).
A FreeCAD parameter edit then keeps those subelements through FreeCAD's own topological
naming, but cannot re-resolve the reference: a fillet on "every hole's entry edge" keeps
its old edges when the hole count changes. ``selection_drift`` compares an edited
document's selections with a build123d rebuild of the same edit and flags that case, so
the caller re-lowers instead of trusting the edited document. A named hole entry face
is not lowered (its sketch plane has no expression link to the parameters).

FreeCAD runs as a separate FreeCADCmd process (its own Python) on fc_build.py.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from ..contracts import expr
from ..contracts.compile import PLANE_AXES, CompiledFeature, CompiledRecipe
from ..contracts.errors import ErrorCode, ShilpaError
from ..contracts.ir import HOLE_OPS, SKETCH_OPS, NamedSelector
from ..settings import ROOT

SCRIPT = Path(__file__).parent / "freecad_script" / "fc_build.py"
TIMEOUT_S = int(os.getenv("SHILPA_FREECAD_TIMEOUT_S", 180))
SAFE_ENV_KEYS = ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "PATH", "TEMP", "TMP", "PATHEXT", "COMSPEC",
                 "NUMBER_OF_PROCESSORS", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "LOCALAPPDATA", "APPDATA", "LANG")

# Linear-history capability matrix (a subset of the IR; intersect has no PartDesign equivalent here).
CAPABILITIES = {"centered_rectangle", "circle", "slot", "profile", "path", "helix", "extrude", "stepped_shaft",
                "revolve", "sweep", "loft", "hole", "corner_hole_pattern", "linear_hole_pattern", "polar_hole_pattern",
                "pocket", "boolean", "shell", "mirror", "linear_pattern", "polar_pattern", "fillet", "chamfer"}

_NAME = re.compile(r"\b[a-z][a-z0-9_]*\b")
# A cut turns an additive tool feature into its subtractive twin.
SUBTRACTIVE = {"Pad": "Pocket", "Revolution": "Groove", "AdditivePipe": "SubtractivePipe",
               "AdditiveLoft": "SubtractiveLoft", "AdditiveHelix": "SubtractiveHelix"}
# Sketch plane normals as (global axis index, sign): XZ faces -Y in both kernels.
NORMAL = {"XY": (2, 1), "XZ": (1, -1), "YZ": (0, 1)}
# Hole entry sides: (axis index, outward sign, in-face (u, v) axis indices) and the sketch plane holding (u, v).
SIDES = {"top": (2, 1, (0, 1)), "bottom": (2, -1, (0, 1)), "x_max": (0, 1, (1, 2)), "x_min": (0, -1, (1, 2)),
         "y_max": (1, 1, (0, 2)), "y_min": (1, -1, (0, 2))}
SIDE_PLANE = {"top": "XY", "bottom": "XY", "x_max": "YZ", "x_min": "YZ", "y_max": "XZ", "y_min": "XZ"}


def ex(q: dict, unit: str = "mm") -> str:
    """FreeCAD expression text for a value dict; constants become quantities."""
    return q.get("e") or f"{q['v']!r} {unit}".strip()


def _q_add(a: dict, b: dict) -> dict:
    out = {"v": a["v"] + b["v"]}
    if a.get("e") or b.get("e"):
        out["e"] = f"({ex(a)}) + ({ex(b)})"
    return out


def freecad_cmd() -> Path | None:
    explicit = os.getenv("SHILPA_FREECAD_CMD")
    if explicit and Path(explicit).exists():
        return Path(explicit)
    for p in sorted((ROOT / "tools" / "freecad").glob("**/FreeCADCmd.exe")):
        return p
    return None


def available() -> bool:
    return freecad_cmd() is not None


# ------------------------------------------------------------------ lowering


class _Lowerer:
    def __init__(self, compiled: CompiledRecipe, feature_results: list[dict]):
        self.c = compiled
        self.params = compiled.params
        self.bbox = {f["id"]: f.get("detail", {}).get("bbox") for f in feature_results}
        self.detail = {f["id"]: f.get("detail", {}) for f in feature_results}
        self.sketches: dict[str, dict] = {}
        self.helices: dict[str, CompiledFeature] = {}
        self.pending: dict[str, list[dict]] = {}  # standalone bodies (their ops) waiting to be merged by a boolean
        self.ops: list[dict] = []
        self.tip: str | None = None
        self.alias: dict[str, str] = {}  # IR body id -> FreeCAD object name now holding that state

    def q(self, ref: str | None) -> dict:
        """Value plus FreeCAD expression for an IR reference (None means 0)."""
        if ref is None:
            return {"v": 0.0}
        v = expr.evaluate(ref, self.params).value
        e = _NAME.sub(lambda m: f"Params.{m.group(0)}" if m.group(0) in self.params else m.group(0), ref)
        return {"v": v, "e": e}

    def qv(self, cf: CompiledFeature, name: str) -> dict:
        """Like q, but falls back to the compiled value (ISO table lookups are constants)."""
        ref = getattr(cf.spec, name, None)
        return self.q(ref) if ref is not None else {"v": cf.values[name]}

    def unsupported(self, msg: str, fid: str):
        raise ShilpaError(ErrorCode.UNSUPPORTED_OPERATION, f"FreeCAD adapter: {msg}", feature_id=fid)

    def require_tip(self, fid: str, body_ref: str) -> str:
        if self.tip is None or self.alias.get(body_ref) != self.alias.get(self.tip, self.tip):
            self.unsupported(f"{fid} modifies {body_ref!r}, which is not the current end of the feature history", fid)
        return self.alias[self.tip]

    def advance(self, fid: str, obj: str | None = None) -> None:
        self.tip = fid
        self.alias[fid] = obj or fid

    def lower(self) -> dict:
        for cf in self.c.features:
            f, fid = cf.spec, cf.id
            if cf.op not in CAPABILITIES:
                self.unsupported(f"operation {cf.op} is not supported", fid)
            if cf.op in SKETCH_OPS or cf.op == "path":
                self.sketches[fid] = self._sketch(cf)
            elif cf.op == "helix":
                self.helices[fid] = cf
            elif cf.op == "extrude":
                sk = self._placed(f.profile_ref, f.offset_ref)
                op = {"id": fid, "pd": "Pad", "length": self.q(f.distance_ref), "sketch": sk,
                      "midplane": f.direction == "symmetric", "reversed": f.direction in ("negative_z", "negative_normal")}
                self._new_body(fid, [op])
            elif cf.op == "stepped_shaft":
                self._new_body(fid, [self._shaft(f, fid)])
            elif cf.op == "revolve":
                sk = self.sketches[f.profile_ref]
                axis = "H_Axis" if f.axis == PLANE_AXES[sk["plane"]][0] else "V_Axis"
                # Both kernels revolve counter-clockwise about the positive global axis (checked against FreeCAD 1.1).
                self._new_body(fid, [{"id": fid, "pd": "Revolution", "sketch": sk, "axis": axis,
                                      "angle": self.q(f.angle_ref) if f.angle_ref else {"v": 360.0}}])
            elif cf.op == "sweep":
                sk = self.sketches[f.profile_ref]
                if f.path_ref in self.helices:
                    h = self.helices[f.path_ref]
                    op = {"id": fid, "pd": "AdditiveHelix", "sketch": sk, "pitch": self.q(h.spec.pitch_ref),
                          "height": self.q(h.spec.height_ref), "left_handed": h.spec.left_handed}
                else:
                    op = {"id": fid, "pd": "AdditivePipe", "sketch": sk, "spine": self.sketches[f.path_ref]}
                self._new_body(fid, [op])
            elif cf.op == "loft":
                self._new_body(fid, [{"id": fid, "pd": "AdditiveLoft", "sections": [self.sketches[p] for p in f.profile_refs],
                                      "ruled": f.ruled}])
            elif cf.op in HOLE_OPS:
                self._holes(cf)
            elif cf.op == "pocket":
                tip = self.require_tip(fid, f.body_ref)
                rect = {"type": "rect", "cx": self.q(f.center_x_ref), "cy": self.q(f.center_y_ref), "w": self.q(f.width_ref),
                        "h": self.q(f.height_ref), "r": self.q(f.corner_radius_ref) if f.corner_radius_ref else None}
                self.ops.append({"id": fid, "pd": "Pocket", "length": self.q(f.depth_ref),
                                 "sketch": {"plane": "XY", "shapes": [rect], "offset": self._entry(tip, "top")[0]}})
                self.advance(fid)
            elif cf.op == "boolean":
                self._boolean(cf)
            elif cf.op == "shell":
                self.require_tip(fid, f.body_ref)
                self.ops.append({"id": fid, "pd": "Thickness", "size": self.q(f.thickness_ref), "inward": f.direction == "inward",
                                 "faces": [s.model_dump() for s in f.open_faces if not isinstance(s, NamedSelector)],
                                 "face_signatures": self._signatures(fid) if any(isinstance(s, NamedSelector) for s in f.open_faces)
                                 else None})
                self.advance(fid)
            elif cf.op in ("mirror", "linear_pattern", "polar_pattern"):
                self._transform(cf)
            elif cf.op in ("fillet", "chamfer"):
                self.require_tip(fid, f.body_ref)
                size = self.q(f.radius_ref if cf.op == "fillet" else f.distance_ref)
                sel = f.edges.model_dump()
                if isinstance(f.edges, NamedSelector):
                    sel = {**sel, "signatures": self._signatures(fid), "expected_count": len(self._signatures(fid))}
                sel["diameter_value"] = cf.values.get("edges.diameter")
                self.ops.append({"id": fid, "pd": cf.op.capitalize(), "size": size, "selector": sel})
                self.advance(fid)
        if self.pending:
            self.unsupported(f"standalone bodies {sorted(self.pending)} are never merged into the part", next(iter(self.pending)))
        if self.alias.get(self.c.output_id) != self.alias.get(self.tip):
            self.unsupported("the recipe output is not the end of the feature history", self.c.output_id)
        params = {k: {"value": q.value, "kind": q.kind} for k, q in self.params.items()}
        return {"params": params, "ops": self.ops}

    def _signatures(self, fid: str) -> list[dict]:
        """Signatures of the entities the build123d build selected for a named reference."""
        sigs = self.detail.get(fid, {}).get("selected")
        if not sigs:
            self.unsupported("named reference has no resolved selection from the build123d build", fid)
        return sigs

    def _new_body(self, fid: str, ops: list[dict]) -> None:
        if self.tip is None:
            self.ops.extend(ops)
            self.advance(fid, ops[-1]["id"])
        else:
            self.pending[fid] = ops

    # -------------------------------------------------------------- sketches

    def _sketch(self, cf: CompiledFeature) -> dict:
        f = cf.spec
        off = self.q(f.offset_ref) if getattr(f, "offset_ref", None) else None
        if cf.op == "centered_rectangle":
            shapes = [{"type": "rect", "cx": self.q(f.center_x_ref), "cy": self.q(f.center_y_ref), "w": self.q(f.width_ref),
                       "h": self.q(f.height_ref), "r": self.q(f.corner_radius_ref) if f.corner_radius_ref else None}]
        elif cf.op == "circle":
            shapes = [{"type": "circle", "cx": self.q(f.center_x_ref), "cy": self.q(f.center_y_ref), "d": self.q(f.diameter_ref)}]
            if f.inner_diameter_ref:
                shapes.append({**shapes[0], "d": self.q(f.inner_diameter_ref)})
        elif cf.op == "slot":
            shapes = [self._slot(cf)]
        else:  # profile or path
            shapes = [self._chain(cf)]
        return {"plane": f.plane, "shapes": shapes, "offset": off}

    def _placed(self, sketch_id: str, extra_ref: str | None) -> dict:
        """A sketch spec with an extra offset along its normal (an extrude's start offset)."""
        sk = dict(self.sketches[sketch_id])
        if extra_ref:
            sk["offset"] = _q_add(sk["offset"], self.q(extra_ref)) if sk["offset"] else self.q(extra_ref)
        return sk

    def _chain(self, cf: CompiledFeature) -> dict:
        """Profile or path segments: exact geometry from the compiler, endpoints bound to the IR refs."""
        f = cf.spec
        start = (self.q(f.start_x_ref), self.q(f.start_y_ref))
        ends = [(self.q(s.x_ref), self.q(s.y_ref)) for s in f.segments]
        segs = []
        for s in cf.segments:
            i = s.source
            p0 = start if i == 0 else ends[i - 1] if i is not None else ends[-1]
            p1 = ends[i] if i is not None else start
            out = {"kind": "line", "p0": p0, "p1": p1}
            if s.kind == "arc":
                ir = f.segments[i]
                out.update(center=list(s.center), radius=s.radius, ccw=s.ccw)
                if ir.kind == "arc":
                    out.update(kind="arc3", mid=(self.q(ir.mid_x_ref), self.q(ir.mid_y_ref)))
                elif ir.kind == "tangent_arc":
                    out.update(kind="tangent")
                else:
                    out.update(kind="radius", r=self.q(ir.radius_ref))
            segs.append(out)
        if f.op == "profile" and cf.segments[-1].source is not None:
            segs[-1]["p1"] = start  # the last segment closes onto the start point
        return {"type": "chain", "closed": f.op == "profile", "segs": segs}

    def _slot(self, cf: CompiledFeature) -> dict:
        f, v = cf.spec, cf.values
        cx, cy, L, W = self.q(f.center_x_ref), self.q(f.center_y_ref), self.q(f.length_ref), self.q(f.width_ref)
        a = self.q(f.rotation_angle_ref) if f.rotation_angle_ref else None
        av = math.radians(a["v"]) if a else 0.0
        parametric = any(q.get("e") for q in (cx, cy, L, W) + ((a,) if a else ()))

        def pt(su: int, sn: int) -> tuple[dict, dict]:
            x = cx["v"] + su * L["v"] / 2 * math.cos(av) - sn * W["v"] / 2 * math.sin(av)
            y = cy["v"] + su * L["v"] / 2 * math.sin(av) + sn * W["v"] / 2 * math.cos(av)
            if not parametric:
                return {"v": x}, {"v": y}
            if a is None:
                return ({"v": x, "e": f"({ex(cx)}) + {su} * ({ex(L)}) / 2"}, {"v": y, "e": f"({ex(cy)}) + {sn} * ({ex(W)}) / 2"})
            c, s = f"cos({ex(a, 'deg')})", f"sin({ex(a, 'deg')})"
            return ({"v": x, "e": f"({ex(cx)}) + {su} * ({ex(L)}) / 2 * {c} - {sn} * ({ex(W)}) / 2 * {s}"},
                    {"v": y, "e": f"({ex(cy)}) + {su} * ({ex(L)}) / 2 * {s} + {sn} * ({ex(W)}) / 2 * {c}"})

        corners = [pt(-1, -1), pt(1, -1), pt(1, 1), pt(-1, 1)]
        centers = [[cx["v"] + su * L["v"] / 2 * math.cos(av), cy["v"] + su * L["v"] / 2 * math.sin(av)] for su in (1, -1)]
        # The end arcs are tangent to the sides: a radius on a semicircle with pinned ends is degenerate for the solver.
        segs = [{"kind": "line", "p0": corners[0], "p1": corners[1]},
                {"kind": "tangent", "p0": corners[1], "p1": corners[2], "center": centers[0], "radius": W["v"] / 2, "ccw": True},
                {"kind": "line", "p0": corners[2], "p1": corners[3]},
                {"kind": "tangent", "p0": corners[3], "p1": corners[0], "center": centers[1], "radius": W["v"] / 2, "ccw": True}]
        return {"type": "chain", "closed": True, "segs": segs}

    # -------------------------------------------------------------- holes

    def _entry(self, tip: str, side: str) -> tuple[dict, bool]:
        """Sketch offset (along the side's sketch-plane normal) of a hole entry face, and whether the cut runs along that normal."""
        axis, sign, _ = SIDES[side]
        n_axis, n_sign = NORMAL[SIDE_PLANE[side]]
        assert n_axis == axis
        bb = self.bbox.get(self.tip)  # bboxes are recorded per IR feature; self.tip is the IR id of the current state
        key = "max" if sign > 0 else "min"
        coord = {"v": bb[key][axis] if bb else 0.0, "e": f"({tip}.Shape.BoundBox.{'XYZ'[axis]}{key.capitalize()} * 1 mm)"}
        off = coord if n_sign > 0 else {"v": -coord["v"], "e": f"-{coord['e']}"}
        return off, -sign == n_sign

    def _holes(self, cf: CompiledFeature) -> None:
        f, fid = cf.spec, cf.id
        tip = self.require_tip(fid, f.body_ref)
        if f.entry_face is not None:
            self.unsupported("a named hole entry face has no parametric sketch placement in PartDesign", fid)
        plane = SIDE_PLANE[f.face]
        centers = self._centers(cf, tip)
        d = self.qv(cf, "diameter_ref")
        entry, along_normal = self._entry(tip, f.face)

        def circles(dia: dict) -> list[dict]:
            return [{"type": "circle", "cx": x, "cy": y, "d": dia} for x, y in centers]

        if f.hole_type == "counterbore":
            self.ops.append({"id": f"{fid}_cbore", "pd": "Pocket", "length": self.qv(cf, "cbore_depth_ref"), "reversed": along_normal,
                             "sketch": {"plane": plane, "shapes": circles(self.qv(cf, "cbore_diameter_ref")), "offset": entry}})
        elif f.hole_type == "countersink":
            D, A = self.qv(cf, "csk_diameter_ref"), self.qv(cf, "csk_angle_ref")
            depth = {"v": cf.values["csk_depth"]}
            if any(q.get("e") for q in (D, A, d)):
                depth["e"] = f"(({ex(D)}) - ({ex(d)})) / 2 / tan(({ex(A, 'deg')}) / 2)"
            # A negative taper narrows the pocket as it goes in: the cone wall sits at half the included angle.
            taper = {"v": -A["v"] / 2, **({"e": f"-({A['e']}) / 2"} if A.get("e") else {})}
            self.ops.append({"id": f"{fid}_csk", "pd": "Pocket", "length": depth, "taper": taper, "reversed": along_normal,
                             "sketch": {"plane": plane, "shapes": circles(D), "offset": entry}})
        op = {"id": fid, "pd": "Pocket", "sketch": {"plane": plane, "shapes": circles(d), "offset": None}}
        if f.mode == "through_all":
            op["through_all"] = True
        else:
            op["sketch"]["offset"] = entry
            op["length"] = self.q(f.depth_ref)
            op["reversed"] = along_normal
        if cf.meta.get("thread"):
            op["meta"] = {"ShilpaThread": cf.meta["thread"] + (f" depth {cf.meta['thread_depth']:g} mm" if "thread_depth" in cf.meta else "")}
        self.ops.append(op)
        self.advance(fid)

    def _centers(self, cf, tip: str) -> list[tuple[dict, dict]]:
        f = cf.spec
        if cf.op == "hole":
            return [(self.q(f.center_x_ref), self.q(f.center_y_ref))]
        if cf.op == "corner_hole_pattern":
            bb = self.bbox[self.tip]
            e = self.q(f.edge_offset_ref)
            _, _, (iu, iv) = SIDES[f.face]

            def lim(i: int, key: str, sign: int) -> dict:
                name = f"{'XYZ'[i]}{key.capitalize()}"
                return {"v": bb[key][i] + sign * e["v"], "e": f"({tip}.Shape.BoundBox.{name} * 1 mm) {'+' if sign > 0 else '-'} ({e['e']})"}

            xs = [lim(iu, "min", 1), lim(iu, "max", -1)]
            ys = [lim(iv, "min", 1), lim(iv, "max", -1)]
            return [(x, y) for x in xs for y in ys]
        cx, cy = self.q(f.center_x_ref), self.q(f.center_y_ref)
        cxe, cye = cx.get("e") or "0 mm", cy.get("e") or "0 mm"
        if cf.op == "linear_hole_pattern":
            nx, ny = int(cf.values["count_x_ref"]), int(cf.values["count_y_ref"])
            px, py = self.q(f.pitch_x_ref), self.q(f.pitch_y_ref)
            out = []
            for i in range(nx):
                for j in range(ny):
                    ox, oy = i - (nx - 1) / 2, j - (ny - 1) / 2
                    out.append(({"v": cx["v"] + ox * px["v"], "e": f"({cxe}) + {ox!r} * ({px['e']})"},
                                {"v": cy["v"] + oy * py["v"], "e": f"({cye}) + {oy!r} * ({py['e']})"}))
            return out
        # polar
        n = int(cf.values["count_ref"])
        pcd = self.q(f.pitch_diameter_ref)
        a0 = self.q(f.start_angle_ref) if f.start_angle_ref else {"v": 0.0}
        out = []
        for k in range(n):
            step = 360.0 * k / n
            ang = f"({a0['e']}) + {step!r} deg" if a0.get("e") else f"{step!r} deg"
            rad = math.radians(a0["v"] + step)
            out.append(({"v": cx["v"] + pcd["v"] / 2 * math.cos(rad), "e": f"({cxe}) + ({pcd['e']}) / 2 * cos({ang})"},
                        {"v": cy["v"] + pcd["v"] / 2 * math.sin(rad), "e": f"({cye}) + ({pcd['e']}) / 2 * sin({ang})"}))
        return out

    # -------------------------------------------------------------- bodies

    def _boolean(self, cf: CompiledFeature) -> None:
        f, fid = cf.spec, cf.id
        self.require_tip(fid, f.target_ref)
        if f.tool_ref not in self.pending:
            self.unsupported(f"boolean tool {f.tool_ref!r} must be a standalone body (extrude, shaft, revolve, sweep, "
                             "loft, or a mirror / pattern of one)", fid)
        if f.operation == "intersect":
            self.unsupported("intersect has no linear PartDesign equivalent", fid)
        ops = self.pending.pop(f.tool_ref)
        if f.operation == "cut":
            first = ops[0]
            if first["pd"] not in SUBTRACTIVE:
                self.unsupported(f"{first['pd']} tools cannot be cut", fid)
            if first["pd"] == "Pad":
                # A pad region removed as a pocket: pockets cut against the sketch normal by default.
                first = {**first, "pd": "Pocket", "reversed": not first["reversed"] if not first["midplane"] else False}
            else:
                first = {**first, "pd": SUBTRACTIVE[first["pd"]]}
            ops = [first] + ops[1:]
        self.ops.extend(ops)
        self.advance(fid, ops[-1]["id"])

    def _transform(self, cf: CompiledFeature) -> None:
        """Mirror / pattern: of a waiting tool body (feature mode, merged later) or of the whole current part."""
        f, fid = cf.spec, cf.id
        pd = {"mirror": "Mirrored", "linear_pattern": "LinearPattern", "polar_pattern": "PolarPattern"}[cf.op]
        op: dict = {"id": fid, "pd": pd}
        if cf.op == "mirror":
            if not f.keep_original:
                self.unsupported("a mirror without the original has no PartDesign equivalent", fid)
            op.update(plane=f.plane, offset=self.q(f.offset_ref) if f.offset_ref else None)
        elif cf.op == "linear_pattern":
            op.update(direction=f.direction, count=self.q(f.count_ref), spacing=self.q(f.spacing_ref))
        else:
            op.update(axis=f.axis, count=self.q(f.count_ref), angle=self.q(f.angle_ref) if f.angle_ref else {"v": 360.0})
        if f.body_ref in self.pending:
            ops = self.pending.pop(f.body_ref)
            if len(ops) != 1:
                self.unsupported(f"{fid} transforms {f.body_ref!r}, which is already a mirror or pattern", fid)
            op["originals"] = [ops[0]["id"]]
            self.pending[fid] = ops + [op]
        else:
            self.require_tip(fid, f.body_ref)
            op["originals"] = None  # whole shape
            self.ops.append(op)
            self.advance(fid)

    def _shaft(self, f, fid: str) -> dict:
        n = len(f.sections)
        z = self.q(f.offset_ref) if f.offset_ref else {"v": 0.0}
        bore = {"v": self.q(f.bore_diameter_ref)["v"] / 2, "e": f"({self.q(f.bore_diameter_ref)['e']}) / 2"} if f.bore_diameter_ref else {"v": 0.0}
        pts = [(bore, z)]
        for i in range(n):
            d = self.q(f.sections[i].diameter_ref)
            r = {"v": d["v"] / 2, "e": f"({d['e']}) / 2"}
            length = self.q(f.sections[i].length_ref)
            z_next = {"v": z["v"] + length["v"], "e": f"({z['e']}) + ({length['e']})" if z.get("e") else length["e"]}
            pts += [(r, z), (r, z_next)]
            z = z_next
        pts.append((bore, z))
        clean = [pts[0]]
        for p in pts[1:]:
            if abs(p[0]["v"] - clean[-1][0]["v"]) > 1e-9 or abs(p[1]["v"] - clean[-1][1]["v"]) > 1e-9:
                clean.append(p)
        return {"id": fid, "pd": "Revolution", "sketch": {"plane": "XZ", "shapes": [{"type": "polyline", "pts": clean}], "offset": None}}


def lower(compiled: CompiledRecipe, feature_results: list[dict]) -> dict:
    return _Lowerer(compiled, feature_results).lower()


# ------------------------------------------------------------------ running FreeCAD


def _run(job: dict, work: Path) -> dict:
    exe = freecad_cmd()
    if exe is None:
        raise ShilpaError(ErrorCode.EXPORT_FAILED, "FreeCAD is not installed (tools/freecad or SHILPA_FREECAD_CMD)")
    job_path, result_path = work / "fc_job.json", work / "fc_result.json"
    job["result"] = str(result_path)
    job_path.write_text(json.dumps(job), encoding="utf-8")
    result_path.unlink(missing_ok=True)
    env = {k: v for k, v in os.environ.items() if k.upper() in SAFE_ENV_KEYS}
    env["SHILPA_FC_JOB"] = str(job_path)
    t0 = time.perf_counter()
    try:
        proc = subprocess.run([str(exe), str(SCRIPT)], env=env, cwd=str(work), capture_output=True, text=True,
                              timeout=TIMEOUT_S, check=False)
    except subprocess.TimeoutExpired:
        raise ShilpaError(ErrorCode.EXPORT_FAILED, f"FreeCAD did not finish within {TIMEOUT_S} s")
    if not result_path.exists():
        raise ShilpaError(ErrorCode.EXPORT_FAILED, "FreeCAD exited without a result",
                          details={"stdout": proc.stdout[-1500:], "stderr": proc.stderr[-1500:]})
    res = json.loads(result_path.read_text(encoding="utf-8"))
    res["ms"] = round((time.perf_counter() - t0) * 1000)
    return res


def _short_workdir() -> Path:
    # FreeCAD fails to write files on long Windows paths (deep staging keys give "Failed to
    # open file"), so it always works in a short scratch directory under var/.
    from ..settings import settings

    base = Path(os.getenv("SHILPA_FREECAD_SCRATCH") or settings.var_dir / "fc")
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="j", dir=base))


def selection_drift(build, fc_result: dict) -> list[str]:
    """Selections an edited FreeCAD document kept that a build123d rebuild of the same edit would change.

    ``build`` is the build123d BuildResult of the edited recipe; ``fc_result`` the result of
    ``edit_fcstd`` (fc_build.py reports each fillet / chamfer / thickness feature's
    subelements after recompute). A count mismatch means FreeCAD's stored references no
    longer say what the recipe's selector means; re-lower the edited recipe.
    """
    fc = {s["id"]: s for s in fc_result.get("selections", [])}
    out = []
    for f in build.features:
        want = f.detail.get("edges", f.detail.get("open_faces")) if f.op in ("fillet", "chamfer", "shell") else None
        if want is None or f.id not in fc:
            continue
        got = len(fc[f.id]["subs"])
        if got != want:
            out.append(f"{f.id}: FreeCAD keeps {got} {'faces' if f.op == 'shell' else 'edges'}, the recipe now selects {want}")
    return out


def build_fcstd(compiled: CompiledRecipe, feature_results: list[dict], out_dir: Path) -> dict:
    plan = lower(compiled, feature_results)
    out_dir = Path(out_dir)
    (out_dir / "freecad_plan.json").write_text(json.dumps(plan, indent=1), encoding="utf-8")
    work = _short_workdir()
    try:
        job = {"mode": "build", **plan, "out_fcstd": str(work / "model.FCStd"), "out_step": str(work / "freecad.step")}
        res = _run(job, work)
        for name in ("model.FCStd", "freecad.step"):
            if (work / name).exists():
                shutil.copy2(work / name, out_dir / name)
        shutil.copy2(work / "fc_result.json", out_dir / "freecad_result.json")
        return res
    finally:
        shutil.rmtree(work, ignore_errors=True)


def edit_fcstd(fcstd: Path, changes: dict[str, float], out_dir: Path) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    work = _short_workdir()
    try:
        shutil.copy2(fcstd, work / "source.FCStd")
        job = {"mode": "edit", "fcstd": str(work / "source.FCStd"), "set": changes, "out_fcstd": str(work / "edited.FCStd"),
               "out_step": str(work / "edited.step")}
        res = _run(job, work)
        for name in ("edited.FCStd", "edited.step"):
            if (work / name).exists():
                shutil.copy2(work / name, out_dir / name)
        return res
    finally:
        shutil.rmtree(work, ignore_errors=True)
