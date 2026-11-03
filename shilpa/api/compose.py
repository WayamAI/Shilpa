"""Composition API (Shilpa Composition Language, spec 8.2): create, interpret, apply, steps.

* ``POST /v1/compositions`` creates an empty composition in a project.
* ``POST /v1/compositions/{id}/interpret`` builds nothing. It resolves @-mentions, asks the composer
  model for IR (only when the client did not send ``steps``), expands and checks the IR, and returns the
  interpretation card: reading, counts, normalised units, assumptions, blockers. Sending ``steps`` back
  (with ``answers``, the patches of the options the user picked) re-interprets without any model call.
* ``POST /v1/compositions/{id}/apply`` re-runs the deterministic interpretation, refuses on blockers,
  lowers the whole composition to an ``AssemblySpec`` and enqueues the existing assembly job through the
  outbox. It appends a step (``pending``); the step becomes ``applied`` with its version when the job
  succeeds (``failed`` otherwise). Idempotency keys work as on other job endpoints.
* ``GET /v1/compositions/{id}`` and ``/steps`` read the history (viewers may read; only writers interpret
  or apply). Every query filters by the caller's tenant; another tenant's ids answer 404.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..contracts.composition import Patch, Step
from ..db import Composition, CompositionStep, Job, Model, ModelVersion, Project, UsageEvent, now, tx
from .auth import Principal, principal, require_write

router = APIRouter()
MAX_PROMPT = 4000


def _err(status: int, code: str, message: str, **extra) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message, **extra})


# ---------------------------------------------------------------- models


class CompositionIn(BaseModel):
    project_id: str = Field(min_length=1, max_length=36)
    name: str = Field(default="Untitled composition", min_length=1, max_length=200)


class InterpretIn(BaseModel):
    prompt: str = Field(default="", max_length=MAX_PROMPT)
    mentions: list[dict[str, Any]] = Field(default_factory=list, max_length=32)  # pinned chips (spec 2.2)
    steps: list[dict[str, Any]] | None = Field(default=None, max_length=50)  # IR to re-interpret (no model call)
    answers: list[dict[str, Any]] = Field(default_factory=list, max_length=20)  # option patches the user picked


class ApplyIn(BaseModel):
    prompt: str = Field(default="", max_length=MAX_PROMPT)
    steps: list[dict[str, Any]] = Field(min_length=1, max_length=50)
    base_version_id: str | None = None
    spec_hash: str | None = Field(default=None, max_length=64)  # the card's hash: 409 when the interpretation changed
    idempotency_key: str | None = Field(default=None, max_length=100)


# ---------------------------------------------------------------- helpers


def _composition(s, p: Principal, cid: str) -> Composition:
    c = s.get(Composition, cid)
    if c is None or c.tenant_id != p.tenant_id:
        raise _err(404, "not_found", "composition not found")
    return c


def _sync(s, comp: Composition) -> None:
    """Move pending steps forward from their jobs (append-only history; only status changes)."""
    pending = s.scalars(select(CompositionStep).where(CompositionStep.composition_id == comp.id,
                                                      CompositionStep.status == "pending")).all()
    for st in pending:
        job = s.get(Job, st.job_id)
        if job is None or job.state not in ("succeeded", "failed", "cancelled"):
            continue
        st.finished_at = now()
        if job.state == "succeeded" and job.result_version_id:
            st.status, st.result_version_id = "applied", job.result_version_id
            comp.model_id = comp.model_id or job.model_id
            comp.head_version_id = job.result_version_id
        else:
            st.status = "failed"


def _steps(s, comp: Composition, status: str | None = None) -> list[CompositionStep]:
    q = select(CompositionStep).where(CompositionStep.composition_id == comp.id, CompositionStep.tenant_id == comp.tenant_id)
    if status:
        q = q.where(CompositionStep.status == status)
    return list(s.scalars(q.order_by(CompositionStep.number)).all())


def _applied_ir(rows: list[CompositionStep]) -> list[Step]:
    return [Step.model_validate(d) for r in rows for d in r.ir.get("steps", [])]


def _library(s, p: Principal, applied: list[Step], extra_steps: list[dict] | None = None):
    """The tenant's library: head versions of its single-part models, plus versions pinned by applied steps.

    [Assumption] spec 8.4: one tenant library; every single-part model in any of the tenant's projects is in it.
    """
    from ..compose.resolve import Library, NativeItem

    rows = s.execute(select(Model, ModelVersion).join(ModelVersion, ModelVersion.id == Model.head_version_id)
                     .where(Model.tenant_id == p.tenant_id, ModelVersion.tenant_id == p.tenant_id,
                            (Model.kind == "part") | (Model.kind.is_(None)))
                     .order_by(Model.created_at, Model.id)).all()
    natives = [NativeItem(m.id, m.name, v.id, v.recipe) for m, v in rows]
    lib = Library(natives)
    lib.other_kinds = dict(s.execute(select(Model.id, Model.kind).where(
        Model.tenant_id == p.tenant_id, Model.kind.is_not(None), Model.kind != "part")).all())
    have = {n.version_id for n in natives}
    wanted = set()
    for st in applied:
        for r in (st.source, st.target):
            if r is not None and r.source == "native" and r.version and r.version not in have:
                wanted.add(r.version)
    for d in extra_steps or []:
        for k in ("source", "target"):
            r = d.get(k) if isinstance(d, dict) else None
            if isinstance(r, dict) and r.get("source") == "native" and r.get("version") and r["version"] not in have:
                wanted.add(str(r["version"])[:80])
    for vid in sorted(wanted):
        v = s.get(ModelVersion, vid)
        if v is None or v.tenant_id != p.tenant_id:
            continue  # unknown or another tenant's: the reference stays unresolved and is reported
        m = s.get(Model, v.model_id)
        lib.pinned[v.id] = NativeItem(m.id, m.name, v.id, v.recipe)
    return lib


def _parse_steps(raw: list[dict]) -> list[Step]:
    try:
        return [Step.model_validate(d) for d in raw]
    except ValidationError as exc:
        e = exc.errors()[0]
        raise _err(422, "invalid_ir", f"step {'.'.join(str(x) for x in e.get('loc', ()))}: {e['msg']}") from None


def _step_out(st: CompositionStep) -> dict:
    card = st.interpretation or {}
    return {"id": st.id, "number": st.number, "prompt": st.prompt, "status": st.status, "job_id": st.job_id,
            "base_version_id": st.base_version_id, "result_version_id": st.result_version_id, "spec_hash": st.spec_hash,
            "ir": st.ir, "reading": card.get("reading"), "counts": card.get("counts"), "warnings": card.get("warnings", []),
            "assumptions": card.get("assumptions", []), "created_at": st.created_at.isoformat(),
            "finished_at": st.finished_at.isoformat() if st.finished_at else None}


def _comp_out(s, comp: Composition) -> dict:
    rows = _steps(s, comp)
    return {"id": comp.id, "project_id": comp.project_id, "name": comp.name, "model_id": comp.model_id,
            "head_version_id": comp.head_version_id, "created_at": comp.created_at.isoformat(),
            "step_count": len(rows), "applied_steps": sum(r.status == "applied" for r in rows),
            "pending": any(r.status == "pending" for r in rows)}


# ---------------------------------------------------------------- routes


@router.post("/v1/compositions", status_code=201)
def create_composition(body: CompositionIn, p: Principal = Depends(principal)):
    require_write(p)
    with tx() as s:
        proj = s.get(Project, body.project_id)
        if proj is None or proj.tenant_id != p.tenant_id:
            raise _err(404, "not_found", "project not found")
        comp = Composition(tenant_id=p.tenant_id, project_id=proj.id, name=body.name, created_by=p.user_id)
        s.add(comp)
        s.flush()
        from .app import _audit

        _audit(s, p, f"composition:{comp.id}", "create")
        return _comp_out(s, comp)


@router.get("/v1/compositions/{cid}")
def get_composition(cid: str, p: Principal = Depends(principal)):
    with tx() as s:
        comp = _composition(s, p, cid)
        _sync(s, comp)
        return _comp_out(s, comp)


@router.get("/v1/projects/{project_id}/compositions")
def list_compositions(project_id: str, p: Principal = Depends(principal)):
    with tx() as s:
        proj = s.get(Project, project_id)
        if proj is None or proj.tenant_id != p.tenant_id:
            raise _err(404, "not_found", "project not found")
        comps = s.scalars(select(Composition).where(Composition.project_id == project_id, Composition.tenant_id == p.tenant_id)
                          .order_by(Composition.created_at.desc())).all()
        return [_comp_out(s, c) for c in comps]


@router.get("/v1/compositions/{cid}/steps")
def list_steps(cid: str, p: Principal = Depends(principal)):
    with tx() as s:
        comp = _composition(s, p, cid)
        _sync(s, comp)
        return [_step_out(r) for r in _steps(s, comp)]


@router.post("/v1/compositions/{cid}/interpret")
def interpret_prompt(cid: str, body: InterpretIn, p: Principal = Depends(principal)):
    """The interpretation card. Builds nothing; calls the composer model only when ``steps`` is absent."""
    from ..agent import composer
    from ..agent.llm import ensure_enabled, usage_totals
    from ..compose import mentions as mp
    from ..compose.expand import Expander
    from ..compose.interpret import interpret, renumber
    from ..compose.resolve import resolve_prompt

    require_write(p)
    if body.steps is None and not body.prompt.strip():
        raise _err(400, "bad_request", "give a prompt, or steps to re-interpret")
    try:
        pins = mp.pin_map(body.mentions)
        answers = [Patch.model_validate(a).model_dump() for a in body.answers]
    except (ValueError, ValidationError) as exc:
        raise _err(422, "invalid_mention", str(exc)[:300]) from None
    with tx() as s:
        comp = _composition(s, p, cid)
        _sync(s, comp)
        applied = _applied_ir(_steps(s, comp, "applied"))
        lib = _library(s, p, applied, body.steps)
        comp_id, name, head = comp.id, comp.name, comp.head_version_id

    prog, _ = Expander(lib).run(applied, set())
    resolutions, errors = resolve_prompt(body.prompt, lib, prog.instances, pins)
    llm_info: dict = {"used": False}
    if body.steps is not None:
        new = _parse_steps(body.steps)
    else:
        ensure_enabled()  # 503 planner_disabled with SHILPA_LLM=off (a fake client in tests is allowed)
        table = []
        for r in resolutions:
            row = {"id": r.mention, "text": r.text, "status": r.status, "label": r.label, "message": r.message}
            if r.status == "ok" and r.ref is not None:
                row["kind"] = r.ref.source
                try:
                    part = prog.part_of(r.ref.instance) if r.ref.source == "instance" else lib.part(r.ref)
                    row["summary"] = part.summary()
                except Exception:  # noqa: BLE001 - the expander reports it with context
                    row["summary"] = None
            table.append(row)
        state = {"instances": [{"id": i.id, "part": i.label, "grounded": i.grounded} for i in prog.instances.values()]}
        budget = composer.new_budget()
        try:
            new = composer.compose(body.prompt, table, state, budget)
        finally:
            if budget.calls:
                with tx() as s:
                    for c in budget.calls:
                        s.add(UsageEvent(tenant_id=p.tenant_id, job_id=None, kind="llm", input_tokens=c["input_tokens"],
                                         output_tokens=c["output_tokens"], detail={**c, "composition_id": comp_id}))
        new = renumber(new, applied)
        for st in new:
            st.prompt = st.prompt or body.prompt
        llm_info = {"used": True, "purpose": composer.PURPOSE, **usage_totals(budget.calls)}
    return interpret(composition_id=comp_id, name=name, library=lib, applied=applied, new=new, resolutions=resolutions,
                     mention_errors=errors, base_version=head, answers=answers or None, llm=llm_info)


@router.post("/v1/compositions/{cid}/apply", status_code=202)
def apply_steps(cid: str, body: ApplyIn, p: Principal = Depends(principal), idempotency_key: str | None = Header(default=None)):
    """Re-interpret ``steps`` deterministically (no model), then enqueue the assembly job and append a step."""
    from ..compose.interpret import interpret
    from . import app as api

    require_write(p)
    key = idempotency_key or body.idempotency_key or uuid.uuid4().hex
    job_key = f"compose:{cid}:{key}"[:128]
    new = _parse_steps(body.steps)

    def existing():
        with tx() as s:
            comp = _composition(s, p, cid)
            job = s.scalars(select(Job).where(Job.tenant_id == p.tenant_id, Job.idempotency_key == job_key)).first()
            if job is None:
                return None
            st = s.scalars(select(CompositionStep).where(CompositionStep.job_id == job.id,
                                                         CompositionStep.composition_id == comp.id)).first()
            return {"step": _step_out(st), "job": api._job_out(job)} if st else None

    prior = existing()
    if prior is not None:
        return prior

    with tx() as s:
        comp = _composition(s, p, cid)
        _sync(s, comp)
        if _steps(s, comp, "pending"):
            raise _err(409, "step_running", "the previous step is still being built; wait for it to finish")
        if body.base_version_id != comp.head_version_id:
            raise _err(409, "stale_revision", "base_version_id is not the composition's current version",
                       head_version_id=comp.head_version_id)
        applied = _applied_ir(_steps(s, comp, "applied"))
        lib = _library(s, p, applied, body.steps)
        comp_id, name, head, project_id, model_id = comp.id, comp.name, comp.head_version_id, comp.project_id, comp.model_id
    taken = {st.id for st in applied}
    if any(st.id in taken for st in new):
        raise _err(422, "invalid_ir", "step ids collide with applied steps; interpret again to renumber them")
    card = interpret(composition_id=comp_id, name=name, library=lib, applied=applied, new=new, base_version=head)
    if card["status"] != "ready":
        raise _err(422, "blocked", "the interpretation has open questions; answer them before applying",
                   blockers=card["blockers"])
    if body.spec_hash and body.spec_hash != card["spec_hash"]:
        raise _err(409, "interpretation_changed", "the parts or the composition changed since this was interpreted; "
                   "interpret again", spec_hash=card["spec_hash"])
    from ..coordinator import check_direct

    bad = check_direct("assembly", card["spec"])
    if bad:
        raise _err(422, bad["code"], bad["message"])

    def go():
        with tx() as s:
            comp = _composition(s, p, cid)
            if comp.head_version_id != head:
                raise _err(409, "stale_revision", "the composition moved on while this was checked", head_version_id=comp.head_version_id)
            number = (s.scalar(select(func.max(CompositionStep.number)).where(CompositionStep.composition_id == comp.id)) or 0) + 1
            summary = f"Composition step {number}: {body.prompt or card['reading']}"[:500]
            inp = {"exec": "assembly", "spec": card["spec"], "freecad": False, "name": name, "change_summary": summary,
                   "composition_id": comp.id}
            job, created = api._create_job(s, p, project_id=project_id, kind="assembly", key=job_key, input=inp,
                                           model_id=model_id, base_version_id=head)
            if not created:
                return None
            st = CompositionStep(tenant_id=p.tenant_id, composition_id=comp.id, number=number, prompt=body.prompt,
                                 ir={"steps": card["steps"]}, interpretation={k: v for k, v in card.items() if k not in ("spec", "ir")},
                                 spec_hash=card["spec_hash"], base_version_id=head, job_id=job.id, status="pending",
                                 created_by=p.user_id)
            s.add(st)
            s.flush()
            api._audit(s, p, f"composition:{comp.id}", "apply", {"step": number, "job_id": job.id})
            return {"step": _step_out(st), "job": api._job_out(job)}

    try:
        out = go()
    except IntegrityError:
        out = None
    if out is None:
        out = existing()
        if out is None:
            raise _err(409, "conflict", "a concurrent apply won; reload the composition")
    return out
