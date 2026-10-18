"""FreeCAD adapter: native, parametric PartDesign documents (blueprint section 7, backlog B030/B031).

Shilpa's IR is a dataflow graph; a PartDesign Body is a linear feature history. ``lower``
turns a compiled recipe into a linear plan (Pad, Pocket, Revolution, Fillet, Chamfer)
whose every dimension is an expression over a ``Params`` spreadsheet, so editing a
parameter in FreeCAD regenerates the part with the same design intent. Recipes that do
not fit a linear history return a typed unsupported error before FreeCAD runs.

FreeCAD runs as a separate FreeCADCmd process (its own Python) on fc_build.py.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from ..contracts import expr
from ..contracts.compile import CompiledRecipe
from ..contracts.errors import ErrorCode, ShilpaError
from ..settings import ROOT

SCRIPT = Path(__file__).parent / "freecad_script" / "fc_build.py"
TIMEOUT_S = int(os.getenv("SHILPA_FREECAD_TIMEOUT_S", 180))
SAFE_ENV_KEYS = ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "PATH", "TEMP", "TMP", "PATHEXT", "COMSPEC",
                 "NUMBER_OF_PROCESSORS", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "LOCALAPPDATA", "APPDATA", "LANG")

# Linear-history capability matrix (a subset of the IR; intersect has no PartDesign equivalent here).
CAPABILITIES = {"centered_rectangle", "circle", "extrude", "stepped_shaft", "hole", "corner_hole_pattern",
                "linear_hole_pattern", "polar_hole_pattern", "pocket", "boolean", "fillet", "chamfer"}

_NAME = re.compile(r"\b[a-z][a-z0-9_]*\b")


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
        self.sketches: dict[str, dict] = {}
        self.pending: dict[str, dict] = {}  # standalone bodies waiting to be merged by a boolean
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

    def unsupported(self, msg: str, fid: str):
        raise ShilpaError(ErrorCode.UNSUPPORTED_OPERATION, f"FreeCAD adapter: {msg}", feature_id=fid)

    def require_tip(self, fid: str, body_ref: str) -> str:
        if self.tip is None or self.alias.get(body_ref) != self.alias.get(self.tip, self.tip):
            self.unsupported(f"{fid} modifies {body_ref!r}, which is not the current end of the feature history", fid)
        return self.alias[self.tip]

    def advance(self, fid: str) -> None:
        self.tip = fid
        self.alias[fid] = fid

    def lower(self) -> dict:
        for cf in self.c.features:
            f, fid = cf.spec, cf.id
            if cf.op not in CAPABILITIES:
                self.unsupported(f"operation {cf.op} is not supported", fid)
            if cf.op == "centered_rectangle":
                self.sketches[fid] = {"plane": f.plane, "shape": {"type": "rect", "cx": self.q(f.center_x_ref), "cy": self.q(f.center_y_ref),
                                      "w": self.q(f.width_ref), "h": self.q(f.height_ref),
                                      "r": self.q(f.corner_radius_ref) if f.corner_radius_ref else None}}
            elif cf.op == "circle":
                self.sketches[fid] = {"plane": f.plane, "shape": {"type": "circle", "cx": self.q(f.center_x_ref), "cy": self.q(f.center_y_ref),
                                      "d": self.q(f.diameter_ref)}}
            elif cf.op == "extrude":
                sk = self.sketches[f.profile_ref]
                op = {"id": fid, "pd": "Pad", "length": self.q(f.distance_ref),
                      "sketch": {"plane": sk["plane"], "shapes": [sk["shape"]], "offset": self.q(f.offset_ref) if f.offset_ref else None},
                      "midplane": f.direction == "symmetric", "reversed": f.direction in ("negative_z", "negative_normal")}
                self._new_body(fid, op)
            elif cf.op == "stepped_shaft":
                self._new_body(fid, self._shaft(f, fid))
            elif cf.op in ("hole", "corner_hole_pattern", "linear_hole_pattern", "polar_hole_pattern"):
                tip = self.require_tip(fid, f.body_ref)
                circles = [{"type": "circle", "cx": x, "cy": y, "d": self.q(f.diameter_ref)} for x, y in self._centers(cf, tip)]
                op = {"id": fid, "pd": "Pocket", "sketch": {"plane": "XY", "shapes": circles, "offset": None}}
                if f.mode == "through_all":
                    op["through_all"] = True
                else:
                    op["sketch"]["offset"] = self._top(tip)
                    op["length"] = self.q(f.depth_ref)
                self.ops.append(op)
                self.advance(fid)
            elif cf.op == "pocket":
                tip = self.require_tip(fid, f.body_ref)
                rect = {"type": "rect", "cx": self.q(f.center_x_ref), "cy": self.q(f.center_y_ref), "w": self.q(f.width_ref),
                        "h": self.q(f.height_ref), "r": self.q(f.corner_radius_ref) if f.corner_radius_ref else None}
                self.ops.append({"id": fid, "pd": "Pocket", "length": self.q(f.depth_ref),
                                 "sketch": {"plane": "XY", "shapes": [rect], "offset": self._top(tip)}})
                self.advance(fid)
            elif cf.op == "boolean":
                self.require_tip(fid, f.target_ref)
                if f.tool_ref not in self.pending:
                    self.unsupported(f"boolean tool {f.tool_ref!r} must be a standalone extrude or shaft", fid)
                if f.operation == "intersect":
                    self.unsupported("intersect has no linear PartDesign equivalent", fid)
                op = self.pending.pop(f.tool_ref)
                if f.operation == "cut":
                    if op["pd"] != "Pad":
                        self.unsupported("only extruded tools can be cut", fid)
                    # A pad region removed as a pocket: pockets cut against the sketch normal by default.
                    op = {**op, "pd": "Pocket", "reversed": not op["reversed"] if not op["midplane"] else False}
                self.ops.append(op)
                self.alias[fid] = op["id"]
                self.tip = fid
            elif cf.op in ("fillet", "chamfer"):
                self.require_tip(fid, f.body_ref)
                size = self.q(f.radius_ref if cf.op == "fillet" else f.distance_ref)
                self.ops.append({"id": fid, "pd": cf.op.capitalize(), "size": size, "selector": f.edges.model_dump()})
                self.advance(fid)
        if self.pending:
            self.unsupported(f"standalone bodies {sorted(self.pending)} are never merged into the part", next(iter(self.pending)))
        if self.alias.get(self.c.output_id) != self.alias.get(self.tip):
            self.unsupported("the recipe output is not the end of the feature history", self.c.output_id)
        params = {k: {"value": q.value, "kind": q.kind} for k, q in self.params.items()}
        return {"params": params, "ops": self.ops}

    def _new_body(self, fid: str, op: dict) -> None:
        if self.tip is None:
            self.ops.append(op)
            self.advance(fid)
        else:
            self.pending[fid] = op

    def _top(self, tip: str) -> dict:
        bb = self.bbox.get(self.tip)  # bboxes are recorded per IR feature; self.tip is the IR id of the current state
        return {"v": bb["max"][2] if bb else 0.0, "e": f"({tip}.Shape.BoundBox.ZMax * 1 mm)"}

    def _centers(self, cf, tip: str) -> list[tuple[dict, dict]]:
        f = cf.spec
        if cf.op == "hole":
            return [(self.q(f.center_x_ref), self.q(f.center_y_ref))]
        if cf.op == "corner_hole_pattern":
            bb = self.bbox[self.tip]
            e = self.q(f.edge_offset_ref)
            xs = [({"v": bb["min"][0] + e["v"], "e": f"({tip}.Shape.BoundBox.XMin * 1 mm) + ({e['e']})"}),
                  ({"v": bb["max"][0] - e["v"], "e": f"({tip}.Shape.BoundBox.XMax * 1 mm) - ({e['e']})"})]
            ys = [({"v": bb["min"][1] + e["v"], "e": f"({tip}.Shape.BoundBox.YMin * 1 mm) + ({e['e']})"}),
                  ({"v": bb["max"][1] - e["v"], "e": f"({tip}.Shape.BoundBox.YMax * 1 mm) - ({e['e']})"})]
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
        import math

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
