"""Request routing and the LLM kill switch. No test here reaches a model: fakes only."""

import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from shilpa.agent import llm, router
from shilpa.api.app import app
from shilpa.settings import Settings, settings

from .test_workflow import DEV


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


class FakeClient:
    """Stands in for AzureOpenAI: records requests and answers with a fixed JSON body."""

    def __init__(self, answer: dict):
        self.answer = answer
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.requests.append(kw)
        msg = SimpleNamespace(content=json.dumps(self.answer), refusal=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")],
                               usage=SimpleNamespace(prompt_tokens=12, completion_tokens=5), model="fake")


def budget():
    return llm.Budget(input_tokens=1000, output_tokens=1000, deadline=time.time() + 60)


@pytest.mark.parametrize("text,kind", [
    ("Mounting plate 80 x 40 x 8 mm with four 6 mm holes", "part"),
    ("Steel spacer with 20 mm OD and 10 mm ID, 12 mm long", "part"),
    ("Pipe flange, 120 mm OD, 6 bolt holes on a 95 mm PCD", "part"),
    ("L bracket bent from 2 mm steel sheet with a 3 mm bend radius", "sheet_metal"),
    ("Sheet metal enclosure tray with hemmed edges and a flat pattern DXF", "sheet_metal"),
    ("A hinge assembly: base, pin and a lid that swings 100 degrees", "assembly"),
    ("Shaft in two bearings on a base plate, check the clearance", "assembly"),
    ("A carriage on a rail with two end stops, slider joint", "assembly"),
    ("Design a gravel bike for a 180 cm rider", "product"),
    ("A bicycle frame and wheels", "product"),
])
def test_rules_route(text, kind):
    r = router.classify_rules(text)
    assert r.kind == kind, r
    assert r.supported and r.method == "rules"


@pytest.mark.parametrize("text", ["Design a PCB for an Arduino shield", "Write a python script to sort files",
                                  "Floor plan for a two bedroom house", "Run an FEA stress analysis of my bracket"])
def test_unsupported_is_explained(text):
    r = router.classify_rules(text)
    assert r.kind == "unsupported" and not r.supported and r.reason.startswith("Not supported")


def test_settings_kill_switch_defaults(monkeypatch):
    monkeypatch.delenv("SHILPA_LLM", raising=False)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "")
    s = Settings(llm_mode="off")
    assert not s.llm_enabled and not s.llm_configured and s.planner_status == "disabled"
    s = Settings(llm_mode="on", aoai_endpoint="https://x", aoai_deployment="d")
    assert s.llm_enabled and s.llm_configured and s.planner_status == "online"
    s = Settings(llm_mode="off", aoai_endpoint="https://x", aoai_deployment="d")
    assert not s.llm_configured and s.planner_status == "disabled"
    # The test environment has no endpoint, so the switch is off by default.
    assert settings.llm_mode == "off" and settings.planner_status == "disabled"


def test_every_llm_call_raises_typed_error():
    with pytest.raises(llm.PlannerDisabled) as exc:
        llm.call_structured(system="s", user="u", schema_name="x", schema={"type": "object"}, budget=budget())
    assert "AI planner is disabled" in exc.value.info.message and exc.value.info.retryable is False
    with pytest.raises(llm.PlannerDisabled):
        llm._client()
    with pytest.raises(llm.PlannerDisabled):
        router.classify_llm("a hinge", budget())


def test_fake_client_runs_the_llm_code_path():
    fake = FakeClient({"kind": "assembly", "reason": "several parts with a joint"})
    with llm.use_client(fake):
        r = router.classify_llm("two plates joined by a hinge", budget())
    assert r.kind == "assembly" and r.method == "llm"
    req = fake.requests[0]
    assert req["response_format"]["json_schema"]["strict"] is True and "two plates" in req["messages"][1]["content"]
    with pytest.raises(llm.PlannerDisabled):  # the fake is gone again
        router.classify_llm("x", budget())


def test_unsure_route_does_not_call_the_model():
    r = router.classify("something vague", budget())
    assert r.method == "rules" and "disabled" in (r.note or "")


def test_unsure_route_uses_the_model_when_enabled(monkeypatch):
    monkeypatch.setattr(router, "settings", Settings(llm_mode="on", aoai_endpoint="https://x", aoai_deployment="d"))
    fake = FakeClient({"kind": "sheet_metal", "reason": "a folded cover"})
    with llm.use_client(fake):
        r = router.classify("a cover for my thing", budget())
    assert r.kind == "sheet_metal" and r.method == "llm" and len(fake.requests) == 1


def test_health_reports_planner_disabled(client):
    h = client.get("/v1/health").json()
    assert h["planner"] == "disabled" and h["llm_configured"] is False and h["llm_enabled"] is False
    assert set(h["job_kinds"]) == {"part", "assembly", "sheet_metal", "product"}


def test_language_endpoints_answer_planner_disabled(client):
    pid = client.post("/v1/projects", json={"name": "kill switch"}, headers=DEV).json()["id"]
    r = client.post(f"/v1/projects/{pid}/specifications", json={"prompt": "a plate 80 x 40 x 8"}, headers=DEV)
    assert r.status_code == 503 and r.json()["code"] == "planner_disabled"
    assert "AI planner is disabled" in r.json()["message"]


def test_route_endpoint(client):
    r = client.post("/v1/route", json={"prompt": "hinge assembly with a lid"}, headers=DEV).json()
    assert r["kind"] == "assembly" and r["planner"] == "disabled"
    r = client.post("/v1/route", json={"prompt": "design a website"}, headers=DEV).json()
    assert r["kind"] == "unsupported" and not r["supported"]
