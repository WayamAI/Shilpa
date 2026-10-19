"""Deterministic execution contract: recipe -> solid -> artifacts -> validation.

This is what a CAD worker runs for one attempt (blueprint section 4.1). It writes
into a staging directory and returns a manifest; publishing a version is the
caller's responsibility and only happens when ``result.ok`` is true.

``execute_kind`` is the same contract for assemblies, sheet metal and products
(``shilpa/workers/kinds.py``).
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import build123d as bd

from .adapters import build123d_adapter as adapter
from .contracts.errors import ErrorCode, ErrorInfo, ShilpaError
from .validators import geometry

STL_TOLERANCE = 0.01  # mm linear deflection
STL_ANGULAR = 0.1  # rad
GLB_LINEAR = 0.05
GLB_ANGULAR = 0.2


@dataclass
class Artifact:
    format: str
    path: str
    sha256: str
    bytes: int


@dataclass
class ExecutionResult:
    ok: bool
    error: ErrorInfo | None
    features: list[dict]
    validation: dict | None
    artifacts: list[Artifact] = field(default_factory=list)
    engine: dict = field(default_factory=dict)
    timings_ms: dict = field(default_factory=dict)
    parameters: dict = field(default_factory=dict)
    conversions: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        def default(o):
            if hasattr(o, "model_dump"):
                return o.model_dump(mode="json")
            return o.value if hasattr(o, "value") else str(o)

        return json.loads(json.dumps(asdict(self), default=default))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def execute(recipe, out_dir: Path, oracle: dict | None = None, cancel_check=None) -> ExecutionResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    timings: dict[str, float] = {}
    engine = adapter.engine_versions()

    t0 = time.perf_counter()
    try:
        built = adapter.build(recipe, cancel_check=cancel_check)
    except ShilpaError as exc:
        return ExecutionResult(False, exc.info, [], None, engine=engine)
    timings["build"] = (time.perf_counter() - t0) * 1000
    feats = [asdict(f) for f in built.features]
    params = {k: {"value": q.value, "kind": q.kind} for k, q in built.compiled.params.items()}
    conversions = [asdict(c) for c in built.compiled.conversions]
    if not built.ok:
        return ExecutionResult(False, built.error.info, feats, None, engine=engine, timings_ms=timings, parameters=params, conversions=conversions)

    shape = built.shape
    recipe_obj = built.compiled.recipe
    artifacts: list[Artifact] = []
    (out_dir / "recipe.json").write_text(recipe_obj.model_dump_json(indent=2), encoding="utf-8")

    t0 = time.perf_counter()
    step = out_dir / "model.step"
    try:
        bd.export_step(shape, str(step))
        if "STL" in recipe_obj.exports:
            stl = out_dir / "model.stl"
            bd.export_stl(shape, str(stl), tolerance=STL_TOLERANCE, angular_tolerance=STL_ANGULAR)
            (out_dir / "model.stl.units.json").write_text(
                json.dumps({"units": "mm", "linear_deflection_mm": STL_TOLERANCE, "angular_deflection_rad": STL_ANGULAR}, indent=2),
                encoding="utf-8",
            )
        if "GLB" in recipe_obj.exports:
            glb = out_dir / "preview.glb"
            bd.export_gltf(shape, str(glb), unit=bd.Unit.MM, binary=True, linear_deflection=GLB_LINEAR, angular_deflection=GLB_ANGULAR)
    except Exception as exc:
        err = ShilpaError(ErrorCode.EXPORT_FAILED, f"export failed: {exc}")
        return ExecutionResult(False, err.info, feats, None, engine=engine, timings_ms=timings, parameters=params, conversions=conversions)
    timings["export"] = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    report = geometry.validate(step, built.compiled.assertion_values, built_volume=shape.volume, oracle=oracle)
    if report.measurement is not None:
        size = report.measurement.bbox_size
        if (out_dir / "model.stl").exists():
            report.checks += geometry.validate_stl(out_dir / "model.stl", size, STL_TOLERANCE, STL_ANGULAR)
        if (out_dir / "preview.glb").exists():
            report.checks += geometry.validate_glb(out_dir / "preview.glb", size, GLB_LINEAR, GLB_ANGULAR)
        report.passed = all(c.passed for c in report.checks)
    timings["validate"] = (time.perf_counter() - t0) * 1000

    if report.passed and "FCSTD" in recipe_obj.exports:
        t0 = time.perf_counter()
        report.checks += _freecad_checks(built, feats, out_dir, report.measurement)
        report.passed = all(c.passed for c in report.checks)
        timings["freecad"] = (time.perf_counter() - t0) * 1000
    validation = report.to_dict()
    (out_dir / "validation.json").write_text(json.dumps(validation, indent=2), encoding="utf-8")
    (out_dir / "features.json").write_text(json.dumps(feats, indent=2, default=str), encoding="utf-8")

    for fmt, name in (("FCSTD", "model.FCStd"), ("STEP", "model.step"), ("STL", "model.stl"), ("STL_UNITS", "model.stl.units.json"), ("GLB", "preview.glb"), ("RECIPE", "recipe.json"), ("VALIDATION", "validation.json")):
        p = out_dir / name
        if p.exists():
            artifacts.append(Artifact(fmt, str(p), sha256(p), p.stat().st_size))

    error = None
    if not report.passed:
        failed = [c.name for c in report.checks if not c.passed]
        error = ShilpaError(ErrorCode.VALIDATION_FAILED, "validation failed: " + ", ".join(failed), details={"failed": failed}).info
    return ExecutionResult(report.passed, error, feats, validation, artifacts, engine, timings, params, conversions)


def _freecad_checks(built, feats: list[dict], out_dir: Path, ref: geometry.Measurement) -> list[geometry.Check]:
    """Native FreeCAD document: build, then validate its own STEP and compare with the build123d solid."""
    from .adapters import freecad_adapter

    try:
        res = freecad_adapter.build_fcstd(built.compiled, feats, out_dir)
    except ShilpaError as exc:
        return [geometry.Check("freecad_build", False, note=exc.info.message)]
    if not res.get("ok"):
        err = res.get("error") or {}
        return [geometry.Check("freecad_build", False, note=f"{err.get('feature_id') or ''} {err.get('message', '')}".strip())]
    checks = [geometry.Check("freecad_build", True, note=f"FreeCAD {res.get('freecad')} in {res.get('ms')} ms")]
    fc = geometry.validate(out_dir / "freecad.step", built.compiled.assertion_values, built_volume=built.shape.volume)
    for c in fc.checks:
        c.name = "freecad_" + c.name
    checks += fc.checks
    if fc.measurement is not None:
        ok = all(abs(a - b) <= geometry.DIM_TOL for a, b in zip(fc.measurement.bbox_size, ref.bbox_size))
        checks.append(geometry.Check("freecad_matches_build123d_bbox", ok, list(ref.bbox_size), list(fc.measurement.bbox_size), geometry.DIM_TOL))
    return checks


KINDS = ("assembly", "sheet_metal", "product")


def execute_kind(kind: str, spec: dict, out_dir: Path, options: dict | None = None, cancel_check=None) -> dict:
    """Run one non-part job kind; returns a result dict shaped like ``ExecutionResult.to_dict()``."""
    from .workers.kinds import EXECUTORS

    if kind not in EXECUTORS:
        raise ShilpaError(ErrorCode.UNSUPPORTED_OPERATION, f"unknown job kind {kind!r}; have {sorted(EXECUTORS)}")
    return EXECUTORS[kind](spec, Path(out_dir), options or {}, cancel_check)
