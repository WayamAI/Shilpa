"""Coordinator process: outbox publisher, planner work and watchdog (blueprint section 5).

Run:  uv run python -m shilpa.coordinator
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta

from sqlalchemy import select

from . import queue
from .agent import planner
from .agent.llm import Budget, usage_totals
from .contracts.errors import ErrorCode, ShilpaError
from .db import Job, JobAttempt, ModelVersion, QueueMessage, Specification, UsageEvent, init_db, now, tx
from .jobs import TERMINAL, StaleRevision, emit, load, transition
from .contracts.hashing import recipe_hash
from .settings import settings

log = logging.getLogger("shilpa.coordinator")

# Static errors that mean the planner wrote a bad recipe (not that the user asked for one).
PLANNER_FIXABLE = {ErrorCode.INVALID_PARAMETER, ErrorCode.UNIT_MISMATCH, ErrorCode.REFERENCE_CYCLE}
# The job's first valid plan, kept in budget_used (internal, hidden by the API) for check_repair.
BASELINE_KEY = "_baseline_recipe"


def _budget(job: Job) -> Budget:
    b = settings.budgets
    used = job.budget_used or {}
    return Budget(
        input_tokens=b.input_tokens,
        output_tokens=b.output_tokens,
        deadline=used.get("started_at", time.time()) + b.elapsed_s,
        used_input=used.get("input_tokens", 0),
        used_output=used.get("output_tokens", 0),
    )


def _record_usage(s, job: Job, budget: Budget, used: dict) -> None:
    for c in budget.calls:
        s.add(UsageEvent(tenant_id=job.tenant_id, job_id=job.id, kind="llm", input_tokens=c["input_tokens"],
                         output_tokens=c["output_tokens"], detail=c))
    used["input_tokens"], used["output_tokens"] = budget.used_input, budget.used_output
    used.update(usage_totals(budget.calls, used))
    budget.calls.clear()


# Job kinds whose input is already a complete, typed spec: no planner, no repair loop.
DIRECT_KINDS = ("assembly", "sheet_metal", "product")


def exec_kind(job: Job) -> str | None:
    kind = (job.input or {}).get("exec")
    return kind if kind in DIRECT_KINDS else None


def check_direct(kind: str, spec) -> dict | None:
    """Static check of a direct job's spec before any CAD runs; returns an error dict or None."""
    from pydantic import ValidationError

    try:
        if kind == "assembly":
            from .contracts.assembly import AssemblySpec

            AssemblySpec.model_validate(spec)
        elif kind == "sheet_metal":
            from .sheetmetal import SheetMetalSpec

            SheetMetalSpec.model_validate(spec)
        elif kind == "product":
            from .workers.kinds import NOT_INSTALLED, product_runner

            if product_runner() is None:
                raise ShilpaError(ErrorCode.UNSUPPORTED_OPERATION, NOT_INSTALLED)
    except ValidationError as exc:
        e = exc.errors()[0]
        where = ".".join(str(x) for x in e.get("loc", ()))
        return ShilpaError(ErrorCode.INVALID_SCHEMA, f"{kind.replace('_', ' ')} spec is invalid at {where or 'top level'}: {e['msg']}"
                           ).info.model_dump(mode="json")
    except ShilpaError as exc:
        err = exc.info.model_dump(mode="json")
        err["retryable"] = False
        return err
    return None


def handle_direct(job_id: str) -> None:
    """queued -> planning -> executing for assembly, sheet-metal and product jobs (the spec is the plan)."""
    with tx() as s:
        job = load(s, job_id)
        if job is None or job.state in TERMINAL:
            return
        if job.cancel_requested:
            transition(s, job, "cancelled")
            return
        if job.state == "queued":
            transition(s, job, "planning")
        elif job.state != "planning":
            return
        kind, spec = exec_kind(job), (job.input or {}).get("spec")
        used = dict(job.budget_used or {})
        error = check_direct(kind, spec)
        if error is None and used.get("cad_executions", 0) >= settings.budgets.cad_executions:
            error = ShilpaError(ErrorCode.BUDGET_EXHAUSTED, "CAD execution budget exhausted").info.model_dump(mode="json")
        if error:
            transition(s, job, "failed", error=error, budget_used=used, event_data={"error": error})
            return
        n = used.get("cad_executions", 0) + 1
        used["cad_executions"] = n
        s.add(JobAttempt(tenant_id=job.tenant_id, job_id=job.id, number=n, recipe_hash=recipe_hash(spec or {}), status="queued"))
        detail = {"instances": len(spec.get("instances", []))} if kind == "assembly" else \
            {"flanges": len(spec.get("flanges", [])) + len(spec.get("hems", []))} if kind == "sheet_metal" else {}
        transition(s, job, "executing", recipe=spec, budget_used=used,
                   event_data={"attempt": n, "mode": "direct", "kind": kind, **detail},
                   outbox=("cad", {"job_id": job.id, "attempt": n, "tenant_id": job.tenant_id}))


