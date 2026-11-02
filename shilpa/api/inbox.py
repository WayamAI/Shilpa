"""The "Needs you" inbox: things in the caller's tenant that wait on a person.

Read only. Every query filters by the caller's verified tenant. Viewers see the same items; `can_act` tells
the client whether the caller may answer or retry (writes are enforced by the endpoints that do the work).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select

from ..db import Job, Model, Project, Specification, tx
from .auth import Principal, principal

router = APIRouter()

FAILED_WINDOW = timedelta(days=7)
SPEC_WINDOW = timedelta(days=30)
LIMIT = 100
PENDING_SPEC = {"needs_clarification": "clarification", "needs_review": "drawing_review"}
KIND_LABEL = {"part": "Part", "assembly": "Assembly", "sheet_metal": "Sheet metal", "product": "Product"}


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _spec_item(spec: Specification, proj: Project, can_act: bool) -> dict:
    req = spec.parsed or {}
    if spec.status == "needs_review":
        kind, title = "drawing_review", "Drawing values to confirm"
        detail = req.get("status_reason") or "Confirm the values read from the drawing before building."
    else:
        kind, title = "clarification", "Questions before building"
        questions = [m.get("question") for m in req.get("missing", []) if m.get("critical") and m.get("question")]
        conflicts = [c.get("description") for c in req.get("conflicts", []) if c.get("description")]
        notes = conflicts or questions
        detail = notes[0] if notes else "The planner needs more detail before it can build."
        if len(notes) > 1:
            detail += f" ({len(notes) - 1} more)"
    return {"id": f"spec:{spec.id}", "kind": kind, "project_id": proj.id, "project_name": proj.name, "model_id": None, "model_name": None,
            "title": title, "detail": detail, "created_at": spec.created_at.isoformat(), "can_act": can_act,
            "link": {"project_id": proj.id, "open": "specification", "specification_id": spec.id, "job_id": None}}


def _job_item(job: Job, proj: Project, model: Model | None, can_act: bool) -> dict:
    msg = (job.error or {}).get("message") or "The job stopped without a message."
    return {"id": f"job:{job.id}", "kind": "failed_build", "project_id": proj.id, "project_name": proj.name,
            "model_id": job.model_id, "model_name": model.name if model else None,
            "title": f"{KIND_LABEL.get(job.kind, 'Job')} build failed", "detail": msg,
            "created_at": _aware(job.updated_at).isoformat(), "can_act": can_act,
            "link": {"project_id": proj.id, "open": "job", "specification_id": job.specification_id, "job_id": job.id}}


@router.get("/v1/needs-you")
def needs_you(p: Principal = Depends(principal)):
    now = datetime.now(timezone.utc)
    items: list[dict] = []
    with tx() as s:
        projects = {x.id: x for x in s.scalars(select(Project).where(Project.tenant_id == p.tenant_id)).all()}
        models = {m.id: m for m in s.scalars(select(Model).where(Model.tenant_id == p.tenant_id)).all()}
        jobs = s.scalars(select(Job).where(Job.tenant_id == p.tenant_id).order_by(Job.created_at.desc())).all()
        run_specs = {j.specification_id for j in jobs if j.specification_id}

        specs = s.scalars(
            select(Specification).where(Specification.tenant_id == p.tenant_id, Specification.status.in_(list(PENDING_SPEC)),
                                        Specification.created_at >= now - SPEC_WINDOW)
        ).all()
        for spec in specs:
            if spec.id not in run_specs and spec.project_id in projects:
                items.append(_spec_item(spec, projects[spec.project_id], p.can_write))

        ok = [j for j in jobs if j.state == "succeeded"]
        for j in jobs:
            if j.state != "failed" or _aware(j.updated_at) < now - FAILED_WINDOW or j.project_id not in projects:
                continue
            at = _aware(j.created_at)
            superseded = any(
                _aware(o.created_at) > at
                and ((j.model_id is not None and o.model_id == j.model_id)
                     or (j.model_id is None and j.specification_id is not None and o.specification_id == j.specification_id))
                for o in ok
            )
            if not superseded:
                items.append(_job_item(j, projects[j.project_id], models.get(j.model_id) if j.model_id else None, p.can_write))
    items.sort(key=lambda i: i["created_at"], reverse=True)
    items = items[:LIMIT]
    return {"count": len(items), "items": items}
