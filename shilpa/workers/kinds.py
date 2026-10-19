"""Execution contracts for job kinds beyond single parts: assemblies, sheet metal and products.

Each ``execute_*`` runs inside the restricted geometry subprocess, writes its files
into the staging directory and returns a result dict shaped like
``pipeline.ExecutionResult.to_dict()`` (``ok``, ``error``, ``features``,
``validation``, ``artifacts``, ``engine``, ``timings_ms``), so the CAD worker can
publish it as an immutable version exactly like a part.

``ok`` means the geometry was built and exported. Failed design checks (an
interference, a hovering mate, a hole too close to a bend) do not make a job
fail: they are findings the engineer needs to see, so the version is published
with ``validation.passed = false`` and every check listed.

Besides the exchange files, every kind writes two viewer files:

- ``meshes.json``: one tessellated mesh per distinct part geometry, in part-local
  millimetres (Z up), as base64 float32 positions and uint32 indices;
- ``viewer.json``: instances (mesh key, colour, part-to-world matrix), the
  swept joints with their world frames so the studio can scrub them client-side,
  every check with the instances it involves, the BOM, and for sheet metal the
  flat pattern as polylines plus the bend table.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np

from ..contracts.errors import ErrorCode, ShilpaError

MESH_ANGULAR = 0.25  # rad


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _artifacts(out_dir: Path, files: dict[str, str]) -> list[dict]:
    out = []
    for fmt, name in files.items():
        p = out_dir / name
        if p.exists():
            out.append({"format": fmt, "path": str(p), "sha256": _sha(p), "bytes": p.stat().st_size})
    return out


def _engine() -> dict:
    from ..adapters import build123d_adapter as adapter

    return adapter.engine_versions()


def _jsonable(o: Any):
    if hasattr(o, "model_dump"):
        return o.model_dump(mode="json")
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if hasattr(o, "value") and not isinstance(o, (str, bytes)):
        return o.value
    return str(o)


def _write_json(path: Path, data: Any) -> Path:
    path.write_text(json.dumps(data, indent=1, default=_jsonable), encoding="utf-8")
    return path


def _fail(code: ErrorCode, message: str, timings: dict | None = None, **details) -> dict:
    err = ShilpaError(code, message, details=details or None).info.model_dump(mode="json")
    return {"ok": False, "error": err, "features": [], "validation": None, "artifacts": [], "engine": {},
            "timings_ms": timings or {}}


# ---------------------------------------------------------------- meshes


def color_hex(name: str | None) -> str | None:
    """CSS colour name or #rrggbb -> #rrggbb (None when unknown)."""
    if not name:
        return None
    if name.startswith("#") and len(name) in (4, 7):
        return name.lower()
    try:
        import build123d as bd

        r, g, b, _ = tuple(bd.Color(name))
    except Exception:
        return None
    return "#{:02x}{:02x}{:02x}".format(*(round(c * 255) for c in (r, g, b)))


def mesh_of(shape, tolerance: float | None = None) -> dict:
    """Tessellate one solid in its own coordinates; tolerance scales with its size."""
    bb = shape.bounding_box()
    diag = math.sqrt(bb.size.X ** 2 + bb.size.Y ** 2 + bb.size.Z ** 2) or 1.0
    tol = tolerance or min(0.5, max(0.01, diag * 6e-4))
    verts, tris = shape.tessellate(tol, MESH_ANGULAR)
    pos = np.array([(v.X, v.Y, v.Z) for v in verts], dtype=np.float32).reshape(-1)
    idx = np.array(tris, dtype=np.uint32).reshape(-1)
    return {"positions": base64.b64encode(pos.tobytes()).decode("ascii"),
            "indices": base64.b64encode(idx.tobytes()).decode("ascii"),
            "vertices": len(verts), "triangles": len(tris), "tolerance_mm": round(tol, 4),
            "bbox": [[bb.min.X, bb.min.Y, bb.min.Z], [bb.max.X, bb.max.Y, bb.max.Z]]}


# ---------------------------------------------------------------- assembly

