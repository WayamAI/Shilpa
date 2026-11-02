"""Shilpa REST API, /v1 (blueprint section 15).

Run:  uv run uvicorn shilpa.api.app:app --port 8000
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sse_starlette.sse import EventSourceResponse

from ..adapters import CAPABILITY_MATRIX
from ..agent import planner, router
from ..agent.llm import Budget, PlannerDisabled, ensure_enabled
from ..agent.llm import usage_totals as llm_usage_totals
from ..contracts.errors import ErrorCode, ShilpaError
from ..db import (
    Artifact,
    AuditEvent,
    Job,
    JobAttempt,
    JobEvent,
    Model,
    ModelVersion,
    Project,
    Specification,
    Upload,
    UsageEvent,
    init_db,
    tx,
)
from ..jobs import TERMINAL, emit, new_budget_used, transition
from ..queue import enqueue_outbox
from ..settings import settings
from ..storage import blobs
from .auth import Principal, principal, require_write, seed_dev_identities


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    if settings.auth_mode == "dev":
        seed_dev_identities()
    yield


app = FastAPI(title="Shilpa API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3100", "http://127.0.0.1:3100"],
                   allow_methods=["*"], allow_headers=["*"], expose_headers=["*"])


def _err(status: int, code: str, message: str, **extra) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message, **extra})


@app.exception_handler(ShilpaError)
async def _shilpa_error(request: Request, exc: ShilpaError):
    status = 422
    if isinstance(exc, PlannerDisabled):
        body = exc.info.model_dump(mode="json")
        body["code"] = "planner_disabled"
        body["trace_id"] = request.headers.get("x-trace-id") or uuid.uuid4().hex
        return JSONResponse(status_code=503, content=body)
    if exc.code in (ErrorCode.MODEL_TIMEOUT,):
        status = 504
    elif exc.code in (ErrorCode.INTERNAL,):
        status = 502
    body = exc.info.model_dump(mode="json")
    body["trace_id"] = request.headers.get("x-trace-id") or uuid.uuid4().hex
    return JSONResponse(status_code=status, content=body)


@app.exception_handler(HTTPException)
async def _http_error(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"code": "error", "message": str(exc.detail)}
    detail.setdefault("retryable", False)
    detail["trace_id"] = request.headers.get("x-trace-id") or uuid.uuid4().hex
    return JSONResponse(status_code=exc.status_code, content=detail)


def _audit(s, p: Principal, obj: str, action: str, meta: dict | None = None) -> None:
    s.add(AuditEvent(tenant_id=p.tenant_id, actor=p.user_id, object=obj, action=action, meta=meta or {}))


def _project(s, p: Principal, project_id: str) -> Project:
    proj = s.get(Project, project_id)
    if proj is None or proj.tenant_id != p.tenant_id:
        raise _err(404, "not_found", "project not found")
    return proj


def _owned(s, p: Principal, cls, obj_id: str, what: str):
    obj = s.get(cls, obj_id)
    if obj is None or obj.tenant_id != p.tenant_id:
        raise _err(404, "not_found", f"{what} not found")
    return obj


# ---------------------------------------------------------------- meta


@app.get("/v1/health")
def health():
    from ..adapters import freecad_adapter
    from ..workers.kinds import product_runner

    return {"ok": True, "llm_configured": settings.llm_configured, "auth_mode": settings.auth_mode,
            "planner": settings.planner_status, "llm_enabled": settings.llm_enabled,
            "llm_deployment": (settings.llm_model or None) if settings.llm_enabled else None,
            "llm_provider": settings.llm_provider if settings.llm_enabled else None,
            "freecad_available": freecad_adapter.available(),
            "products_available": product_runner() is not None,
            "job_kinds": ["part", "assembly", "sheet_metal", "product"],
            "adapters": {k: sorted(v["operations"]) for k, v in CAPABILITY_MATRIX.items()}}


@app.get("/v1/starters")
def starters(p: Principal = Depends(principal)):
    """Reference assemblies (the golden set) and sheet-metal examples; none needs the planner."""
    from ..workers.kinds import product_runner
    from .starters import assembly_starters, product_starters, sheet_metal_starters

    available = product_runner() is not None
    return {"assemblies": assembly_starters(), "sheet_metal": sheet_metal_starters(),
            "products": product_starters() if available else [], "products_available": available}


class RouteIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)


@app.post("/v1/route")
def route_request(body: RouteIn, p: Principal = Depends(principal)):
    """Classify a request as part | sheet_metal | assembly | product, or explain why it is unsupported.

    Rule-based first; the model classifier is only used for unsure requests and only when the
    planner is enabled (never with SHILPA_LLM=off)."""
    b = settings.budgets
    budget = Budget(input_tokens=min(b.input_tokens, 4000), output_tokens=min(b.output_tokens, 400), deadline=time.time() + 30)
    r = router.classify(body.prompt, budget if settings.llm_configured else None)
    if budget.calls:
        with tx() as s:
            for c in budget.calls:
                s.add(UsageEvent(tenant_id=p.tenant_id, job_id=None, kind="llm", input_tokens=c["input_tokens"],
                                 output_tokens=c["output_tokens"], detail=c))
    return {**r.to_dict(), "planner": settings.planner_status}


class CatalogPartIn(BaseModel):
    generator: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


@app.get("/v1/catalog")
def catalog(p: Principal = Depends(principal)):
    """Every standard-part generator with its family and JSON parameter schema."""
    from ..catalog.preview import browse

    return browse()


@app.get("/v1/catalog/lookup")
def catalog_lookup(q: str = "", p: Principal = Depends(principal)):
    """Typed part names ("M6x20 socket head", "6204-2RS", "DIN 125 M8") to catalog parts, rule-based."""
    from ..catalog.designations import lookup

    return {"query": q, "matches": lookup(q[:200]) if q.strip() else []}


@app.post("/v1/catalog/preview")
def catalog_preview(body: CatalogPartIn, p: Principal = Depends(principal)):
    """Build one catalog part now (no job: these build in about a second) and return its mesh, ports and data."""
    from ..catalog.preview import preview

    return preview(body.generator, body.params)


@app.post("/v1/catalog/step")
def catalog_step(body: CatalogPartIn, p: Principal = Depends(principal)):
    from fastapi.responses import Response

    from ..catalog.preview import step

    data, name = step(body.generator, body.params)
    return Response(data, media_type="application/step", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/v1/examples")
def examples(p: Principal = Depends(principal)):
    """Golden reference recipes, offered in the studio as starting points."""
    out = []
    for path in sorted(planner.CORPUS.glob("*.json")):
        fx = json.loads(path.read_text(encoding="utf-8"))
        out.append({"id": fx["id"], "family": fx["family"], "description": fx["description"], "recipe": fx["recipe"]})
    return out


@app.get("/v1/me")
def me(p: Principal = Depends(principal)):
    return {"user_id": p.user_id, "email": p.email, "name": p.name, "tenant_id": p.tenant_id,
            "tenant_name": p.tenant_name, "role": p.role, "can_write": p.can_write}


# ---------------------------------------------------------------- projects


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


def _project_out(proj: Project, models: int = 0) -> dict:
    return {"id": proj.id, "name": proj.name, "created_at": proj.created_at.isoformat(), "model_count": models}


@app.post("/v1/projects", status_code=201)
def create_project(body: ProjectIn, p: Principal = Depends(principal)):
    require_write(p)
    with tx() as s:
        proj = Project(tenant_id=p.tenant_id, name=body.name, created_by=p.user_id)
        s.add(proj)
        s.flush()
        _audit(s, p, f"project:{proj.id}", "create")
        return _project_out(proj)


@app.get("/v1/projects")
def list_projects(q: str | None = None, p: Principal = Depends(principal)):
    with tx() as s:
        stmt = select(Project).where(Project.tenant_id == p.tenant_id).order_by(Project.created_at.desc())
        if q:
            stmt = stmt.where(Project.name.ilike(f"%{q}%"))
        projects = s.scalars(stmt).all()
        counts = dict(s.execute(select(Model.project_id, func.count()).where(Model.tenant_id == p.tenant_id).group_by(Model.project_id)).all())
        return [_project_out(x, counts.get(x.id, 0)) for x in projects]


@app.get("/v1/projects/{project_id}")
def get_project(project_id: str, p: Principal = Depends(principal)):
    with tx() as s:
        proj = _project(s, p, project_id)
        models = s.scalars(select(Model).where(Model.project_id == proj.id, Model.tenant_id == p.tenant_id).order_by(Model.created_at.desc())).all()
        jobs = s.scalars(select(Job).where(Job.project_id == proj.id, Job.tenant_id == p.tenant_id).order_by(Job.created_at.desc()).limit(20)).all()
        return {**_project_out(proj, len(models)), "models": [_model_out(s, m) for m in models], "recent_jobs": [_job_out(j) for j in jobs]}


# ---------------------------------------------------------------- uploads (drawings)


def _upload_out(u: Upload) -> dict:
    pages = (u.pages or {}).get("pages", [])
    return {"id": u.id, "project_id": u.project_id, "filename": u.filename, "media_type": u.media_type, "bytes": u.bytes,
            "sha256": u.sha256, "state": u.state, "error": u.error, "has_text_layer": (u.pages or {}).get("has_text_layer"),
            "pages": [{"number": pg["number"], "width_px": pg["width_px"], "height_px": pg["height_px"]} for pg in pages],
            "created_at": u.created_at.isoformat()}


@app.post("/v1/projects/{project_id}/uploads", status_code=201)
def create_upload(project_id: str, file: UploadFile = File(...), p: Principal = Depends(principal)):
    """Quarantine an uploaded drawing, then parse it in a separate restricted process."""
    import hashlib
    import subprocess
    import sys

    from ..drawings.ingest import MAX_BYTES
    from ..settings import ROOT
    from ..workers.cad import _scrubbed_env

    require_write(p)
    with tx() as s:
        _project(s, p, project_id)
    data = file.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise _err(413, "too_large", f"uploads are limited to {MAX_BYTES // (1024 * 1024)} MB")
    upload_id = str(uuid.uuid4())
    prefix = f"tenants/{p.tenant_id}/projects/{project_id}/uploads/{upload_id}"
    original = blobs.path(f"{prefix}/original.bin")  # never the client's file name: no path tricks
    original.parent.mkdir(parents=True, exist_ok=True)
    original.write_bytes(data)
    base = (file.filename or "drawing").replace("\\", "/").rsplit("/", 1)[-1]  # display only; never a path
    safe_name = "".join(ch for ch in base[-120:] if ch.isalnum() or ch in "._- ").lstrip(". ") or "drawing"
    with tx() as s:
        s.add(Upload(id=upload_id, tenant_id=p.tenant_id, project_id=project_id, filename=safe_name,
                     sha256=hashlib.sha256(data).hexdigest(), bytes=len(data), state="quarantined", blob_prefix=prefix,
                     created_by=p.user_id))
    out = blobs.path(f"{prefix}/pages")
    try:
        subprocess.run([sys.executable, "-E", "-s", "-m", "shilpa.drawings.ingest", str(original), str(out)], cwd=str(ROOT),
                       env=_scrubbed_env(), timeout=90, capture_output=True, check=False)
        result = json.loads((out / "ingest.json").read_text(encoding="utf-8"))
    except Exception as exc:  # timeout or crash in the parser process
        result = {"ok": False, "error": f"the file could not be processed ({type(exc).__name__})"}
    with tx() as s:
        u = s.get(Upload, upload_id)
        if result.get("ok"):
            u.state, u.media_type, u.pages = "ready", result["media_type"], result
        else:
            u.state, u.error = "rejected", result.get("error")
        _audit(s, p, f"upload:{u.id}", "create", {"state": u.state, "bytes": u.bytes})
        out_u = _upload_out(u)
    if out_u["state"] == "rejected":
        raise _err(422, "upload_rejected", out_u["error"] or "rejected", upload_id=upload_id)
    return out_u


@app.get("/v1/uploads/{upload_id}")
def get_upload(upload_id: str, p: Principal = Depends(principal)):
    with tx() as s:
        return _upload_out(_owned(s, p, Upload, upload_id, "upload"))


@app.get("/v1/uploads/{upload_id}/pages/{number}")
def upload_page(upload_id: str, number: int, p: Principal = Depends(principal)):
    with tx() as s:
        u = _owned(s, p, Upload, upload_id, "upload")
        if u.state != "ready" or not 1 <= number <= len(u.pages["pages"]):
            raise _err(404, "not_found", "page not found")
        path = blobs.path(f"{u.blob_prefix}/pages/page-{number}.png")
    return FileResponse(path, media_type="image/png")


# ---------------------------------------------------------------- specifications


class SpecIn(BaseModel):
    prompt: str | None = Field(default=None, max_length=8000)
    upload_id: str | None = None


class SpecPatch(BaseModel):
    revision: int
    answers: dict[str, float] = Field(default_factory=dict)
    resolved_conflicts: bool = False
    confirm_drawing: bool = False


def _spec_out(spec: Specification) -> dict:
    return {"id": spec.id, "project_id": spec.project_id, "prompt": spec.prompt, "status": spec.status,
            "revision": spec.revision, "requirements": spec.parsed, "upload_id": spec.upload_id,
            "created_at": spec.created_at.isoformat()}


@app.post("/v1/projects/{project_id}/specifications", status_code=201)
def create_specification(project_id: str, body: SpecIn, p: Principal = Depends(principal)):
    require_write(p)
    if not body.upload_id and not (body.prompt and len(body.prompt.strip()) >= 3):
        raise _err(400, "bad_request", "give a prompt, an upload_id, or both")
    ensure_enabled()  # 503 planner_disabled with SHILPA_LLM=off: reading language and drawings needs the model
    upload = None
    with tx() as s:
        _project(s, p, project_id)
        if body.upload_id:
            upload = _owned(s, p, Upload, body.upload_id, "upload")
            if upload.project_id != project_id or upload.state != "ready":
                raise _err(422, "upload_not_ready", f"upload is {upload.state}")
            ingested, page_dir = dict(upload.pages), blobs.path(f"{upload.blob_prefix}/pages")
    b = settings.budgets
    budget = Budget(input_tokens=b.input_tokens, output_tokens=b.output_tokens, deadline=time.time() + 180)
    t0 = time.time()
    if upload is not None:
        from ..drawings.extract import extract, to_requirements

        req = to_requirements(extract(ingested, page_dir, budget, body.prompt))
    else:
        req = planner.extract_requirements(body.prompt, budget)
    req["_usage"] = {"input_tokens": budget.used_input, "output_tokens": budget.used_output, "ms": round((time.time() - t0) * 1000),
                     **llm_usage_totals(budget.calls)}
    with tx() as s:
        for c in budget.calls:
            s.add(UsageEvent(tenant_id=p.tenant_id, job_id=None, kind="llm", input_tokens=c["input_tokens"],
                             output_tokens=c["output_tokens"], detail=c))
        spec = Specification(tenant_id=p.tenant_id, project_id=project_id, prompt=body.prompt or "", parsed=req,
                             status=req["status"], upload_id=body.upload_id)
        s.add(spec)
        s.flush()
        _audit(s, p, f"specification:{spec.id}", "create", {"status": spec.status})
        return _spec_out(spec)


@app.get("/v1/specifications/{spec_id}")
def get_specification(spec_id: str, p: Principal = Depends(principal)):
    with tx() as s:
        return _spec_out(_owned(s, p, Specification, spec_id, "specification"))


@app.patch("/v1/specifications/{spec_id}")
def patch_specification(spec_id: str, body: SpecPatch, p: Principal = Depends(principal)):
    require_write(p)
    with tx() as s:
        spec = _owned(s, p, Specification, spec_id, "specification")
        if spec.revision != body.revision:
            raise _err(409, "stale_revision", f"specification is at revision {spec.revision}", current_revision=spec.revision)
        parsed = dict(spec.parsed)
        if parsed.get("source") == "drawing":
            from ..drawings.extract import confirm

            if body.resolved_conflicts:
                parsed["conflicts"] = []
            if body.confirm_drawing:
                req = confirm(parsed, body.answers)
            else:  # answering a question without confirming the sheet keeps it under review
                drawing, source = parsed.pop("drawing"), parsed.pop("source")
                req = planner.answer_clarifications(parsed, body.answers, body.resolved_conflicts)
                req["drawing"], req["source"] = drawing, source
                if req["status"] == "ready":
                    req["status"], req["status_reason"] = "needs_review", "confirm the values read from the drawing"
        else:
            req = planner.answer_clarifications(parsed, body.answers, body.resolved_conflicts)
        spec.parsed, spec.status, spec.revision = req, req["status"], spec.revision + 1
        _audit(s, p, f"specification:{spec.id}", "answer", {"answers": list(body.answers)})
        return _spec_out(spec)


# ---------------------------------------------------------------- jobs


class JobIn(BaseModel):
    specification_id: str | None = None
    recipe: dict[str, Any] | None = None  # direct recipe submission (bypasses the planner)
    idempotency_key: str | None = None


def _job_out(job: Job) -> dict:
    return {"id": job.id, "project_id": job.project_id, "kind": job.kind, "state": job.state, "state_revision": job.state_revision,
            "model_id": job.model_id, "base_version_id": job.base_version_id, "result_version_id": job.result_version_id,
            "error": job.error, "cancel_requested": job.cancel_requested,
            "budget_used": {k: v for k, v in (job.budget_used or {}).items() if not k.startswith("_")},
            "input": {k: v for k, v in (job.input or {}).items() if k not in ("recipe", "spec")},
            "created_at": job.created_at.isoformat(), "updated_at": job.updated_at.isoformat()}


def _create_job(s, p: Principal, *, project_id: str, kind: str, key: str, input: dict, spec: Specification | None = None,
                model_id: str | None = None, base_version_id: str | None = None) -> tuple[Job, bool]:
    existing = s.scalars(select(Job).where(Job.tenant_id == p.tenant_id, Job.idempotency_key == key)).first()
    if existing:
        return existing, False
    job = Job(tenant_id=p.tenant_id, project_id=project_id, kind=kind, specification_id=spec.id if spec else None,
              spec_revision=spec.revision if spec else None, model_id=model_id, base_version_id=base_version_id,
              input=input, state="queued", idempotency_key=key, budget_used=new_budget_used(), created_by=p.user_id)
    s.add(job)
    s.flush()
    emit(s, job, "state.queued", {"to": "queued"})
    enqueue_outbox(s, "plan", {"job_id": job.id, "mode": "plan", "tenant_id": p.tenant_id})
    _audit(s, p, f"job:{job.id}", "create", {"kind": kind})
    return job, True


def _commit_job(fn):
    """Run job creation; a concurrent duplicate idempotency key resolves to the existing job (T035)."""
    try:
        return fn()
    except IntegrityError:
        return None


@app.post("/v1/projects/{project_id}/jobs", status_code=202)
def create_job(project_id: str, body: JobIn, p: Principal = Depends(principal), idempotency_key: str | None = Header(default=None)):
    require_write(p)
    key = idempotency_key or body.idempotency_key or uuid.uuid4().hex

    def go():
        with tx() as s:
            _project(s, p, project_id)
            spec = None
            inp: dict = {}
            if body.specification_id:
                spec = _owned(s, p, Specification, body.specification_id, "specification")
                if spec.project_id != project_id:
                    raise _err(404, "not_found", "specification not found")
                if spec.status not in ("ready", "confirmed"):
                    raise _err(422, "clarification_required", f"specification is {spec.status}",
                               missing=spec.parsed.get("missing"), conflicts=spec.parsed.get("conflicts"))
            elif body.recipe:
                planner.check_recipe(dict(body.recipe))  # 422 before any job exists (T007)
                inp["recipe"] = body.recipe
            else:
                raise _err(400, "bad_request", "give specification_id or recipe")
            job, _ = _create_job(s, p, project_id=project_id, kind="generate", key=key, input=inp, spec=spec)
            return _job_out(job)

    out = _commit_job(go)
    if out is None:
        with tx() as s:
            out = _job_out(s.scalars(select(Job).where(Job.tenant_id == p.tenant_id, Job.idempotency_key == key)).one())
    return out


class KindJobIn(BaseModel):
    spec: dict[str, Any]
    name: str | None = Field(default=None, max_length=200)
    starter: str | None = Field(default=None, max_length=64)  # reference starter id, for the change summary
    freecad: bool = False  # also write a native FreeCAD document (assemblies)
    idempotency_key: str | None = None


class ProductJobIn(BaseModel):
    request: str | None = Field(default=None, max_length=8000)
    spec: dict[str, Any] | None = None
    name: str | None = Field(default=None, max_length=200)
    starter: str | None = Field(default=None, max_length=64)
    idempotency_key: str | None = None


KIND_LABEL = {"assembly": "assembly", "sheet_metal": "sheet-metal part", "product": "product"}


def _spec_error(kind: str, spec: dict) -> None:
    """422 before any job exists when a spec does not parse (as recipes do, T007)."""
    from ..coordinator import check_direct

    err = check_direct(kind, spec)
    if err:
        status = 501 if kind == "product" and err["code"] == ErrorCode.UNSUPPORTED_OPERATION.value else 422
        code = "product_templates_not_installed" if status == 501 else err["code"]
        raise _err(status, code, err["message"])


def _kind_job(p: Principal, project_id: str, kind: str, spec: Any, key: str, *, name: str | None = None,
              freecad: bool = False, summary: str | None = None, extra: dict | None = None) -> dict:
    def go():
        with tx() as s:
            _project(s, p, project_id)
            inp = {"exec": kind, "spec": spec, "freecad": freecad, **(extra or {})}
            if name:
                inp["name"] = name
            if summary:
                inp["change_summary"] = summary
            job, _ = _create_job(s, p, project_id=project_id, kind=kind, key=key, input=inp)
            return _job_out(job)

    out = _commit_job(go)
    if out is None:
        with tx() as s:
            out = _job_out(s.scalars(select(Job).where(Job.tenant_id == p.tenant_id, Job.idempotency_key == key)).one())
    return out


@app.post("/v1/projects/{project_id}/assemblies", status_code=202)
def create_assembly_job(project_id: str, body: KindJobIn, p: Principal = Depends(principal),
                        idempotency_key: str | None = Header(default=None)):
    """Build, place, check and export an AssemblySpec (STEP with names and colours, BOM, placements, viewer meshes)."""
    require_write(p)
    _spec_error("assembly", body.spec)
    summary = f"Started from the {body.starter.replace('_', ' ')} reference assembly" if body.starter else "Assembly from a spec"
    return _kind_job(p, project_id, "assembly", body.spec, idempotency_key or body.idempotency_key or uuid.uuid4().hex,
                     name=body.name or body.spec.get("name"), freecad=body.freecad, summary=summary)


@app.post("/v1/projects/{project_id}/sheet-metal", status_code=202)
def create_sheet_metal_job(project_id: str, body: KindJobIn, p: Principal = Depends(principal),
                           idempotency_key: str | None = Header(default=None)):
    """Build a SheetMetalSpec: folded STEP, flat-pattern DXF, bend table and DFM checks."""
    require_write(p)
    _spec_error("sheet_metal", body.spec)
    summary = f"Started from the {body.starter.replace('_', ' ')} sheet-metal example" if body.starter else "Sheet-metal part from a spec"
    return _kind_job(p, project_id, "sheet_metal", body.spec, idempotency_key or body.idempotency_key or uuid.uuid4().hex,
                     name=body.name or body.spec.get("name"), summary=summary)


@app.post("/v1/projects/{project_id}/products", status_code=202)
def create_product_job(project_id: str, body: ProductJobIn, p: Principal = Depends(principal),
                       idempotency_key: str | None = Header(default=None)):
    """Run a product template (``shilpa.product.run_product``). 501 until the product templates are installed."""
    require_write(p)
    if (body.request is None) == (body.spec is None):
        raise _err(400, "bad_request", "give exactly one of request or spec")
    _spec_error("product", body.spec or {})
    payload = {"spec": body.spec} if body.spec is not None else {"request": body.request}
    return _kind_job(p, project_id, "product", payload, idempotency_key or body.idempotency_key or uuid.uuid4().hex,
                     name=body.name, summary=f"Started from the {body.starter.replace('_', ' ')} reference product"
                     if body.starter else f"Product from the request: {body.request}" if body.request else "Product from a spec")


@app.get("/v1/jobs/{job_id}")
def get_job(job_id: str, p: Principal = Depends(principal)):
    with tx() as s:
        job = _owned(s, p, Job, job_id, "job")
        attempts = s.scalars(select(JobAttempt).where(JobAttempt.job_id == job.id).order_by(JobAttempt.number)).all()
        out = _job_out(job)
        out["recipe"] = job.recipe
        out["attempts"] = [{"number": a.number, "status": a.status, "error": a.error, "worker": a.worker,
                            "features": (a.result or {}).get("features"), "validation": (a.result or {}).get("validation"),
                            "timings_ms": (a.result or {}).get("timings_ms")} for a in attempts]
        return out


@app.post("/v1/jobs/{job_id}/cancel")
def cancel_job(job_id: str, p: Principal = Depends(principal)):
    require_write(p)
    with tx() as s:
        job = _owned(s, p, Job, job_id, "job")
        if job.state in TERMINAL:
            return {**_job_out(job), "note": f"job already {job.state}"}
        job.cancel_requested = True
        if job.state == "queued":
            transition(s, job, "cancelled")
        else:
            emit(s, job, "cancel.requested", {})
        _audit(s, p, f"job:{job.id}", "cancel")
        return _job_out(job)


@app.get("/v1/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request, p: Principal = Depends(principal),
                     last_event_id: str | None = Header(default=None)):
    with tx() as s:
        _owned(s, p, Job, job_id, "job")
    start = int(last_event_id or request.query_params.get("after") or 0)

    async def gen():
        cursor = start
        idle = 0
        while True:
            if await request.is_disconnected():
                return
            with tx() as s:
                rows = s.scalars(select(JobEvent).where(JobEvent.job_id == job_id, JobEvent.id > cursor).order_by(JobEvent.id)).all()
                state = s.get(Job, job_id).state
                evs = [(e.id, e.type, e.data, e.created_at.isoformat()) for e in rows]
            for eid, typ, data, at in evs:
                cursor = eid
                yield {"id": str(eid), "event": "job", "data": json.dumps({"type": typ, "data": data, "at": at})}
            if state in TERMINAL and not evs:
                yield {"event": "end", "data": json.dumps({"state": state})}
                return
            idle = 0 if evs else idle + 1
            await asyncio.sleep(0.4 if idle < 50 else 1.5)

    return EventSourceResponse(gen(), ping=15)


# ---------------------------------------------------------------- models and versions


def _model_out(s, m: Model) -> dict:
    head = s.get(ModelVersion, m.head_version_id) if m.head_version_id else None
    thumb = s.scalar(select(Artifact.id).where(Artifact.version_id == m.head_version_id, Artifact.format == "THUMB")) if head else None
    return {"thumb_artifact_id": thumb, "id": m.id, "project_id": m.project_id, "name": m.name, "kind": m.kind or "part", "head_version_id": m.head_version_id,
            "head_number": head.number if head else None, "created_at": m.created_at.isoformat()}


def _version_out(s, v: ModelVersion, full: bool = False) -> dict:
    arts = s.scalars(select(Artifact).where(Artifact.version_id == v.id)).all()
    out = {"id": v.id, "model_id": v.model_id, "number": v.number, "parent_version_id": v.parent_version_id, "job_id": v.job_id,
           "recipe_hash": v.recipe_hash, "engine": v.engine, "validation_state": v.validation_state,
           "validation_passed": (v.validation or {}).get("passed"), "change_summary": v.change_summary,
           "created_at": v.created_at.isoformat(),
           "artifacts": [{"id": a.id, "format": a.format, "bytes": a.bytes, "sha256": a.sha256} for a in arts],
           "parameters": v.recipe.get("parameters")}
    m = s.get(Model, v.model_id)
    out["kind"] = (m.kind if m else None) or "part"
    if out["kind"] != "part":
        out["parameters"] = {}
    if full:
        out["recipe"] = v.recipe
        out["validation"] = v.validation
        feats = next((a for a in arts if a.format == "FEATURES"), None)
        if feats:
            out["features"] = json.loads(blobs.path(feats.blob_key).read_text(encoding="utf-8"))
        viewer = next((a for a in arts if a.format == "VIEWER"), None)
        if viewer and blobs.exists(viewer.blob_key):
            out["viewer"] = json.loads(blobs.path(viewer.blob_key).read_text(encoding="utf-8"))
    return out


@app.get("/v1/projects/{project_id}/models")
def list_models(project_id: str, p: Principal = Depends(principal)):
    with tx() as s:
        _project(s, p, project_id)
        return [_model_out(s, m) for m in s.scalars(select(Model).where(Model.project_id == project_id, Model.tenant_id == p.tenant_id)).all()]


@app.get("/v1/models/{model_id}")
def get_model(model_id: str, p: Principal = Depends(principal)):
    with tx() as s:
        return _model_out(s, _owned(s, p, Model, model_id, "model"))


@app.get("/v1/models/{model_id}/versions")
def list_versions(model_id: str, p: Principal = Depends(principal), limit: int = 50, offset: int = 0):
    with tx() as s:
        m = _owned(s, p, Model, model_id, "model")
        vs = s.scalars(select(ModelVersion).where(ModelVersion.model_id == m.id).order_by(ModelVersion.number.desc()).offset(offset).limit(min(limit, 200))).all()
        return [_version_out(s, v) for v in vs]


@app.get("/v1/versions/{version_id}")
def get_version(version_id: str, p: Principal = Depends(principal)):
    with tx() as s:
        return _version_out(s, _owned(s, p, ModelVersion, version_id, "version"), full=True)


class EditIn(BaseModel):
    base_version_id: str
    parameters: dict[str, float] | None = None
    instruction: str | None = Field(default=None, max_length=4000)
    restore_version_id: str | None = None
    idempotency_key: str | None = None


@app.post("/v1/models/{model_id}/edits", status_code=202)
def create_edit(model_id: str, body: EditIn, p: Principal = Depends(principal), idempotency_key: str | None = Header(default=None)):
    require_write(p)
    key = idempotency_key or body.idempotency_key or uuid.uuid4().hex
    if sum(x is not None for x in (body.parameters, body.instruction, body.restore_version_id)) != 1:
        raise _err(400, "bad_request", "give exactly one of parameters, instruction or restore_version_id")

    def go():
        with tx() as s:
            m = _owned(s, p, Model, model_id, "model")
            if m.head_version_id != body.base_version_id:
                raise _err(409, "stale_revision", "base_version_id is not the current head", head_version_id=m.head_version_id)
            base = _owned(s, p, ModelVersion, body.base_version_id, "version")
            inp: dict = {}
            kind = m.kind or "part"
            if kind != "part":
                # Assemblies, sheet metal and products are edited through their spec; versions can be restored.
                if not body.restore_version_id:
                    raise _err(422, "unsupported_operation",
                               f"parameter and conversational edits apply to single parts; this {KIND_LABEL.get(kind, kind)} "
                               "is changed through its spec (restoring a version works)")
                src = _owned(s, p, ModelVersion, body.restore_version_id, "version")
                if src.model_id != m.id:
                    raise _err(404, "not_found", "version not found")
                inp = {"exec": kind, "spec": src.recipe, "restore_of": src.number}
                job, _ = _create_job(s, p, project_id=m.project_id, kind="edit", key=key, input=inp, model_id=m.id, base_version_id=base.id)
                return _job_out(job)
            if body.parameters:
                recipe = planner.apply_parameter_edit(base.recipe, body.parameters)
                planner.check_recipe(dict(recipe))  # reject invalid values before queueing
                inp["parameters"] = body.parameters
            elif body.instruction:
                ensure_enabled()  # 503 planner_disabled while SHILPA_LLM=off
                if not settings.llm_configured:
                    raise _err(503, "llm_unavailable", "conversational edits need Azure OpenAI configured")
                inp["instruction"] = body.instruction
            else:
                src = _owned(s, p, ModelVersion, body.restore_version_id, "version")
                if src.model_id != m.id:
                    raise _err(404, "not_found", "version not found")
                inp["recipe"] = src.recipe
                inp["restore_of"] = src.number
            job, _ = _create_job(s, p, project_id=m.project_id, kind="edit", key=key, input=inp, model_id=m.id, base_version_id=base.id)
            return _job_out(job)

    out = _commit_job(go)
    if out is None:
        with tx() as s:
            out = _job_out(s.scalars(select(Job).where(Job.tenant_id == p.tenant_id, Job.idempotency_key == key)).one())
    return out


class ExportIn(BaseModel):
    format: str = Field(pattern="^FCSTD$")


@app.post("/v1/versions/{version_id}/exports", status_code=202)
def create_export(version_id: str, body: ExportIn, p: Principal = Depends(principal)):
    """Create an export derivative of an immutable version; reuses an existing verified artifact."""
    require_write(p)
    from ..adapters import freecad_adapter

    with tx() as s:
        v = _owned(s, p, ModelVersion, version_id, "version")
        existing = s.scalars(select(Artifact).where(Artifact.version_id == v.id, Artifact.format == body.format)).first()
        if existing:
            return {"artifact_id": existing.id, "job": None}
        m = s.get(Model, v.model_id)
        kind = m.kind or "part"
        if kind == "sheet_metal":
            raise _err(422, "unsupported_operation", "native FreeCAD export is not available for sheet-metal parts yet; use STEP and DXF")
        if not freecad_adapter.available():
            raise _err(503, "export_unavailable", "FreeCAD is not installed on this server")
        if kind in ("assembly", "product"):
            # Rebuild the same spec with the FreeCAD Assembly export; the artifact attaches to this version.
            spec = v.recipe
            if kind == "product":  # the derived AssemblySpec the product template placed
                art = s.scalars(select(Artifact).where(Artifact.version_id == v.id, Artifact.format == "ASSEMBLY_SPEC")).first()
                if art is None:
                    raise _err(422, "unsupported_operation", "this product version has no assembly spec to export")
                spec = json.loads(blobs.path(art.blob_key).read_text(encoding="utf-8"))
            job, _ = _create_job(s, p, project_id=m.project_id, kind="export", key=f"export:{v.id}:{body.format}",
                                 input={"exec": "assembly", "spec": spec, "freecad": True, "export_of": v.id, "format": body.format},
                                 model_id=m.id, base_version_id=v.id)
            return {"artifact_id": None, "job": _job_out(job)}
        recipe = dict(v.recipe)
        recipe["exports"] = sorted(set(recipe.get("exports", [])) | {body.format})
        job, _ = _create_job(s, p, project_id=m.project_id, kind="export", key=f"export:{v.id}:{body.format}",
                             input={"recipe": recipe, "export_of": v.id, "format": body.format}, model_id=m.id, base_version_id=v.id)
        return {"artifact_id": None, "job": _job_out(job)}


# ---------------------------------------------------------------- artifacts and usage

MEDIA = {"FCSTD": ("application/octet-stream", "FCStd"), "STEP": ("model/step", "step"), "STL": ("model/stl", "stl"), "GLB": ("model/gltf-binary", "glb"),
         "RECIPE": ("application/json", "json"), "VALIDATION": ("application/json", "json"),
         "STL_UNITS": ("application/json", "json"), "FEATURES": ("application/json", "json"),
         "DXF": ("image/vnd.dxf", "dxf"), "BOM_CSV": ("text/csv", "csv"), "BOM_JSON": ("application/json", "json"),
         "PLACEMENTS": ("application/json", "json"), "MESHES": ("application/json", "json"),
         "VIEWER": ("application/json", "json"), "PRODUCT": ("application/json", "json"),
         "PRODUCT_BOM_CSV": ("text/csv", "csv"), "PRODUCT_BOM_JSON": ("application/json", "json"),
         "ASSEMBLY_SPEC": ("application/json", "json"), "RENDER_SIDE": ("image/png", "png"), "RENDER_ISO": ("image/png", "png"),
         "THUMB": ("image/webp", "webp")}
NAMED_FORMATS = ("STEP", "STL", "GLB", "FCSTD")


@app.get("/v1/artifacts/{artifact_id}/download")
def download(artifact_id: str, p: Principal = Depends(principal)):
    with tx() as s:
        a = _owned(s, p, Artifact, artifact_id, "artifact")
        v = s.get(ModelVersion, a.version_id)
        m = s.get(Model, v.model_id)
        path = blobs.path(a.blob_key)
        media, ext = MEDIA.get(a.format, ("application/octet-stream", "bin"))
        safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (m.name or "model"))[:60]
        suffix = {"BOM_CSV": "bom", "BOM_JSON": "bom", "DXF": "flat", "PRODUCT_BOM_CSV": "product_bom", "PRODUCT_BOM_JSON": "product_bom",
                  "RENDER_SIDE": "side", "RENDER_ISO": "iso", "THUMB": "thumb"}.get(a.format, a.format.lower())
        fname = f"{safe_name}_v{v.number}.{ext}" if a.format in NAMED_FORMATS else f"{safe_name}_v{v.number}_{suffix}.{ext}"
    if not path.exists():
        raise _err(404, "not_found", "artifact bytes missing")
    return FileResponse(path, media_type=media, filename=fname)


@app.get("/v1/usage")
def usage(p: Principal = Depends(principal)):
    with tx() as s:
        rows = s.execute(select(UsageEvent.kind, func.count(), func.sum(UsageEvent.input_tokens), func.sum(UsageEvent.output_tokens),
                                func.sum(UsageEvent.cpu_seconds)).where(UsageEvent.tenant_id == p.tenant_id).group_by(UsageEvent.kind)).all()
        jobs = dict(s.execute(select(Job.state, func.count()).where(Job.tenant_id == p.tenant_id).group_by(Job.state)).all())
    return {"by_kind": {k: {"events": n, "input_tokens": i or 0, "output_tokens": o or 0, "cpu_seconds": round(c or 0, 2)} for k, n, i, o, c in rows},
            "jobs": jobs}
