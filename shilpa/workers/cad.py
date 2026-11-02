"""CPU CAD worker (local stand-in for a Container Apps event job, blueprint sections 5, 10).

Receives a cad message, takes the job lease, runs the geometry subprocess with a
timeout while renewing the message lock and job lease, then either publishes an
immutable model version or routes the failure to repair / failed. The message is
completed only after the durable transition, so a crash means redelivery, and the
unique (job_id) constraint on model_versions prevents a second publication.

Run:  uv run python -m shilpa.workers.cad
"""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select, update

from .. import queue, thumbs
from ..contracts.errors import ErrorCode, ShilpaError
from ..contracts.hashing import recipe_hash
from ..db import (
    Artifact,
    Job,
    JobAttempt,
    Model,
    ModelVersion,
    UsageEvent,
    init_db,
    now,
    tx,
)
from ..jobs import TERMINAL, StaleRevision, load, transition
from ..settings import ROOT, settings
from ..storage import blobs
from . import kinds

log = logging.getLogger("shilpa.worker")
WORKER_ID = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
SAFE_ENV_KEYS = ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "PATH", "TEMP", "TMP", "PATHEXT", "COMSPEC", "NUMBER_OF_PROCESSORS",
                 "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "LOCALAPPDATA", "APPDATA", "LANG",
                 "SHILPA_FREECAD_CMD")  # a path to the FreeCAD binary, not a credential

PUBLISHED_FILES = {"FCSTD": "model.FCStd", "STEP": "model.step", "STL": "model.stl", "STL_UNITS": "model.stl.units.json", "GLB": "preview.glb",
                   "RECIPE": "recipe.json", "VALIDATION": "validation.json", "FEATURES": "features.json", "THUMB": thumbs.THUMB_FILE}
# Assembly, sheet-metal and product jobs publish their own file sets.
KIND_FILES = {k: {**v, "THUMB": thumbs.THUMB_FILE} for k, v in kinds.FILES.items()}


def _scrubbed_env() -> dict:
    env = {k: v for k, v in os.environ.items() if k.upper() in SAFE_ENV_KEYS}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _claim_lease(job_id: str) -> bool:
    t = now()
    with tx() as s:
        res = s.execute(
            update(Job)
            .where(Job.id == job_id, Job.state == "executing")
            .where((Job.lease_owner.is_(None)) | (Job.lease_expires_at < t) | (Job.lease_owner == WORKER_ID))
            .values(lease_owner=WORKER_ID, lease_expires_at=t + timedelta(seconds=settings.lock_duration_s))
        )
        return res.rowcount == 1