ASSEMBLY_FILES = {"STEP": "assembly.step", "FCSTD": "assembly.FCStd", "BOM_CSV": "bom.csv", "BOM_JSON": "bom.json",
                  "PLACEMENTS": "placements.json", "MESHES": "meshes.json", "VIEWER": "viewer.json",
                  "VALIDATION": "validation.json", "RECIPE": "spec.json"}
DEFAULT_RANGE = {"angle": (-180.0, 180.0), "offset": (-50.0, 50.0)}


def _import_sources() -> None:
    """Part sources register themselves on import; missing optional modules are fine."""
    import importlib

    for mod in ("shilpa.catalog", "shilpa.weldment", "shilpa.sheetmetal", "shilpa.product"):
        try:
            importlib.import_module(mod)
        except Exception:
            pass


def mesh_key(spec, iid: str) -> str:
    """Copies share their root's geometry, so they share one mesh."""
    inst = spec.instance(iid)
    while inst.copy_of:
        inst = spec.instance(inst.copy_of)
    return inst.id


def _trans_z(dz: float) -> np.ndarray:
    T = np.eye(4)
    T[2, 3] = dz
    return T


def _rot_z(deg: float) -> np.ndarray:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    T = np.eye(4)
    T[:2, :2] = [[c, -s], [s, c]]
    return T


def joint_frames(build) -> list[dict]:
    """World frames of the swept joints in the placement tree, for client-side scrubbing.

    Moving a joint from its assembled value by ``d`` (degrees about the joint z, or mm
    along it) moves every instance on its moving side by ``W = J @ motion(sign * d) @ inv(J)``,
    with ``motion`` a turn about z plus, for a screw, the advance ``d * pitch / 360``.
    Derived from ``T_b = T_a @ P_a @ Translate(xy, offset) @ RotZ(angle) @ F @ inv(P_b)``:
    the joint motion sits between ``Translate`` and ``RotZ`` on the forward side, and in
    the inverted chain (``sign = -1``) when the moving side is ``a``.
    """
    from ..assembly.build import FLIP, port_matrix
    from ..contracts.assembly import SWEPT

    out = []
    for m, forward in build.order:
        if m.type not in SWEPT or m.inst_a not in build.matrices or m.inst_b not in build.matrices:
            continue
        param = SWEPT[m.type]
        Pa = port_matrix(build.parts[m.inst_a].port(m.port_a))
        Pb = port_matrix(build.parts[m.inst_b].port(m.port_b))
        trans = np.eye(4)
        trans[:3, 3] = (m.xy[0], m.xy[1], m.offset)
        F = FLIP if m.opposed else np.eye(4)
        if forward:
            J, sign = build.matrices[m.inst_a] @ Pa @ trans, 1.0
        else:
            J, sign = build.matrices[m.inst_b] @ Pb @ np.linalg.inv(F) @ _rot_z(-m.angle), -1.0
        value = m.angle if param == "angle" else m.offset
        limits = list(m.limits) if m.limits else [value + d for d in DEFAULT_RANGE[param]]
        out.append({"name": m.name, "type": m.type, "a": m.inst_a, "b": m.inst_b, "param": param,
                    "unit": "deg" if param == "angle" else "mm", "value": value, "limits": limits,
                    "has_limits": m.limits is not None, "pitch": m.pitch, "sign": sign,
                    "frame": [[round(float(v), 9) for v in row] for row in J],
                    "moving": sorted(build.moving_side(m))})
    return out


def joint_motion(joint: dict, value: float) -> np.ndarray:
    """World transform applied to the moving side when ``joint`` is set to ``value`` (mirrors the studio)."""
    d = value - joint["value"]
    s = joint["sign"]
    if joint["param"] == "angle":
        motion = _trans_z(s * d * (joint["pitch"] or 0.0) / 360.0 if joint["type"] == "screw" else 0.0) @ _rot_z(s * d)
    else:
        motion = _trans_z(s * d)
    J = np.array(joint["frame"])
    return J @ motion @ np.linalg.inv(J)


