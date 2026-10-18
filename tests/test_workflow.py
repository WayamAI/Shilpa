"""End-to-end workflow through the API, queue, coordinator and CAD worker (no LLM needed).

Covers T035 idempotent submit, T036 duplicate delivery, T042 queued cancellation,
T046 stale edit, T051/T052 tenant isolation, T055 viewer write, and the blueprint
section 4.3 demo: plate v1 -> width 100 -> v2 with holes at X +/-40, v1 preserved.
"""

import copy

import pytest
from fastapi.testclient import TestClient

from shilpa import coordinator, queue
from shilpa.api.app import app
from shilpa.db import ModelVersion, QueueMessage, tx
from shilpa.workers import cad

from .test_contracts import BLUEPRINT_PLATE

DEV = {"Authorization": "Bearer dev:dev@wayam.local"}
VIEWER = {"Authorization": "Bearer dev:viewer@wayam.local"}
OTHER = {"Authorization": "Bearer dev:other@example.com"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def pump(client, job_id, limit=60):
    for _ in range(limit):
        coordinator.run_once()
        cad.run_once()
        job = client.get(f"/v1/jobs/{job_id}", headers=DEV).json()
        if job["state"] in ("succeeded", "failed", "cancelled"):
            return job
    raise AssertionError(f"job did not finish: {job}")


@pytest.fixture(scope="module")
def project(client):
    r = client.post("/v1/projects", json={"name": "Workflow tests"}, headers=DEV)
    assert r.status_code == 201
    return r.json()["id"]


def test_generate_edit_and_history(client, project):
    r = client.post(f"/v1/projects/{project}/jobs", json={"recipe": BLUEPRINT_PLATE}, headers={**DEV, "Idempotency-Key": "plate-1"})
    assert r.status_code == 202, r.text
    job = pump(client, r.json()["id"])
    assert job["state"] == "succeeded", job["error"]
    v1 = client.get(f"/v1/versions/{job['result_version_id']}", headers=DEV).json()
    assert v1["number"] == 1 and v1["validation"]["passed"]
    assert v1["validation"]["measurement"]["bbox_size"] == [80, 40, 8]

    # Width edit retaining the 10 mm edge offset (blueprint 4.3)
    r = client.post(f"/v1/models/{v1['model_id']}/edits", json={"base_version_id": v1["id"], "parameters": {"width": 100}}, headers=DEV)
    assert r.status_code == 202, r.text
    job2 = pump(client, r.json()["id"])
    assert job2["state"] == "succeeded", job2["error"]
    v2 = client.get(f"/v1/versions/{job2['result_version_id']}", headers=DEV).json()
    assert v2["number"] == 2 and v2["parent_version_id"] == v1["id"]
    xs = sorted({c["center"][0] for c in v2["validation"]["measurement"]["cylinders"] if c["kind"] == "hole"})
    assert xs == [-40, 40]
    # v1 is untouched
    again = client.get(f"/v1/versions/{v1['id']}", headers=DEV).json()
    assert again["validation"]["measurement"]["bbox_size"] == [80, 40, 8]

    # Stale edit on v1 now returns 409 (T046)
    r = client.post(f"/v1/models/{v1['model_id']}/edits", json={"base_version_id": v1["id"], "parameters": {"width": 90}}, headers=DEV)
    assert r.status_code == 409 and r.json()["code"] == "stale_revision"

    # Restore v1 as v3
    r = client.post(f"/v1/models/{v1['model_id']}/edits", json={"base_version_id": v2["id"], "restore_version_id": v1["id"]}, headers=DEV)
    job3 = pump(client, r.json()["id"])
    v3 = client.get(f"/v1/versions/{job3['result_version_id']}", headers=DEV).json()
    assert v3["number"] == 3 and v3["recipe_hash"] == v1["recipe_hash"]

    # Downloads are authorised per tenant (T052)
    step = next(a for a in v1["artifacts"] if a["format"] == "STEP")
    assert client.get(f"/v1/artifacts/{step['id']}/download", headers=DEV).status_code == 200
    assert client.get(f"/v1/artifacts/{step['id']}/download", headers=OTHER).status_code == 404
    assert client.get(f"/v1/projects/{project}", headers=OTHER).status_code == 404  # T051
    assert client.get(f"/v1/jobs/{job['id']}", headers=OTHER).status_code == 404


def test_idempotent_submit(client, project):  # T035
    h = {**DEV, "Idempotency-Key": "same-key"}
    a = client.post(f"/v1/projects/{project}/jobs", json={"recipe": BLUEPRINT_PLATE}, headers=h).json()
    b = client.post(f"/v1/projects/{project}/jobs", json={"recipe": BLUEPRINT_PLATE}, headers=h).json()
    assert a["id"] == b["id"]
    pump(client, a["id"])


def test_duplicate_delivery_publishes_once(client, project):  # T036 / T037
    r = client.post(f"/v1/projects/{project}/jobs", json={"recipe": BLUEPRINT_PLATE}, headers=DEV).json()
    coordinator.run_once()  # plan -> executing, cad message in outbox
    coordinator.run_once()  # publish outbox
    with tx() as s:
        msg = s.query(QueueMessage).filter(QueueMessage.queue == "cad").order_by(QueueMessage.id.desc()).first()
        body = dict(msg.body)
    # Re-send the same work under a different message id: duplicate detection cannot catch it.
    queue.send("cad", "dup-" + body["job_id"], body)
    for _ in range(4):
        cad.run_once()
    job = client.get(f"/v1/jobs/{r['id']}", headers=DEV).json()
    assert job["state"] == "succeeded"
    with tx() as s:
        assert s.query(ModelVersion).filter(ModelVersion.job_id == r["id"]).count() == 1


def test_invalid_recipe_rejected_before_job(client, project):  # T007
    bad = copy.deepcopy(BLUEPRINT_PLATE)
    bad["parameters"]["thickness"] = -1
    r = client.post(f"/v1/projects/{project}/jobs", json={"recipe": bad}, headers=DEV)
    assert r.status_code == 422 and r.json()["code"] == "invalid_parameter"


def test_geometry_failure_without_llm_fails_cleanly(client, project):
    bad = copy.deepcopy(BLUEPRINT_PLATE)
    bad["parameters"]["hole_diameter"] = 20  # breaks out of the edge: precondition failure
    r = client.post(f"/v1/projects/{project}/jobs", json={"recipe": bad}, headers=DEV).json()
    job = pump(client, r["id"])
    # Repair is attempted, but with no planner configured the job fails with a persisted error.
    assert job["state"] == "failed" and job["error"]["code"]
    assert job["result_version_id"] is None


def test_viewer_cannot_write(client, project):  # T055
    r = client.post(f"/v1/projects/{project}/jobs", json={"recipe": BLUEPRINT_PLATE}, headers=VIEWER)
    assert r.status_code == 403
    assert client.get(f"/v1/projects/{project}", headers=VIEWER).status_code == 200


def test_queued_cancellation(client, project):  # T042
    r = client.post(f"/v1/projects/{project}/jobs", json={"recipe": BLUEPRINT_PLATE}, headers=DEV).json()
    c = client.post(f"/v1/jobs/{r['id']}/cancel", headers=DEV).json()
    assert c["state"] == "cancelled"
    job = pump(client, r["id"])
    assert job["state"] == "cancelled" and job["result_version_id"] is None


def test_unauthenticated(client):  # T054
    assert client.get("/v1/projects").status_code == 401
    assert client.get("/v1/projects", headers={"Authorization": "Bearer nope"}).status_code == 401