def handle_plan(msg: dict) -> None:
    job_id = msg["job_id"]
    with tx() as s:
        job = load(s, job_id)
        if job is None or job.state in TERMINAL:
            return
        direct = exec_kind(job) is not None
    if direct:
        handle_direct(job_id)
        return
    with tx() as s:
        job = load(s, job_id)
        if job is None or job.state in TERMINAL:
            return
        if job.cancel_requested:
            transition(s, job, "cancelled")
            return
        if job.state == "queued":
            transition(s, job, "planning")
        elif job.state != "planning":
            return  # duplicate or stale delivery
        spec = s.get(Specification, job.specification_id) if job.specification_id else None
        base = s.get(ModelVersion, job.base_version_id) if job.base_version_id else None
        last_attempt = s.scalars(select(JobAttempt).where(JobAttempt.job_id == job.id).order_by(JobAttempt.number.desc())).first()
        snapshot = dict(kind=job.kind, input=dict(job.input or {}), recipe=job.recipe, used=dict(job.budget_used or {}),
                        spec=dict(spec.parsed) if spec else None, base_recipe=dict(base.recipe) if base else None,
                        last_error=last_attempt.error if last_attempt else None,
                        last_features=(last_attempt.result or {}).get("features") if last_attempt else None)
        budget = _budget(job)

    used = snapshot["used"]
    mode = msg.get("mode", "plan")
    recipe, error = None, None
    pending_error = snapshot["last_error"] if mode == "repair" else None
    current = snapshot["recipe"]
    first_summary = None
    feedback: str | None = None
    repaired = False

    while True:
        try:
            if pending_error is None:
                inp = snapshot["input"]
                if inp.get("recipe"):
                    recipe = dict(inp["recipe"])
                elif inp.get("parameters") and snapshot["base_recipe"]:
                    recipe = planner.apply_parameter_edit(snapshot["base_recipe"], inp["parameters"])
                elif inp.get("instruction") and snapshot["base_recipe"]:
                    used["plan_calls"] = used.get("plan_calls", 0) + 1
                    recipe = planner.edit_recipe(snapshot["base_recipe"], inp["instruction"], budget, feedback)
                elif snapshot["spec"]:
                    used["plan_calls"] = used.get("plan_calls", 0) + 1
                    recipe = planner.plan_recipe(snapshot["spec"], budget, feedback)
                else:
                    raise ShilpaError(ErrorCode.INTERNAL, "job has nothing to plan from")
            else:
                if used.get("repair_calls", 0) >= settings.budgets.repair_calls:
                    raise ShilpaError(ErrorCode.BUDGET_EXHAUSTED, "repair budget exhausted",
                                      details={"last_error": pending_error})
                used["repair_calls"] = used.get("repair_calls", 0) + 1
                recipe = planner.repair_recipe(current, pending_error, snapshot["last_features"], budget)
                repaired = True
                if snapshot["kind"] == "generate":
                    # Against the first valid plan, kept on the job, so repeated repairs cannot drift.
                    planner.check_repair(used.get(BASELINE_KEY) or current, recipe)
            # The user-facing summary describes the edit, not later internal repairs.
            first_summary = first_summary or recipe.get("_change_summary")
            recipe = planner.check_recipe(recipe)
            if snapshot["spec"] and snapshot["kind"] == "generate":
                planner.check_requirements(recipe, snapshot["spec"])
                if not repaired and BASELINE_KEY not in used:
                    used[BASELINE_KEY] = {k: v for k, v in recipe.items() if not k.startswith("_")}
            break
        except ShilpaError as exc:
            # A plan that fails static checks, or malformed model output, is retried within
            # the same shared repair budget (T027). Nothing untyped ever executes.
            planner_mistake = recipe is not None and exc.code in PLANNER_FIXABLE
            retry_ok = ((exc.info.retryable or planner_mistake) and exc.code != ErrorCode.BUDGET_EXHAUSTED
                        and used.get("repair_calls", 0) < settings.budgets.repair_calls)
            if retry_ok and recipe is not None:
                current, pending_error, recipe = recipe, exc.info.model_dump(mode="json"), None
                continue
            if retry_ok and recipe is None:
                if pending_error is None:
                    used["repair_calls"] = used.get("repair_calls", 0) + 1
                    feedback = exc.info.message  # tell the planner what was wrong with its output
                continue
            error = exc.info.model_dump(mode="json")
            break

    with tx() as s:
        job = load(s, job_id)
        if job is None or job.state != "planning":
            return
        _record_usage(s, job, budget, used)
        if job.cancel_requested:
            transition(s, job, "cancelled", budget_used=used)
            return
        if error:
            transition(s, job, "failed", error=error, budget_used=used, event_data={"error": error})
            return
        if used.get("cad_executions", 0) >= settings.budgets.cad_executions:
            err = ShilpaError(ErrorCode.BUDGET_EXHAUSTED, "CAD execution budget exhausted").info.model_dump(mode="json")
            transition(s, job, "failed", error=err, budget_used=used, event_data={"error": err})
            return
        summary = first_summary if mode == "plan" and first_summary else recipe.pop("_change_summary", None)
        recipe.pop("_change_summary", None)
        n = used.get("cad_executions", 0) + 1
        used["cad_executions"] = n
        s.add(JobAttempt(tenant_id=job.tenant_id, job_id=job.id, number=n, recipe_hash=recipe_hash(recipe), status="queued"))
        inp = dict(job.input or {})
        if summary:
            inp["change_summary"] = summary
        transition(s, job, "executing", recipe=recipe, budget_used=used, input=inp,
                   event_data={"attempt": n, "mode": mode, "change_summary": summary, "features": len(recipe["features"])},
                   outbox=("cad", {"job_id": job.id, "attempt": n, "tenant_id": job.tenant_id}))