def _check_group(name: str) -> str:
    base = name.split("[", 1)[0]
    return {"spec_valid": "spec", "part_built": "build", "bom_built": "bom", "bom_quantities": "bom",
            "all_placed": "spec"}.get(base, base)


def check_instances(build, name: str, actual: Any, note: str | None = None) -> list[str]:
    """Instance ids a check is about, for click-to-highlight in the studio."""
    known = {i.id for i in build.spec.instances}
    mates = {m.name: m for m in build.spec.mates}
    inside = name[name.find("[") + 1:-1] if "[" in name and name.endswith("]") else None
    found: list[str] = []

    def add(iid):
        if iid in known and iid not in found:
            found.append(iid)

    if inside is not None:
        if inside in mates:
            add(mates[inside].inst_a)
            add(mates[inside].inst_b)
        elif "+" in inside:
            for iid in inside.split("+"):
                add(iid)
        else:
            add(inside)
    if name.startswith("sweep[") and isinstance(actual, list):
        for hit in actual:
            for iid in str(hit.get("pair", "")).split("+"):
                add(iid)
    if name in ("interference", "all_placed") and isinstance(actual, list):
        for item in actual:
            for iid in str(item).split("+"):
                add(iid)
    if name == "spec_valid":
        for issue in build.issues:
            for w in issue.where:
                add(w.split(".")[0])
    return found


def assembly_viewer(build, report, kind: str = "assembly", extra: dict | None = None) -> dict:
    spec = build.spec
    from ..contracts.assembly import part_number

    instances = []
    for inst in spec.instances:
        part = build.parts.get(inst.id)
        root = spec.root_of(inst.id)
        color = inst.color or (spec.instance(inst.copy_of).color if inst.copy_of else None) or root.color
        T = build.matrices.get(inst.id)
        instances.append({"id": inst.id, "part_number": part_number(spec, inst.id), "name": part.name if part else None,
                          "source": root.source, "color": color_hex(color), "mesh": mesh_key(spec, inst.id) if part else None,
                          "matrix": [[round(float(v), 9) for v in row] for row in T] if T is not None else None,
                          "placed": T is not None, "grounded": inst.grounded, "quantity": inst.quantity,
                          "copy_of": inst.copy_of,
                          "error": build.errors[inst.id].message if inst.id in build.errors else None})
    checks = []
    for c in report.checks:
        checks.append({"name": c.name, "group": _check_group(c.name), "passed": c.passed, "requested": c.requested,
                       "actual": c.actual, "tolerance": c.tolerance, "note": c.note,
                       "instances": check_instances(build, c.name, c.actual, c.note)})
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    for shape in build.placed.values():
        bb = shape.bounding_box()
        lo = np.minimum(lo, [bb.min.X, bb.min.Y, bb.min.Z])
        hi = np.maximum(hi, [bb.max.X, bb.max.Y, bb.max.Z])
    size = (hi - lo).tolist() if np.isfinite(lo).all() else None
    out = {"kind": kind, "name": spec.name, "passed": report.passed, "instances": instances, "joints": joint_frames(build),
           "mates": [{"name": m.name, "type": m.type, "a": m.inst_a, "b": m.inst_b, "intent": m.intent,
                      "in_tree": any(m is t for t, _ in build.order)} for m in spec.mates],
           "checks": checks, "bom": report.bom, "dof": report.dof,
           "issues": [{"code": i.code, "message": i.message, "where": i.where, "severity": i.severity} for i in build.issues],
           "bbox": [lo.tolist(), hi.tolist()] if size else None, "size": [round(v, 4) for v in size] if size else None}
    if extra:
        out.update(extra)
    return out


