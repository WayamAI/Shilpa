"""THUMB artifacts: rendered by the CAD worker for every published version, served via the artifact route."""

import pytest
from fastapi.testclient import TestClient

from shilpa import thumbs
from shilpa.api.app import app
from shilpa.api.starters import assembly_starters, sheet_metal_starters
from shilpa.db import Artifact, Model, tx
from shilpa.storage import blobs

from .test_contracts import BLUEPRINT_PLATE
from .test_workflow import DEV, OTHER, pump

GOLDEN = {s["id"]: s for s in assembly_starters()}
SHEET = {s["id"]: s for s in sheet_metal_starters()}
WEBP = b"RIFF"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def project(client):
    return client.post("/v1/projects", json={"name": "Thumbs"}, headers=DEV).json()["id"]


def part_version(client, project):
    r = client.post(f"/v1/projects/{project}/jobs", json={"recipe": BLUEPRINT_PLATE}, headers=DEV)
    job = pump(client, r.json()["id"])
    assert job["state"] == "succeeded", job["error"]
    return client.get(f"/v1/versions/{job['result_version_id']}", headers=DEV).json()


def thumb_of(version):
    return next((a for a in version["artifacts"] if a["format"] == "THUMB"), None)


def check_webp(client, art):
    r = client.get(f"/v1/artifacts/{art['id']}/download", headers=DEV)
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    assert r.content[:4] == WEBP and r.content[8:12] == b"WEBP"


def test_part_job_publishes_thumb(client, project):
    v = part_version(client, project)
    check_webp(client, thumb_of(v))
    model = client.get(f"/v1/models/{v['model_id']}", headers=DEV).json()
    assert model["thumb_artifact_id"] == thumb_of(v)["id"]
    listed = client.get(f"/v1/projects/{project}", headers=DEV).json()["models"]
    assert any(m["thumb_artifact_id"] == thumb_of(v)["id"] for m in listed)


def test_assembly_job_publishes_thumb(client, project):
    r = client.post(f"/v1/projects/{project}/assemblies", json={"spec": GOLDEN["hinge"]["spec"], "starter": "hinge"}, headers=DEV)
    job = pump(client, r.json()["id"])
    assert job["state"] == "succeeded", job["error"]
    check_webp(client, thumb_of(client.get(f"/v1/versions/{job['result_version_id']}", headers=DEV).json()))


def test_sheet_metal_job_publishes_thumb(client, project):
    r = client.post(f"/v1/projects/{project}/sheet-metal", json={"spec": SHEET["l_bracket"]["spec"], "starter": "l_bracket"}, headers=DEV)
    job = pump(client, r.json()["id"])
    assert job["state"] == "succeeded", job["error"]
    check_webp(client, thumb_of(client.get(f"/v1/versions/{job['result_version_id']}", headers=DEV).json()))


def test_render_failure_does_not_fail_the_job(client, project, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("renderer exploded")

    monkeypatch.setattr(thumbs, "render", boom)  # caught inside render_dir
    v = part_version(client, project)
    assert thumb_of(v) is None
    assert v["artifacts"]  # the version still published its geometry
    monkeypatch.undo()
    monkeypatch.setattr(thumbs, "write_thumb", boom)  # even an exception escaping write_thumb is contained by the worker
    assert thumb_of(part_version(client, project)) is None
    model = client.get(f"/v1/models/{v['model_id']}", headers=DEV).json()
    assert model["thumb_artifact_id"] is None


def test_cross_tenant_cannot_download_thumb(client, project):
    art = thumb_of(part_version(client, project))
    assert client.get(f"/v1/artifacts/{art['id']}/download", headers=DEV).status_code == 200
    assert client.get(f"/v1/artifacts/{art['id']}/download", headers=OTHER).status_code == 404
    assert client.get(f"/v1/artifacts/{art['id']}/download").status_code == 401


def test_backfill_renders_missing_head_thumbs(client, project, monkeypatch):
    monkeypatch.setattr(thumbs, "render", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    v = part_version(client, project)
    monkeypatch.undo()
    assert thumb_of(v) is None
    done, _ = thumbs.backfill()
    assert done >= 1
    again = client.get(f"/v1/versions/{v['id']}", headers=DEV).json()
    check_webp(client, thumb_of(again))
    with tx() as s:
        assert s.query(Artifact).filter_by(version_id=v["id"], format="THUMB").count() == 1
    assert thumbs.backfill()[0] == 0
