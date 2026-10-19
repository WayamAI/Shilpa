"""Ollama Cloud adapter: schema in the prompt, lenient parsing, one repair round, kill switch. No network."""

import dataclasses
import json
import time

import pytest

from shilpa.agent import llm
from shilpa.contracts.errors import ErrorCode, ShilpaError

SCHEMA = {"type": "object", "properties": {"part": {"type": "string", "enum": ["plate", "shaft"]},
                                           "width_mm": {"type": ["number", "null"]}},
          "required": ["part", "width_mm"], "additionalProperties": False}
KEY = "test-key-123"


class FakeResponse:
    def __init__(self, status: int, body: dict | str):
        self.status_code = status
        self._body = body
        self.text = body if isinstance(body, str) else json.dumps(body)

    def json(self):
        return self._body


def reply(content: str, done: str = "stop") -> FakeResponse:
    return FakeResponse(200, {"model": "fake-model", "message": {"role": "assistant", "content": content},
                              "done_reason": done, "prompt_eval_count": 100, "eval_count": 20})


@pytest.fixture
def ollama(monkeypatch):
    """Point the gateway at Ollama with a scripted reply queue; returns (queue, sent requests)."""
    s = dataclasses.replace(llm.settings, llm_provider="ollama", llm_mode="on", ollama_api_key=KEY,
                            ollama_model="fake-model")
    monkeypatch.setattr(llm, "settings", s)
    queue, sent = [], []

    def post(url, json=None, timeout=None, headers=None):
        sent.append({"url": url, "json": json, "headers": headers})
        return queue.pop(0)

    import httpx

    monkeypatch.setattr(httpx, "post", post)
    return queue, sent


def budget():
    return llm.Budget(10_000, 4_000, time.time() + 60)


def call(b=None):
    return llm.call_structured(system="Extract.", user="a 120 mm plate", schema_name="req", schema=SCHEMA,
                               budget=b or budget(), purpose="test")


def test_schema_in_prompt_and_fenced_reply_parsed(ollama):
    queue, sent = ollama
    queue.append(reply('```json\n{"part": "plate", "width_mm": 120}\n```'))
    b = budget()
    assert call(b) == {"part": "plate", "width_mm": 120}
    req = sent[0]
    assert req["url"].endswith("/api/chat") and req["headers"]["Authorization"] == f"Bearer {KEY}"
    assert req["json"]["think"] is False and req["json"]["format"] == SCHEMA
    assert '"enum": ["plate", "shaft"]' in req["json"]["messages"][0]["content"]  # schema in the system prompt
    assert b.used_input == 100 and b.used_output == 20 and b.calls[0]["model"] == "fake-model"


def test_one_repair_round_with_the_errors(ollama):
    queue, sent = ollama
    queue += [reply('{"part": "aluminium plate", "width_mm": 120, "material": "al"}'),
              reply('{"part": "plate", "width_mm": 120}')]
    b = budget()
    assert call(b) == {"part": "plate", "width_mm": 120}
    repair = sent[1]["json"]["messages"][-1]["content"]
    assert "does not match" in repair and "aluminium plate" in repair and "material" in repair
    assert len(b.calls) == 2 and b.calls[1]["purpose"] == "test (repair)" and b.used_output == 40


def test_still_wrong_after_repair_is_a_typed_error(ollama):
    queue, _ = ollama
    queue += [reply("I think it is a plate."), reply('{"part": "bracket", "width_mm": null}')]
    with pytest.raises(ShilpaError) as e:
        call()
    assert e.value.code == ErrorCode.INVALID_SCHEMA and "bracket" in e.value.info.message


def test_truncated_reply(ollama):
    queue, _ = ollama
    queue.append(reply('{"part": "pla', done="length"))
    with pytest.raises(ShilpaError) as e:
        call()
    assert e.value.code == ErrorCode.MODEL_TRUNCATED


def test_service_error_never_echoes_the_key(ollama):
    queue, _ = ollama
    queue.append(FakeResponse(401, f"invalid key {KEY}"))
    with pytest.raises(ShilpaError) as e:
        call()
    assert KEY not in e.value.info.message and "401" in e.value.info.message


def test_one_retry_on_a_dropped_connection_or_server_error(ollama, monkeypatch):
    import httpx

    queue, sent = ollama
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    queue += [FakeResponse(503, "busy"), reply('{"part": "plate", "width_mm": 120}')]
    assert call()["part"] == "plate" and len(sent) == 2

    calls = {"n": 0}

    def flaky(url, json=None, timeout=None, headers=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.RemoteProtocolError("peer closed connection")
        return reply('{"part": "shaft", "width_mm": null}')

    monkeypatch.setattr(httpx, "post", flaky)
    assert call()["part"] == "shaft" and calls["n"] == 2


def test_kill_switch_blocks_ollama(monkeypatch):
    s = dataclasses.replace(llm.settings, llm_provider="ollama", llm_mode="off", ollama_api_key=KEY)
    monkeypatch.setattr(llm, "settings", s)

    def boom(*a, **k):
        raise AssertionError("no request may leave while SHILPA_LLM=off")

    import httpx

    monkeypatch.setattr(httpx, "post", boom)
    with pytest.raises(llm.PlannerDisabled):
        call()


def test_images_go_to_the_vision_model(ollama, monkeypatch):
    queue, sent = ollama
    monkeypatch.setattr(llm, "settings", dataclasses.replace(llm.settings, ollama_vision_model="fake-vision"))
    queue.append(reply('{"part": "plate", "width_mm": 120}'))
    llm.call_structured(system="Read.", user=[{"type": "text", "text": "p1"},
                                             {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}}],
                        schema_name="req", schema=SCHEMA, budget=budget())
    assert sent[0]["json"]["model"] == "fake-vision"
    queue.append(reply('{"part": "plate", "width_mm": 120}'))
    call()
    assert sent[1]["json"]["model"] == "fake-model"


def test_images_become_ollama_images():
    msgs = llm._ollama_messages("Read the drawing.", [{"type": "text", "text": "page 1"},
                                                      {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}}],
                                SCHEMA)
    assert msgs[1] == {"role": "user", "content": "page 1", "images": ["QUJD"]}