def write_assembly(build, out_dir: Path, freecad: bool = False, kind: str = "assembly", extra_viewer: dict | None = None,
                   extra_checks: list | None = None, timings: dict | None = None) -> dict:
    """Validate a built assembly and write every exchange and viewer file. Returns the result dict."""
    from ..assembly.export import export_all
    from ..validators.assembly import validate_assembly
    from ..validators.geometry import Check

    timings = timings if timings is not None else {}
    t0 = time.perf_counter()
    report = validate_assembly(build)
    for c in extra_checks or []:
        report.checks.append(c if isinstance(c, Check) else Check(**c))
    report.passed = all(c.passed for c in report.checks)
    timings["validate"] = (time.perf_counter() - t0) * 1000
    if not build.placed:
        return _fail(ErrorCode.VALIDATION_FAILED, "nothing could be placed: " + "; ".join(report.failed), timings,
                     validation=report.to_dict())

    t0 = time.perf_counter()
    fc_note = None
    try:
        export_all(build, out_dir, freecad=False)
    except ShilpaError as exc:
        return _fail(exc.code, exc.info.message, timings)
    if freecad:
        from ..adapters import freecad_adapter
        from ..assembly.export import export_fcstd

        if freecad_adapter.available():
            try:
                res = export_fcstd(build, out_dir)
                report.checks.append(Check("freecad_assembly", bool(res.get("ok")) and (out_dir / "assembly.FCStd").exists(),
                                           note=f"FreeCAD {res.get('freecad')}, joints {res.get('joints')}, "
                                                f"joints satisfied {res.get('joints_satisfied')}"))
            except ShilpaError as exc:
                report.checks.append(Check("freecad_assembly", False, note=exc.info.message))
        else:
            fc_note = "FreeCAD is not installed on this server"
    timings["export"] = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    meshes: dict[str, dict] = {}
    for inst in build.spec.instances:
        if inst.id not in build.parts:
            continue
        key = mesh_key(build.spec, inst.id)
        if key not in meshes:
            meshes[key] = mesh_of(build.parts[inst.id].solid)
    _write_json(out_dir / "meshes.json", {"units": "mm", "up": "Z", "frame": "part", "parts": meshes})
    timings["mesh"] = (time.perf_counter() - t0) * 1000

    validation = report.to_dict()
    if fc_note:
        validation["notes"] = [fc_note]
    _write_json(out_dir / "validation.json", validation)
    _write_json(out_dir / "spec.json", build.spec.model_dump(mode="json", exclude_none=True))
    _write_json(out_dir / "viewer.json", assembly_viewer(build, report, kind, extra_viewer))
    return {"ok": True, "error": None, "features": [], "validation": validation,
            "artifacts": _artifacts(out_dir, ASSEMBLY_FILES), "engine": _engine(), "timings_ms": timings,
            "parameters": {}, "conversions": []}


def execute_assembly(spec: dict, out_dir: Path, options: dict | None = None, cancel_check=None) -> dict:
    from pydantic import ValidationError

    from ..assembly.build import build_assembly
    from ..contracts.assembly import AssemblySpec

    options = options or {}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _import_sources()
    try:
        parsed = AssemblySpec.model_validate(spec)
    except ValidationError as exc:
        return _fail(ErrorCode.INVALID_SCHEMA, f"assembly spec is invalid: {exc.errors()[0]['msg']}")
    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    build = build_assembly(parsed)
    timings["build"] = (time.perf_counter() - t0) * 1000
    if cancel_check and cancel_check():
        return _fail(ErrorCode.CANCELLED, "cancelled", timings)
    return write_assembly(build, out_dir, freecad=bool(options.get("freecad")), timings=timings)


# ---------------------------------------------------------------- sheet metal

SHEET_FILES = {"STEP": "model.step", "DXF": "flat.dxf", "MESHES": "meshes.json", "VIEWER": "viewer.json",
               "VALIDATION": "validation.json", "RECIPE": "spec.json"}


def _edge_points(edge, n: int) -> list[tuple[float, float]]:
    return [(round(p.X, 5), round(p.Y, 5)) for p in (edge.position_at(t) for t in np.linspace(0.0, 1.0, n))]


