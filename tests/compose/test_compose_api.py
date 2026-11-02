"""Worked examples E1 to E4 and E6 end to end through the API, queue, coordinator and CAD worker.

The composer model is always a fake (``llm.use_client``); apply and replay run with a client that
fails the test if it is called, proving they are LLM-free.
"""

import json

import pytest
from fastapi.testclient import TestClient

from shilpa.agent import llm
from shilpa.api.app import app
from shilpa.compose.lower import spec_json

from ..test_workflow import DEV, OTHER, VIEWER, pump
from .fixtures import BRACKET, E1, E2, E3, E4, E6, E6_BASE, PLATE, ExplodingClient, FakeComposer


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def project(client):
    r = client.post("/v1/projects", json={"name": "Compositions"}, headers=DEV)
    pid = r.json()["id"]
    for recipe in (PLATE, BRACKET):  # the native parts of the fixture library
        r = client.post(f"/v1/projects/{pid}/jobs", json={"recipe": recipe}, headers=DEV)
        assert r.status_code == 202, r.text
        assert pump(client, r.json()["id"])["state"] == "succeeded"
    return pid


def new_composition(client, project, name="Bench"):
    r = client.post("/v1/compositions", json={"project_id": project, "name": name}, headers=DEV)
    assert r.status_code == 201, r.text
    return r.json()


