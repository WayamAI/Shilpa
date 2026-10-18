"""Job state machine (blueprint section 10).

PostgreSQL (SQLite locally) owns workflow state. Every transition is a compare-
and-swap on (state, state_revision) and writes its job event and any outbox
message in the same transaction. The model never owns state transitions.

  queued -> planning -> executing -> succeeded
                ^           |
                +-- repair -+-> failed
  any non-terminal -> cancelled
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select, update

from .db import Job, JobEvent, now
from .queue import enqueue_outbox

TERMINAL = {"succeeded", "failed", "cancelled"}


class StaleRevision(Exception):
    pass


def emit(s, job: Job, type_: str, data: dict | None = None) -> None:
    s.add(JobEvent(tenant_id=job.tenant_id, job_id=job.id, type=type_, data=data or {}))


def transition(s, job: Job, to_state: str, *, event: str | None = None, event_data: dict | None = None,
               outbox: tuple[str, dict] | None = None, **fields: Any) -> Job:
    """CAS update. Raises StaleRevision if another process moved the job first."""
    prev = job.state  # read before the UPDATE; the session synchronises the object afterwards
    res = s.execute(
        update(Job)
        .where(Job.id == job.id, Job.state == prev, Job.state_revision == job.state_revision)
        .values(state=to_state, state_revision=job.state_revision + 1, updated_at=now(), **fields)
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:
        raise StaleRevision(f"job {job.id} changed concurrently (expected {prev}@{job.state_revision})")
    job.state, job.state_revision = to_state, job.state_revision + 1
    for k, v in fields.items():
        setattr(job, k, v)
    emit(s, job, event or f"state.{to_state}", {"from": prev, "to": to_state, **(event_data or {})})
    if outbox:
        enqueue_outbox(s, *outbox)
    return job


def load(s, job_id: str) -> Job | None:
    return s.scalars(select(Job).where(Job.id == job_id)).first()


def new_budget_used() -> dict:
    return {"cad_executions": 0, "repair_calls": 0, "plan_calls": 0, "input_tokens": 0, "output_tokens": 0, "started_at": time.time()}