def wire_loop(wire) -> list[list[float]]:
    """A closed wire as one ordered polyline in XY (curves sampled)."""
    edges = wire.order_edges() if hasattr(wire, "order_edges") else wire.edges()
    pts: list[tuple[float, float]] = []
    for e in edges:
        n = 2 if e.geom_type.name == "LINE" else max(24, min(96, int(e.length)))
        seg = _edge_points(e, n)
        if pts:
            if math.dist(pts[-1], seg[0]) > math.dist(pts[-1], seg[-1]):
                seg.reverse()
            seg = seg[1:]
        elif len(edges) > 1:
            nxt = edges[1]
            a, b = nxt.position_at(0), nxt.position_at(1)
            end = min(math.dist(seg[-1], (a.X, a.Y)), math.dist(seg[-1], (b.X, b.Y)))
            start = min(math.dist(seg[0], (a.X, a.Y)), math.dist(seg[0], (b.X, b.Y)))
            if start < end:
                seg.reverse()
        pts += seg
    return [list(p) for p in pts]


def flat_pattern(part) -> dict:
    loops = []
    for face in part.flat.faces():
        loops.append({"outer": True, "points": wire_loop(face.outer_wire())})
        for w in face.inner_wires():
            loops.append({"outer": False, "points": wire_loop(w)})
    bb = part.flat.bounding_box()
    return {"loops": loops,
            "bends": [{"id": bid, "a": [round(a[0], 5), round(a[1], 5)], "b": [round(b[0], 5), round(b[1], 5)]}
                      for bid, a, b in part.bend_lines()],
            "extents": [{"id": b.id, "lines": [[list(map(float, p)) for p in b.flat_start], [list(map(float, p)) for p in b.flat_end]]}
                        for b in part.bends.values()],
            "bbox": [[bb.min.X, bb.min.Y], [bb.max.X, bb.max.Y]], "size": [round(bb.size.X, 4), round(bb.size.Y, 4)],
            "area": round(float(part.flat.area), 4)}


def execute_sheet_metal(spec: dict, out_dir: Path, options: dict | None = None, cancel_check=None) -> dict:
    from pydantic import ValidationError

    from ..sheetmetal import SheetMetalSpec, build
    from ..sheetmetal.checks import check

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        parsed = SheetMetalSpec.model_validate(spec)
    except ValidationError as exc:
        return _fail(ErrorCode.INVALID_SCHEMA, f"sheet-metal spec is invalid: {exc.errors()[0]['msg']}")
    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    try:
        part = build(parsed)
    except ShilpaError as exc:
        return _fail(exc.code, exc.info.message, timings)
    except Exception as exc:
        return _fail(ErrorCode.KERNEL_FAILURE, f"sheet-metal build failed: {exc}", timings)
    timings["build"] = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    try:
        part.export_step(out_dir / "model.step")
        part.export_dxf(out_dir / "flat.dxf")
    except ShilpaError as exc:
        return _fail(exc.code, exc.info.message, timings)
    except Exception as exc:
        return _fail(ErrorCode.EXPORT_FAILED, f"export failed: {exc}", timings)
    timings["export"] = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    report = check(part)
    timings["validate"] = (time.perf_counter() - t0) * 1000
    meta = part.meta()
    validation = report.to_dict()
    validation["meta"] = meta
    _write_json(out_dir / "validation.json", validation)
    _write_json(out_dir / "spec.json", parsed.model_dump(mode="json", exclude_none=True))
    _write_json(out_dir / "meshes.json", {"units": "mm", "up": "Z", "frame": "part", "parts": {"part": mesh_of(part.solid)}})
    bb = part.solid.bounding_box()
    checks = [{"name": c.name, "group": c.name.split(":")[0], "passed": c.passed, "requested": c.requested, "actual": c.actual,
               "tolerance": c.tolerance, "note": c.note, "instances": []} for c in report.checks]
    viewer = {"kind": "sheet_metal", "name": parsed.name, "passed": report.passed,
              "instances": [{"id": "part", "part_number": parsed.name, "name": parsed.name, "source": "sheet_metal",
                             "color": None, "mesh": "part", "matrix": np.eye(4).tolist(), "placed": True, "grounded": True,
                             "quantity": 1, "copy_of": None, "error": None}],
              "joints": [], "mates": [], "checks": checks, "bom": [], "dof": {}, "issues": [],
              "bbox": [[bb.min.X, bb.min.Y, bb.min.Z], [bb.max.X, bb.max.Y, bb.max.Z]],
              "size": [round(bb.size.X, 4), round(bb.size.Y, 4), round(bb.size.Z, 4)],
              "flat": flat_pattern(part), "bend_table": meta["bend_table"], "meta": meta, "stats": report.stats}
    _write_json(out_dir / "viewer.json", viewer)
    return {"ok": True, "error": None, "features": [], "validation": validation, "artifacts": _artifacts(out_dir, SHEET_FILES),
            "engine": _engine(), "timings_ms": timings, "parameters": {}, "conversions": []}


