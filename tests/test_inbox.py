"""GET /v1/needs-you: clarifications, drawing reviews, failed builds, supersession, tenant isolation, viewer."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from shilpa.api.app import app
from shilpa.db import Job, Model, Project, Specification, Tenant, User, tx

DEV = {"Authorization": "Bearer dev:dev@wayam.local"}
VIEWER = {"Authorization": "Bearer dev:viewer@wayam.local"}
OTHER = {"Authorization": "Bearer dev:other@example.com"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _ago(**kw):
    return datetime.now(timezone.utc) - timedelta(**kw)


@pytest.fixture(scope="module")
def seeded(client):
    with tx() as s:
        t = s.scalars(select(Tenant).where(Tenant.name == "Wayam (dev)")).one()
        u = s.scalars(select(User).where(User.email == "dev@wayam.local")).one()
        proj = Project(tenant_id=t.id, name="Inbox project", created_by=u.id)
        s.add(proj)
        s.flush()
        m_fixed = Model(tenant_id=t.id, project_id=proj.id, name="Fixed plate")
        m_broken = Model(tenant_id=t.id, project_id=proj.id, name="Broken bracket")
        s.add_all([m_fixed, m_broken])
        s.flush()

        def job(state, model, age, spec=None, error=None):
            j = Job(tenant_id=t.id, project_id=proj.id, kind="generate", model_id=model.id if model else None, input={}, state=state,
                    idempotency_key=f"k-{len(s.new)}-{age}-{state}-{model.id if model else spec}", created_by=u.id,
                    specification_id=spec, error=error, created_at=_ago(**age), updated_at=_ago(**age))
            s.add(j)
            return j

        fail_fixed = job("failed", m_fixed, {"days": 2}, error={"message": "old failure"})
        job("succeeded", m_fixed, {"days": 1})
        fail_broken = job("failed", m_broken, {"hours": 3}, error={"message": "Boolean cut failed"})
        job("failed", m_broken, {"days": 10}, error={"message": "too old"})
        spec_ask = Specification(tenant_id=t.id, project_id=proj.id, prompt="plate", status="needs_clarification",
                                 parsed={"missing": [{"name": "thickness", "question": "What is the thickness?", "critical": True}],
                                         "conflicts": []})
        spec_drawing = Specification(tenant_id=t.id, project_id=proj.id, prompt="", status="needs_review",
                                     parsed={"status_reason": "confirm the values read from the drawing"})
        spec_done = Specification(tenant_id=t.id, project_id=proj.id, prompt="done", status="ready", parsed={})
        s.add_all([spec_ask, spec_drawing, spec_done])
        s.flush()
        return {"project": proj.id, "fail_fixed": fail_fixed.id, "fail_broken": fail_broken.id, "ask": spec_ask.id,
                "drawing": spec_drawing.id, "tenant": t.id}


def _items(client, headers):
    r = client.get("/v1/needs-you", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == len(body["items"])
    return body["items"]


def test_requires_auth(client):
    assert client.get("/v1/needs-you").status_code == 401


def test_clarification_and_drawing_items(client, seeded):
    by_id = {i["id"]: i for i in _items(client, DEV)}
    ask = by_id[f"spec:{seeded['ask']}"]
    assert ask["kind"] == "clarification" and ask["detail"] == "What is the thickness?"
    assert ask["project_name"] == "Inbox project" and ask["can_act"] is True
    assert ask["link"] == {"project_id": seeded["project"], "open": "specification", "specification_id": seeded["ask"], "job_id": None}
    assert by_id[f"spec:{seeded['drawing']}"]["kind"] == "drawing_review"
    assert not any(i["title"] == "ready" for i in by_id.values())
    assert len([i for i in by_id.values() if i["kind"] in ("clarification", "drawing_review")]) == 2


def test_failed_jobs_window_and_supersession(client, seeded):
    by_id = {i["id"]: i for i in _items(client, DEV)}
    assert f"job:{seeded['fail_fixed']}" not in by_id  # a later job on the same model succeeded
    item = by_id[f"job:{seeded['fail_broken']}"]
    assert item["kind"] == "failed_build" and item["model_name"] == "Broken bracket" and item["detail"] == "Boolean cut failed"
    assert item["link"]["open"] == "job" and item["link"]["job_id"] == seeded["fail_broken"]
    assert "too old" not in {i["detail"] for i in by_id.values()}  # outside 7 days


def test_a_spec_that_was_built_is_not_listed(client, seeded):
    with tx() as s:
        s.add(Job(tenant_id=seeded["tenant"], project_id=seeded["project"], kind="generate", input={}, state="queued",
                  idempotency_key="spec-built", created_by="x", specification_id=seeded["drawing"]))
    ids = {i["id"] for i in _items(client, DEV)}
    assert f"spec:{seeded['drawing']}" not in ids and f"spec:{seeded['ask']}" in ids


def test_viewer_sees_items_but_cannot_act(client, seeded):
    items = _items(client, VIEWER)
    assert items and all(i["can_act"] is False for i in items)


def test_other_tenant_sees_nothing(client, seeded):
    assert _items(client, OTHER) == []


def test_no_dashes_in_strings(client, seeded):
    for i in _items(client, DEV):
        assert "–" not in i["title"] + i["detail"] and "—" not in i["title"] + i["detail"]