def _renew_loop(r: queue.Received, job_id: str, stop: threading.Event, cancel_flag: Path) -> None:
    while not stop.wait(max(5, settings.lock_duration_s // 3)):
        queue.renew(r)
        with tx() as s:
            s.execute(update(Job).where(Job.id == job_id, Job.lease_owner == WORKER_ID)
                      .values(lease_expires_at=now() + timedelta(seconds=settings.lock_duration_s)))
            job = load(s, job_id)
            if job and job.cancel_requested:
                cancel_flag.touch()


def _progress_loop(job_id: str, attempt_no: int, log: Path, stop: threading.Event) -> None:
    """Relay the geometry process's progress lines (product jobs) as ``progress`` job events."""
    seen = 0
    while True:
        done = stop.wait(1.0)
        try:
            lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
        except OSError:
            lines = []
        if len(lines) > seen:
            with tx() as s:
                for line in lines[seen:]:
                    transition_event(s, job_id, "progress", {"attempt": attempt_no, "message": line[:500]})
            seen = len(lines)
        if done:
            return


def run_geometry(recipe: dict, out_dir: Path, cancel_flag: Path, kind: str | None = None,
                 options: dict | None = None) -> tuple[dict, float]:
    """Run one attempt in the restricted subprocess. ``kind`` selects a non-part executor (assembly, ...)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    rpath = out_dir / "input_recipe.json"
    payload = {"__exec__": kind, "spec": recipe, "options": options or {}} if kind else recipe
    rpath.write_text(json.dumps(payload), encoding="utf-8")
    t0 = time.perf_counter()
    try:
        subprocess.run([sys.executable, "-E", "-s", "-m", "shilpa.workers.geometry_exec", str(rpath), str(out_dir), str(cancel_flag)],
                       cwd=str(ROOT), env=_scrubbed_env(), timeout=settings.worker_timeout_s, capture_output=True, check=False)
    except subprocess.TimeoutExpired:
        err = ShilpaError(ErrorCode.KERNEL_FAILURE, f"geometry execution exceeded {settings.worker_timeout_s} s")
        err.info.retryable = False
        return {"ok": False, "error": err.info.model_dump(mode="json"), "features": []}, time.perf_counter() - t0
    elapsed = time.perf_counter() - t0
    result_file = out_dir / "result.json"
    if not result_file.exists():
        err = ShilpaError(ErrorCode.INTERNAL, "geometry process exited without a result")
        return {"ok": False, "error": err.info.model_dump(mode="json"), "features": []}, elapsed
    return json.loads(result_file.read_text(encoding="utf-8")), elapsed


def handle_cad(r: queue.Received) -> None:
    body = r.body
    job_id, attempt_no = body["job_id"], body["attempt"]
    with tx() as s:
        job = load(s, job_id)
        if job is None or job.state != "executing":
            return
        attempt = s.scalars(select(JobAttempt).where(JobAttempt.job_id == job_id, JobAttempt.number == attempt_no)).first()
        if attempt is None or attempt.status in ("ok", "failed"):
            return  # duplicate delivery of finished work
        recipe, tenant, project = dict(job.recipe), job.tenant_id, job.project_id
        kind = (job.input or {}).get("exec") if (job.input or {}).get("exec") in KIND_FILES else None
        options = {"freecad": bool((job.input or {}).get("freecad"))}
        is_export = job.kind == "export"
    if not _claim_lease(job_id):
        raise RuntimeError("job lease held by another worker")
    with tx() as s:
        s.execute(update(JobAttempt).where(JobAttempt.job_id == job_id, JobAttempt.number == attempt_no)
                  .values(status="running", worker=WORKER_ID, started_at=now()))
        transition_event(s, job_id, "attempt.started", {"attempt": attempt_no, "worker": WORKER_ID})

    staging_key = blobs.staging_prefix(tenant, project, job_id, attempt_no)
    # Build in a local directory (the blob directory itself locally, scratch space on Azure) and upload to the
    # staging prefix only when the geometry succeeded. Nothing is visible to users until finish() commits rows.
    with blobs.workdir(staging_key) as out_dir:
        cancel_flag = out_dir.parent / f"cancel-{attempt_no}.flag"
        stop = threading.Event()
        renewer = threading.Thread(target=_renew_loop, args=(r, job_id, stop, cancel_flag), daemon=True)
        renewer.start()
        reporter = threading.Thread(target=_progress_loop, args=(job_id, attempt_no, out_dir / kinds.PROGRESS_FILE, stop), daemon=True)
        reporter.start()
        try:
            result, cpu_s = run_geometry(recipe, out_dir, cancel_flag, kind, options)
        finally:
            stop.set()
            renewer.join(timeout=5)
            reporter.join(timeout=5)
        if result.get("ok") and not is_export:
            _stage_thumb(out_dir)
        if result.get("ok"):
            blobs.push_dir(out_dir, staging_key)
    finish(job_id, attempt_no, recipe, result, cpu_s, staging_key)


def _stage_thumb(out_dir: Path) -> None:
    """Render thumb.webp next to the staged geometry files. Best effort: a failure never fails the job."""
    try:
        thumbs.write_thumb(out_dir)
    except Exception:
        log.exception("thumbnail render failed; publishing without one")


def transition_event(s, job_id, type_, data):
    from ..jobs import emit

    job = load(s, job_id)
    emit(s, job, type_, data)


def finish(job_id: str, attempt_no: int, recipe: dict, result: dict, cpu_s: float, staging_key: str) -> None:
    ok = bool(result.get("ok"))
    error = result.get("error")
    with tx() as s:
        job = load(s, job_id)
        if job is None or job.state != "executing":
            return
        s.add(UsageEvent(tenant_id=job.tenant_id, job_id=job.id, kind="cad_cpu", cpu_seconds=cpu_s, detail={"attempt": attempt_no}))
        s.execute(update(JobAttempt).where(JobAttempt.job_id == job_id, JobAttempt.number == attempt_no)
                  .values(status="ok" if ok else "failed", finished_at=now(), error=error,
                          result={k: result.get(k) for k in ("features", "validation", "engine", "timings_ms", "parameters", "conversions")}))
        common = dict(lease_owner=None, lease_expires_at=None)

        if job.cancel_requested or (error or {}).get("code") == ErrorCode.CANCELLED.value:
            transition(s, job, "cancelled", **common, event_data={"discarded_attempt": attempt_no})
            return

        if not ok:
            used = dict(job.budget_used or {})
            direct = (job.input or {}).get("exec") in KIND_FILES  # a typed spec, no planner to repair it
            can_repair = not direct and (error or {}).get("retryable") and used.get("repair_calls", 0) < settings.budgets.repair_calls \
                and used.get("cad_executions", 0) < settings.budgets.cad_executions
            if can_repair:
                transition(s, job, "planning", **common, event="attempt.failed",
                           event_data={"attempt": attempt_no, "error": error, "next": "repair"},
                           outbox=("plan", {"job_id": job.id, "mode": "repair", "after_attempt": attempt_no}))
            else:
                transition(s, job, "failed", error=error, **common, event_data={"attempt": attempt_no, "error": error})
            return

        publish(s, job, attempt_no, recipe, result, staging_key, common)


def publish_export(s, job: Job, attempt_no: int, result: dict, staging_key: str, common: dict) -> None:
    """Attach a verified export derivative to an existing immutable version."""
    v = s.get(ModelVersion, job.input["export_of"])
    fmt = job.input["format"]
    kind = job.input.get("exec")
    name = KIND_FILES[kind][fmt] if kind in KIND_FILES else {"FCSTD": "model.FCStd"}[fmt]
    if not blobs.exists(f"{staging_key}/{name}"):
        checks = [c for c in (result.get("validation") or {}).get("checks", []) if c["name"].startswith("freecad")]
        notes = "; ".join(c.get("note") or c["name"] for c in checks if not c["passed"]) \
            or "; ".join((result.get("validation") or {}).get("notes", [])) or "the export produced no file"
        err = ShilpaError(ErrorCode.EXPORT_FAILED, f"{fmt} export failed: {notes}").info.model_dump(mode="json")
        transition(s, job, "failed", error=err, **common, event_data={"attempt": attempt_no, "error": err})
        return
    if s.scalars(select(Artifact).where(Artifact.version_id == v.id, Artifact.format == fmt)).first() is None:
        key = f"{blobs.version_prefix(job.tenant_id, job.project_id, v.id)}/{name}"
        blobs.copy(f"{staging_key}/{name}", key)
        sha = {a["format"]: a for a in result.get("artifacts", [])}
        s.add(Artifact(tenant_id=job.tenant_id, version_id=v.id, format=fmt, blob_key=key,
                       sha256=sha.get(fmt, {}).get("sha256") or "", bytes=blobs.size(key)))
    checks = [c for c in (result.get("validation") or {}).get("checks", []) if c["name"].startswith("freecad")]
    transition(s, job, "succeeded", result_version_id=v.id, **common,
               event_data={"version_id": v.id, "format": fmt, "attempt": attempt_no, "checks": len(checks)})


def publish(s, job: Job, attempt_no: int, recipe: dict, result: dict, staging_key: str, common: dict) -> None:
    """Atomic publication of an immutable version and its artifact manifest."""
    if job.kind == "export":
        publish_export(s, job, attempt_no, result, staging_key, common)
        return
    kind = (job.input or {}).get("exec") if (job.input or {}).get("exec") in KIND_FILES else None
    model = s.get(Model, job.model_id) if job.model_id else None
    if model is None:
        default = {"assembly": "Untitled assembly", "sheet_metal": "Untitled sheet-metal part", "product": "Untitled product"}
        model = Model(tenant_id=job.tenant_id, project_id=job.project_id, kind=kind or "part",
                      name=(job.input or {}).get("name") or result.get("name") or recipe.get("name") or default.get(kind, "Untitled part"))
        s.add(model)
        s.flush()
    elif job.base_version_id and model.head_version_id != job.base_version_id:
        err = ShilpaError(ErrorCode.INVALID_PARAMETER, "the model head moved while this edit ran; re-apply the edit on the latest version",
                          details={"conflict": True, "head_version_id": model.head_version_id}).info.model_dump(mode="json")
        transition(s, job, "failed", error=err, **common, event_data={"error": err})
        return

    version_id = str(uuid.uuid4())
    number = (s.scalar(select(ModelVersion.number).where(ModelVersion.model_id == model.id).order_by(ModelVersion.number.desc()).limit(1)) or 0) + 1
    vprefix = blobs.version_prefix(job.tenant_id, job.project_id, version_id)
    copied = []
    for fmt, name in (KIND_FILES[kind] if kind else PUBLISHED_FILES).items():
        src = f"{staging_key}/{name}"
        if blobs.exists(src):
            blobs.copy(src, f"{vprefix}/{name}")
            copied.append((fmt, name))
    sha = {a["format"]: a for a in result.get("artifacts", [])}
    validation = result.get("validation") or {}
    s.add(ModelVersion(id=version_id, tenant_id=job.tenant_id, model_id=model.id, number=number,
                       parent_version_id=job.base_version_id, job_id=job.id, recipe=recipe, recipe_hash=recipe_hash(recipe),
                       engine=result.get("engine") or {}, validation=validation,
                       validation_state="geometry_validated" if validation.get("passed", True) else "checks_failed",
                       change_summary=(job.input or {}).get("change_summary") or _auto_summary(job)))
    s.flush()  # version row before its artifact rows (same transaction)
    for fmt, name in copied:
        s.add(Artifact(tenant_id=job.tenant_id, version_id=version_id, format=fmt, blob_key=f"{vprefix}/{name}",
                       sha256=sha.get(fmt, {}).get("sha256") or "", bytes=blobs.size(f"{vprefix}/{name}")))
    res = s.execute(update(Model).where(Model.id == model.id, Model.head_revision == model.head_revision)
                    .values(head_version_id=version_id, head_revision=model.head_revision + 1))
    if res.rowcount != 1:
        raise StaleRevision("model head changed during publication")
    transition(s, job, "succeeded", model_id=model.id, result_version_id=version_id, **common,
               event_data={"version_id": version_id, "model_id": model.id, "number": number, "attempt": attempt_no})


def _auto_summary(job: Job) -> str | None:
    inp = job.input or {}
    if inp.get("parameters"):
        return "Parameter edit: " + ", ".join(f"{k} = {v:g}" for k, v in inp["parameters"].items())
    if inp.get("restore_of"):
        return f"Restored from version {inp['restore_of']}"
    return None


def run_once() -> bool:
    r = queue.receive("cad")
    if not r:
        return False
    try:
        handle_cad(r)
        queue.complete(r)
    except StaleRevision:
        queue.complete(r)
    except Exception:
        log.exception("cad handler crashed; message will be redelivered")
        queue.abandon(r)
    return True


def main(argv: list[str] | None = None) -> int:
    """``--once`` processes at most one message and returns 0 (also when the queue is empty); used by the Container Apps Job."""
    import argparse

    from .. import settings as cfg
    from ..logging_setup import configure_logging

    ap = argparse.ArgumentParser(prog="shilpa.workers.cad")
    ap.add_argument("--once", action="store_true", help="process at most one message, then exit 0")
    args = ap.parse_args(argv)
    cfg.enforce_startup()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")  # local: as before
    configure_logging(cfg.hosting.env, cfg.hosting.log_level)  # hosted: JSON + redaction replace it
    init_db()
    log.info("cad worker %s started%s", WORKER_ID, " (single run)" if args.once else "")
    if args.once:
        run_once()
        return 0
    while True:
        if not run_once():
            time.sleep(0.3)


if __name__ == "__main__":
    raise SystemExit(main())