# ---------------------------------------------------------------- product

PRODUCT_FILES = {**ASSEMBLY_FILES, "PRODUCT": "product.json"}
NOT_INSTALLED = "product templates not installed: this server has no shilpa.product.run_product yet"


def product_runner():
    """``shilpa.product.run_product`` when the product templates are installed, else None."""
    try:
        from ..product import run_product  # type: ignore[attr-defined]
    except Exception:
        return None
    return run_product


def _field(obj: Any, *names: str):
    for n in names:
        if isinstance(obj, dict) and n in obj:
            return obj[n]
        if not isinstance(obj, dict) and hasattr(obj, n):
            return getattr(obj, n)
    return None


def execute_product(payload: dict, out_dir: Path, options: dict | None = None, cancel_check=None) -> dict:
    """Call ``run_product(spec_or_request, out_dir)`` and publish what it built.

    The product module is expected to return its result (an object or dict). When that
    result carries the placed ``AssemblyBuild`` (``build`` / ``assembly_build``), the same
    exchange and viewer files as an assembly job are written from it, and product-level
    checks (``report.checks`` / ``checks``) join the assembly checks. Whatever else it
    returns is kept as ``product.json``.
    """
    run_product = product_runner()
    if run_product is None:
        return _fail(ErrorCode.UNSUPPORTED_OPERATION, NOT_INSTALLED)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _import_sources()
    arg = payload.get("spec") if payload.get("spec") is not None else payload.get("request")
    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    try:
        res = run_product(arg, out_dir)
    except ShilpaError as exc:
        return _fail(exc.code, exc.info.message, timings)
    except Exception as exc:
        return _fail(ErrorCode.KERNEL_FAILURE, f"product build failed: {type(exc).__name__}: {exc}", timings)
    timings["product"] = (time.perf_counter() - t0) * 1000
    summary = res.to_dict() if hasattr(res, "to_dict") else res
    _write_json(out_dir / "product.json", summary if isinstance(summary, (dict, list)) else {"result": summary})

    build = _field(res, "build", "assembly_build")
    if build is None and _field(res, "assembly") is not None:
        from ..assembly.build import build_assembly

        build = build_assembly(_field(res, "assembly"))
    if build is None:
        ok = bool(_field(res, "ok", "passed") if _field(res, "ok", "passed") is not None else True)
        return {"ok": ok, "error": None, "features": [], "validation": {"passed": ok, "checks": []},
                "artifacts": _artifacts(out_dir, PRODUCT_FILES), "engine": _engine(), "timings_ms": timings,
                "parameters": {}, "conversions": []}
    product_checks = []
    report = _field(res, "report", "product_report")
    for c in (_field(report, "checks") if report is not None else _field(res, "checks")) or []:
        name = _field(c, "name") or "product_check"
        product_checks.append({"name": f"product[{name}]" if not str(name).startswith("product") else str(name),
                               "passed": bool(_field(c, "passed")), "actual": _field(c, "actual"),
                               "note": _field(c, "note", "message", "reason")})
    result = write_assembly(build, out_dir, freecad=bool((options or {}).get("freecad")), kind="product",
                            extra_viewer={"product": summary if isinstance(summary, dict) else None},
                            extra_checks=product_checks, timings=timings)
    if result.get("ok"):
        result["artifacts"] = _artifacts(out_dir, PRODUCT_FILES)
    return result


EXECUTORS = {"assembly": execute_assembly, "sheet_metal": execute_sheet_metal, "product": execute_product}
FILES = {"assembly": ASSEMBLY_FILES, "sheet_metal": SHEET_FILES, "product": PRODUCT_FILES}
