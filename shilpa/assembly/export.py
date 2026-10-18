"""Assembly exports: labelled, coloured STEP; BOM as CSV and JSON; FreeCAD Assembly document.

STEP keeps one labelled child per instance (instance id as the product name, its
colour), so a STEP viewer shows the tree. The FreeCAD export writes a 1.x Assembly
with each instance an App::Link to one shared part feature and each mate a native
joint (Fixed, Revolute, Cylindrical, Slider, Ball, Screw; planar has no FreeCAD
equivalent and is skipped), then lets FreeCAD's solver re-place everything and
compares its placements with Shilpa's.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import build123d as bd
import numpy as np

from ..adapters import freecad_adapter
from ..contracts.errors import ErrorCode, ShilpaError
from .build import AssemblyBuild, mate_matrix, port_matrix

FC_SCRIPT = Path(__file__).parent / "fc_assembly.py"
PLACEMENT_TOL = 1e-4  # mm / matrix entry, FreeCAD solve vs Shilpa placement


def export_step(build: AssemblyBuild, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if build.compound is None or not build.placed:
        raise ShilpaError(ErrorCode.EXPORT_FAILED, "nothing placed to export")
    bd.export_step(build.compound, str(path))
    return path


def bom_rows(build: AssemblyBuild) -> list[dict]:
    from ..validators.assembly import bill_of_materials

    return bill_of_materials(build)


def write_bom(build: AssemblyBuild, out_dir: Path, stem: str = "bom") -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = bom_rows(build)
    js = out_dir / f"{stem}.json"
    js.write_text(json.dumps({"assembly": build.spec.name, "lines": rows}, indent=2), encoding="utf-8")
    cs = out_dir / f"{stem}.csv"
    cols = ["part_number", "quantity", "source", "name", "generator", "volume_mm3", "instances"]
    with cs.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({**{c: r.get(c) for c in cols}, "instances": " ".join(r["instances"])})
    return cs, js


def write_placements(build: AssemblyBuild, path: Path) -> Path:
    path = Path(path)
    path.write_text(json.dumps(build.placement_table(), indent=1), encoding="utf-8")
    return path


def _part_key(build: AssemblyBuild, iid: str) -> str:
    """Instances sharing geometry share a FreeCAD part feature (copies resolve to their root)."""
    inst = build.spec.instance(iid)
    while inst.copy_of:
        inst = build.spec.instance(inst.copy_of)
    return inst.id


def freecad_job(build: AssemblyBuild, work: Path) -> dict:
    parts, instances = {}, []
    for inst in build.spec.instances:
        if inst.id not in build.matrices:
            continue
        key = _part_key(build, inst.id)
        if key not in parts:
            p = work / f"{key}.brep"
            bd.export_brep(build.parts[inst.id].solid, str(p))
            parts[key] = str(p)
        instances.append({"id": inst.id, "part": key, "matrix": build.matrices[inst.id].tolist()})
    joints = []
    for m, _ in build.order:
        Pa = port_matrix(build.parts[m.inst_a].port(m.port_a))
        Pb = port_matrix(build.parts[m.inst_b].port(m.port_b))
        joints.append({"name": m.name.replace(".", "_").replace("~", "__"), "type": m.type, "a": m.inst_a, "b": m.inst_b,
                       "jcs1": (Pa @ mate_matrix(m)).tolist(), "jcs2": Pb.tolist(),
                       "limits": list(m.limits) if m.limits else None, "pitch": m.pitch})
    return {"parts": parts, "instances": instances, "joints": joints, "ground": build.ground}


def joint_residuals(job: dict, placements: dict[str, list]) -> dict[str, float]:
    """How far each joint's two connectors are from satisfying its type, on the given placements.

    Fixed: frames equal. Revolute: origins and z equal. Cylindrical: z equal, origins on one z line.
    Slider: z and x equal, origins on one z line. Ball: origins equal. Screw: as cylindrical.
    """
    out = {}
    for j in job["joints"]:
        if j["a"] not in placements or j["b"] not in placements:
            continue
        A = np.array(placements[j["a"]]) @ np.array(j["jcs1"])
        B = np.array(placements[j["b"]]) @ np.array(j["jcs2"])
        dz = np.abs(A[:3, 2] - B[:3, 2]).max()
        dx = np.abs(A[:3, 0] - B[:3, 0]).max()
        d = B[:3, 3] - A[:3, 3]
        off_axis = np.linalg.norm(d - A[:3, 2] * d.dot(A[:3, 2]))
        r = {"fixed": max(dz, dx, np.abs(d).max()), "revolute": max(dz, np.linalg.norm(d)), "ball": np.linalg.norm(d),
             "cylindrical": max(dz, off_axis), "screw": max(dz, off_axis), "slider": max(dz, dx, off_axis)}.get(j["type"])
        if r is not None:
            out[j["name"]] = float(r)
    return out


def export_fcstd(build: AssemblyBuild, out_dir: Path, scramble: tuple[float, float, float] | None = (3.0, -2.0, 1.0)) -> dict:
    """Write ``assembly.FCStd``. Returns the FreeCAD result plus ``joints`` ("all" | "partial" | "none"),
    ``joints_satisfied`` (every exported joint's constraint holds on FreeCAD's solved placements) and
    ``placements_match`` (FreeCAD's solved placements equal Shilpa's).

    ``scramble`` shifts every non-ground link before FreeCAD solves, so satisfied joints show the
    joints themselves drive the placement rather than the initial positions. Parts held by joints
    with free DOF may then settle elsewhere along those DOF, so ``placements_match`` is only
    expected with ``scramble=None`` or a fully rigid assembly.
    """
    exe = freecad_adapter.freecad_cmd()
    if exe is None:
        raise ShilpaError(ErrorCode.EXPORT_FAILED, "FreeCAD is not installed (tools/freecad or SHILPA_FREECAD_CMD)")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    work = freecad_adapter._short_workdir()
    try:
        job = {**freecad_job(build, work), "out_fcstd": str(work / "assembly.FCStd"), "result": str(work / "fc_result.json"),
               "scramble": list(scramble) if scramble else None}
        (work / "fc_job.json").write_text(json.dumps(job), encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k.upper() in freecad_adapter.SAFE_ENV_KEYS}
        env["SHILPA_FC_JOB"] = str(work / "fc_job.json")
        t0 = time.perf_counter()
        try:
            proc = subprocess.run([str(exe), str(FC_SCRIPT)], env=env, cwd=str(work), capture_output=True, text=True,
                                  timeout=freecad_adapter.TIMEOUT_S, check=False)
        except subprocess.TimeoutExpired:
            raise ShilpaError(ErrorCode.EXPORT_FAILED, f"FreeCAD did not finish within {freecad_adapter.TIMEOUT_S} s")
        result_path = work / "fc_result.json"
        if not result_path.exists():
            raise ShilpaError(ErrorCode.EXPORT_FAILED, "FreeCAD exited without a result",
                              details={"stdout": proc.stdout[-1500:], "stderr": proc.stderr[-1500:]})
        res = json.loads(result_path.read_text(encoding="utf-8"))
        res["ms"] = round((time.perf_counter() - t0) * 1000)
        if (work / "assembly.FCStd").exists():
            shutil.copy2(work / "assembly.FCStd", out_dir / "assembly.FCStd")
        worst = 0.0
        for iid, m in res.get("placements", {}).items():
            worst = max(worst, float(np.abs(np.array(m) - build.matrices[iid]).max()))
        res["placement_max_dev"] = worst
        res["placements_match"] = bool(res.get("placements")) and worst <= PLACEMENT_TOL
        res["joint_residuals"] = joint_residuals(job, res.get("placements", {}))
        res["joints_satisfied"] = bool(res.get("placements")) and all(r <= PLACEMENT_TOL for r in res["joint_residuals"].values())
        (out_dir / "freecad_assembly_result.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
        return res
    finally:
        shutil.rmtree(work, ignore_errors=True)


def export_all(build: AssemblyBuild, out_dir: Path, freecad: bool = False) -> dict[str, Path]:
    """STEP, BOM (CSV and JSON) and the placement table; plus FCStd when asked and FreeCAD exists."""
    out_dir = Path(out_dir)
    paths = {"STEP": export_step(build, out_dir / "assembly.step")}
    paths["BOM_CSV"], paths["BOM_JSON"] = write_bom(build, out_dir)
    paths["PLACEMENTS"] = write_placements(build, out_dir / "placements.json")
    if freecad and freecad_adapter.available():
        res = export_fcstd(build, out_dir)
        if res.get("ok"):
            paths["FCSTD"] = out_dir / "assembly.FCStd"
    return paths