def interpret(client, cid, example, headers=DEV):
    prompt, steps = example
    with llm.use_client(FakeComposer(steps)):
        r = client.post(f"/v1/compositions/{cid}/interpret", json={"prompt": prompt}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def answer(client, cid, card, option):
    with llm.use_client(ExplodingClient()):
        r = client.post(f"/v1/compositions/{cid}/interpret",
                        json={"prompt": "", "steps": card["steps"], "answers": card["blockers"][0]["options"][option]["patch"]},
                        headers=DEV)
    assert r.status_code == 200, r.text
    return r.json()


def apply(client, cid, card, prompt, key=None):
    body = {"prompt": prompt, "steps": card["steps"], "base_version_id": card["base_version_id"], "spec_hash": card["spec_hash"]}
    headers = {**DEV, **({"Idempotency-Key": key} if key else {})}
    with llm.use_client(ExplodingClient()):
        r = client.post(f"/v1/compositions/{cid}/apply", json=body, headers=headers)
    assert r.status_code == 202, r.text
    out = r.json()
    job = pump(client, out["job"]["id"])
    assert job["state"] == "succeeded", job["error"]
    steps = client.get(f"/v1/compositions/{cid}/steps", headers=DEV).json()
    step = next(s for s in steps if s["id"] == out["step"]["id"])
    assert step["status"] == "applied" and step["result_version_id"] == job["result_version_id"]
    return step, client.get(f"/v1/versions/{job['result_version_id']}", headers=DEV).json()


def test_worked_examples_e1_to_e4(client, project):
    comp = new_composition(client, project)
    cid = comp["id"]

    # E1: add and ground.
    card = interpret(client, cid, E1)
    assert card["status"] == "ready" and card["llm"]["used"] and card["llm"]["llm_calls"] == 1
    assert card["mentions"][0]["status"] == "ok" and card["mentions"][0]["ref"]["source"] == "native"
    step, v = apply(client, cid, card, E1[0])
    assert v["kind"] == "assembly" and [i["id"] for i in v["viewer"]["instances"]] == ["plate"]

    # E2: offset placement, 10 mm above the top face, centred.
    card = interpret(client, cid, E2)
    assert card["status"] == "ready" and card["base_version_id"] == v["id"]
    assert card["quantities"][0]["normalised"] == "10 mm"
    assert any(w["code"] == "under_constrained" for w in card["warnings"])
    step, v = apply(client, cid, card, E2[0])
    placed = json.loads(json.dumps(v["viewer"]))
    assert [i["id"] for i in placed["instances"]] == ["plate", "nema17"]
    assert v["parent_version_id"] == card["base_version_id"]

    # E3: the 10 m typo blocks until the user picks.
    card = interpret(client, cid, E3)
    assert card["status"] == "blocked" and card["blockers"][0]["code"] == "unit_suspect"
    assert "10 m (10 000 mm)" in card["blockers"][0]["message"]
    r = client.post(f"/v1/compositions/{cid}/apply", json={"prompt": E3[0], "steps": card["steps"], "base_version_id": card["base_version_id"]},
                    headers=DEV)
    assert r.status_code == 422 and r.json()["code"] == "blocked" and r.json()["blockers"][0]["code"] == "unit_suspect"
    card = answer(client, cid, card, 0)  # 10 mm
    assert card["status"] == "ready" and card["quantities"][0]["provenance"] == "user"
    step, v = apply(client, cid, card, E3[0])

    # E4: a nut wherever there are holes; 2 of 6 holes are M8 clearance, so the user is asked.
    card = interpret(client, cid, E4)
    assert card["blockers"][0]["code"] == "fit_mismatch"
    card = answer(client, cid, card, 0)  # the 4 Ø6.4 holes only
    assert card["counts"]["instances_added"] == 4 and card["counts"]["mates_added"] == 4
    assert card["reading"].startswith("Place 4 x ISO 4032 M6-1, one per Ø6.4 hole on plate")
    step, v = apply(client, cid, card, E4[0])
    ids = [i["id"] for i in v["viewer"]["instances"]]
    assert ids == ["plate", "nema17", "bracket", "iso4032_m6", "iso4032_m6_2", "iso4032_m6_3", "iso4032_m6_4"]
    assert v["validation_passed"], [c for c in v["viewer"]["checks"] if not c["passed"]]

    # Append-only history with one version per step.
    steps = client.get(f"/v1/compositions/{cid}/steps", headers=DEV).json()
    assert [s["number"] for s in steps] == [1, 2, 3, 4] and all(s["status"] == "applied" for s in steps)
    assert len({s["result_version_id"] for s in steps}) == 4
    got = client.get(f"/v1/compositions/{cid}", headers=DEV).json()
    assert got["head_version_id"] == v["id"] and got["model_id"] == v["model_id"] and got["applied_steps"] == 4

    # Replay without the LLM: the stored IR lowers to the same bytes the job built.
    ir_steps = [st for s in steps for st in s["ir"]["steps"]]
    from shilpa.api.compose import _library
    from shilpa.compose import resolve
    from shilpa.compose.expand import Expander
    from shilpa.compose.lower import lower
    from shilpa.contracts.composition import Step
    from shilpa.db import tx
    from shilpa.api.auth import principal

    me = principal("Bearer dev:dev@wayam.local")
    resolve.clear_cache()
    with llm.use_client(ExplodingClient()), tx() as s:
        applied = [Step.model_validate(d) for d in ir_steps]
        lib = _library(s, me, applied)
        replay = lower(Expander(lib).run(applied, set())[0], comp["name"])
    full = client.get(f"/v1/versions/{v['id']}", headers=DEV).json()
    assert spec_json(replay) == spec_json(full["recipe"])
    assert spec_json(replay).encode() == spec_json(json.loads(json.dumps(full["recipe"]))).encode()


def test_worked_example_e6_bearing_on_shaft(client, project):
    cid = new_composition(client, project, "Shaft")["id"]
    card = interpret(client, cid, E6_BASE)
    apply(client, cid, card, E6_BASE[0])
    card = interpret(client, cid, E6)
    assert card["status"] == "ready" and any(a["value"] == "press_fit" for a in card["assumptions"])
    step, v = apply(client, cid, card, E6[0])
    (mate,) = card["spec"]["mates"]
    assert mate["type"] == "fixed" and mate["offset"] == 15.0 and mate["intent"] == "press_fit"
    checks = {c["name"]: c for c in v["viewer"]["checks"]}
    assert checks["interference"]["passed"]


def test_roles_tenants_and_idempotency(client, project):
    cid = new_composition(client, project, "Rules")["id"]
    # Viewers read but never write.
    assert client.get(f"/v1/compositions/{cid}", headers=VIEWER).status_code == 200
    assert client.get(f"/v1/compositions/{cid}/steps", headers=VIEWER).status_code == 200
    assert client.post("/v1/compositions", json={"project_id": project}, headers=VIEWER).status_code == 403
    assert client.post(f"/v1/compositions/{cid}/interpret", json={"prompt": "use @plate"}, headers=VIEWER).status_code == 403
    assert client.post(f"/v1/compositions/{cid}/apply", json={"steps": E1[1]}, headers=VIEWER).status_code == 403
    # Another tenant sees nothing.
    for method, path, body in (("get", f"/v1/compositions/{cid}", None), ("get", f"/v1/compositions/{cid}/steps", None),
                               ("post", f"/v1/compositions/{cid}/interpret", {"prompt": "use @plate"}),
                               ("post", f"/v1/compositions/{cid}/apply", {"steps": E1[1]})):
        r = getattr(client, method)(path, headers=OTHER, **({"json": body} if body else {}))
        assert r.status_code == 404, (path, r.text)
    assert client.post("/v1/compositions", json={"project_id": project}, headers=OTHER).status_code == 404
    assert client.get(f"/v1/projects/{project}/compositions", headers=OTHER).status_code == 404

    # The other tenant's library does not contain our plate, by mention or by a forged pinned reference.
    other_proj = client.post("/v1/projects", json={"name": "Other"}, headers=OTHER).json()["id"]
    ocid = client.post("/v1/compositions", json={"project_id": other_proj}, headers=OTHER).json()["id"]
    with llm.use_client(FakeComposer(E1[1])):
        card = client.post(f"/v1/compositions/{ocid}/interpret", json={"prompt": E1[0]}, headers=OTHER).json()
    assert card["status"] == "blocked" and card["blockers"][0]["code"] == "unknown_part"
    mine = interpret(client, cid, E1)
    forged = client.post(f"/v1/compositions/{ocid}/interpret", json={"steps": mine["steps"]}, headers=OTHER).json()
    assert forged["status"] == "blocked" and {b["code"] for b in forged["blockers"]} == {"unknown_part"}
    pinned = [{"text": "@plate", "ref": {"item": mine["mentions"][0]["ref"]["item"], "version": mine["mentions"][0]["ref"]["version"]}}]
    with llm.use_client(FakeComposer(E1[1])):
        card = client.post(f"/v1/compositions/{ocid}/interpret", json={"prompt": E1[0], "mentions": pinned}, headers=OTHER).json()
    assert card["status"] == "blocked" and "not in your library" in card["blockers"][0]["message"]

    # Kill switch: prose needs the model; without a fake client the API answers 503, never a real call.
    r = client.post(f"/v1/compositions/{cid}/interpret", json={"prompt": E1[0]}, headers=DEV)
    assert r.status_code == 503 and r.json()["code"] == "planner_disabled"

    # Idempotent apply, stale base and a running step.
    body = {"prompt": E1[0], "steps": mine["steps"], "base_version_id": None}
    with llm.use_client(ExplodingClient()):
        a = client.post(f"/v1/compositions/{cid}/apply", json=body, headers={**DEV, "Idempotency-Key": "k1"})
        b = client.post(f"/v1/compositions/{cid}/apply", json=body, headers={**DEV, "Idempotency-Key": "k1"})
        assert a.status_code == b.status_code == 202 and a.json()["step"]["id"] == b.json()["step"]["id"]
        busy = client.post(f"/v1/compositions/{cid}/apply", json=body, headers={**DEV, "Idempotency-Key": "k2"})
        assert busy.status_code == 409 and busy.json()["code"] == "step_running"
    pump(client, a.json()["job"]["id"])
    with llm.use_client(ExplodingClient()):
        stale = client.post(f"/v1/compositions/{cid}/apply", json=body, headers={**DEV, "Idempotency-Key": "k3"})
    assert stale.status_code == 409 and stale.json()["code"] == "stale_revision"
    assert len(client.get(f"/v1/compositions/{cid}/steps", headers=DEV).json()) == 1


def test_bad_input(client, project):
    cid = new_composition(client, project, "Bad")["id"]
    r = client.post(f"/v1/compositions/{cid}/interpret", json={"prompt": "", "steps": [{"id": "x", "op": "add"}]}, headers=DEV)
    assert r.status_code == 422 and r.json()["code"] == "invalid_ir"
    r = client.post(f"/v1/compositions/{cid}/interpret", json={"prompt": "x", "mentions": [{"text": "not a mention", "ref": {"item": "a"}}]},
                    headers=DEV)
    assert r.status_code == 422 and r.json()["code"] == "invalid_mention"
    r = client.post(f"/v1/compositions/{cid}/interpret", json={"prompt": "   "}, headers=DEV)
    assert r.status_code == 400
    assert client.get("/v1/compositions/nope", headers=DEV).status_code == 404