def watchdog() -> None:
    """Fail jobs past their elapsed budget and jobs whose message was dead-lettered."""
    limit = now() - timedelta(seconds=settings.budgets.elapsed_s)
    with tx() as s:
        stale = s.scalars(select(Job).where(Job.state.not_in(TERMINAL), Job.created_at < limit)).all()
        dead = s.scalars(select(QueueMessage).where(QueueMessage.state == "dead")).all()
        dead_jobs = {m.body.get("job_id"): m.dead_reason for m in dead}
        for job in s.scalars(select(Job).where(Job.state.not_in(TERMINAL), Job.id.in_(list(dead_jobs)))).all():
            err = ShilpaError(ErrorCode.INTERNAL, f"work item dead-lettered: {dead_jobs[job.id]}").info.model_dump(mode="json")
            try:
                transition(s, job, "failed", error=err, event_data={"error": err})
            except StaleRevision:
                pass
        for job in stale:
            if job.state in TERMINAL:
                continue
            err = ShilpaError(ErrorCode.BUDGET_EXHAUSTED, "job exceeded its elapsed-time budget").info.model_dump(mode="json")
            try:
                transition(s, job, "failed", error=err, event_data={"error": err})
            except StaleRevision:
                pass


def run_once() -> bool:
    did = queue.publish_outbox() > 0
    r = queue.receive("plan")
    if r:
        did = True
        try:
            handle_plan(r.body)
            queue.complete(r)
        except StaleRevision:
            queue.complete(r)
        except Exception:
            log.exception("plan handler crashed; message will be redelivered")
            queue.abandon(r)
    return did


def main() -> None:
    from . import settings as cfg
    from .logging_setup import configure_logging

    cfg.enforce_startup()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")  # local: as before
    configure_logging(cfg.hosting.env, cfg.hosting.log_level)  # hosted: JSON + redaction replace it
    init_db()
    log.info("coordinator started (llm configured: %s)", settings.llm_configured)
    last_watch = 0.0
    while True:
        did = run_once()
        if time.time() - last_watch > 10:
            watchdog()
            last_watch = time.time()
        if not did:
            time.sleep(0.3)


if __name__ == "__main__":
    main()
