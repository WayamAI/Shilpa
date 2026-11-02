"""The whole publish path on the Azure adapters (fake SDK clients): API -> outbox -> Service Bus -> coordinator ->
CAD worker (local scratch, staging upload, server-side copy) -> rows -> authenticated download streamed from the store."""

import dataclasses
import io

import pytest
from fastapi.testclient import TestClient

from shilpa import queue, queue_servicebus, storage
from shilpa.api import app as api_app
from shilpa.api.app import app
from shilpa.db import Artifact, tx
from shilpa.settings import cloud as real_cloud
from shilpa.workers import cad

from .fakes_azure import FakeBlobService, FakeBroker
from .test_contracts import BLUEPRINT_PLATE
from .test_workflow import DEV, OTHER, pump


@pytest.fixture(scope="module")
def azure_stack(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    svc = FakeBlobService()
    store = storage.AzureBlobStore(container="artifacts", service=svc, workdir=str(tmp_path_factory.mktemp("scratch")))
    broker = FakeBroker()
    c = dataclasses.replace(real_cloud, queue_backend="servicebus")
    mp.setattr(api_app, "blobs", store)
    mp.setattr(cad, "blobs", store)
    mp.setattr(storage, "blobs", store)
    mp.setattr(queue, "cloud", c)
    mp.setattr(queue_servicebus, "cloud", c)
    queue_servicebus.use(queue_servicebus.ServiceBusQueue(client=broker.client()))
    yield svc.containers.setdefault("artifacts", svc.get_container_client("artifacts")), broker
    queue_servicebus.use(None)
    mp.undo()


def test_job_publishes_through_azure_adapters(azure_stack):
    container, broker = azure_stack
    with TestClient(app) as client:
        project = client.post("/v1/projects", json={"name": "Azure adapters"}, headers=DEV).json()["id"]
        r = client.post(f"/v1/projects/{project}/jobs", json={"recipe": BLUEPRINT_PLATE}, headers={**DEV, "Idempotency-Key": "az-1"})
        assert r.status_code == 202, r.text
        job = pump(client, r.json()["id"])
        assert job["state"] == "succeeded", job["error"]
        assert broker.sent >= 2  # plan and cad messages travelled over the (fake) broker
        version = client.get(f"/v1/versions/{job['result_version_id']}", headers=DEV).json()
        assert version["validation"]["passed"] and version["features"]

        names = set(container.data)
        assert any("/versions/" in n and n.endswith("model.step") for n in names)
        assert any("/attempts/" in n and n.endswith("model.step") for n in names)  # staging copy, uploaded before publish
        assert container.copies >= 1  # version files were server-side copies of the staged ones

        step = next(a for a in version["artifacts"] if a["format"] == "STEP")
        d = client.get(f"/v1/artifacts/{step['id']}/download", headers=DEV)
        assert d.status_code == 200 and d.headers["content-length"] == str(step["bytes"]) and len(d.content) == step["bytes"]
        assert "attachment" in d.headers["content-disposition"]
        assert client.get(f"/v1/artifacts/{step['id']}/download", headers=OTHER).status_code == 404  # still tenant-checked
        thumb = next(a for a in version["artifacts"] if a["format"] == "THUMB")
        assert client.get(f"/v1/artifacts/{thumb['id']}/download", headers=DEV).content[:4] == b"RIFF"


def test_missing_blob_is_404_not_500(azure_stack):
    container, _ = azure_stack
    with TestClient(app) as client:
        with tx() as s:
            art = s.query(Artifact).filter(Artifact.format == "STEP").first()
            art_id, key = art.id, art.blob_key
        container.data.pop(key)
        assert client.get(f"/v1/artifacts/{art_id}/download", headers=DEV).status_code == 404


def test_upload_goes_to_the_store(azure_stack):
    container, _ = azure_stack
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(buf, "PNG")
    with TestClient(app) as client:
        project = client.post("/v1/projects", json={"name": "Azure uploads"}, headers=DEV).json()["id"]
        r = client.post(f"/v1/projects/{project}/uploads", files={"file": ("d.png", buf.getvalue(), "image/png")}, headers=DEV)
        assert r.status_code in (201, 422), r.text
        assert any(n.endswith("/original.bin") for n in container.data)
        assert any(n.endswith("/pages/ingest.json") for n in container.data)
        if r.status_code == 201:
            up = r.json()
            page = client.get(f"/v1/uploads/{up['id']}/pages/1", headers=DEV)
            assert page.status_code == 200 and page.content[:4] == b"\x89PNG"
