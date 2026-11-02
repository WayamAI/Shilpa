"""Planner cost controls: per-request examples, per-stage models, result cache, provenance and price estimates.

Fakes only: no test here reaches a model service.
"""

import dataclasses
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from shilpa.agent import examples, llm, planner
from shilpa.agent.llm_cache import LLMCache
from shilpa.agent.schemas import from_recipe
from shilpa.contracts.errors import ShilpaError

SCHEMA = {"type": "object", "properties": {"a": {"type": "number"}}, "required": ["a"], "additionalProperties": False}
CORPUS = Path(planner.CORPUS)


class FakeClient:
    def __init__(self, answer, cached_tokens=None):
        self.answer, self.requests, self.cached_tokens = answer, [], cached_tokens
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.requests.append(kw)
        msg = SimpleNamespace(content=json.dumps(self.answer), refusal=None)
        usage = SimpleNamespace(prompt_tokens=1000, completion_tokens=200,
                                prompt_tokens_details=None if self.cached_tokens is None
                                else SimpleNamespace(cached_tokens=self.cached_tokens))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")], usage=usage,
                               model=kw["model"] or "fake")


def budget():
    return llm.Budget(100_000, 50_000, time.time() + 60)


def with_settings(monkeypatch, **kw):
    monkeypatch.setattr(llm, "settings", dataclasses.replace(llm.settings, **kw))


def call(b, purpose="plan", cache=True, user="u", **kw):
    return llm.call_structured(system="S", user=user, schema_name="x", schema=SCHEMA, budget=b, purpose=purpose,
                               cache=cache, **kw)


# ------------------------------------------------------------------ 1. per-request examples


def test_selection_is_relevant_deterministic_and_bounded():
    ids = examples.select_example_ids("flange with a bolt circle of 6 holes on a 115 mm PCD", 3, "flange")
    assert len(ids) == 3 and ids == sorted(ids) and sum(i.startswith("F") for i in ids) >= 2
    assert ids == examples.select_example_ids("flange with a bolt circle of 6 holes on a 115 mm PCD", 3, "flange")
    assert examples.select_example_ids("swept pipe with a 90 degree bend", 3)[0:1] == ["N02"] or \
        "N02" in examples.select_example_ids("swept pipe with a 90 degree bend", 3)
    assert examples.select_example_ids("anything", 0) == []
    assert len(examples.select_example_ids("zzz qqq", 3)) == 3  # no overlap: padded from the defaults
    assert examples.select_example_ids("zzz qqq", 3) == sorted(examples.DEFAULT_IDS[:3])


def test_plan_system_keeps_a_static_prefix_and_is_smaller(monkeypatch):
    with_settings(monkeypatch, plan_examples_k=3)
    monkeypatch.setattr(planner, "settings", llm.settings)
    a = planner.plan_system("hollow stepped shaft with a bore", "shaft")
    b = planner.plan_system("flange with bolt circle", "flange")
    prefix = planner.PLAN_SYSTEM.split("{examples}")[0]
    assert a.startswith(prefix) and b.startswith(prefix) and a != b  # fixed instructions first, examples after
    assert a.count("Example - ") == 3
    legacy = planner.plan_system("x", None, -1)
    assert legacy.count("Example - ") == len(planner.EXAMPLE_IDS) and len(a) < 0.8 * len(legacy)


# ------------------------------------------------------------------ 2. per-stage models


def test_stage_models_default_to_the_single_model_azure(monkeypatch):
    with_settings(monkeypatch, aoai_deployment="base", model_intake="", model_plan="plan-dep", model_repair="repair-dep", model_edit="")
    fake = FakeClient({"a": 1})
    with llm.use_client(fake):
        for stage in ("intake", "plan", "repair", "edit"):
            call(budget(), purpose=stage, cache=False)
    assert [r["model"] for r in fake.requests] == ["base", "plan-dep", "repair-dep", "base"]


def test_stage_models_ollama(monkeypatch):
    import httpx

    with_settings(monkeypatch, llm_provider="ollama", llm_mode="on", ollama_api_key="k", ollama_model="base",
                  model_plan="", model_edit="edit-model")
    sent = []

    def post(url, json=None, timeout=None, headers=None):
        sent.append(json["model"])
        body = {"model": json["model"], "message": {"content": '{"a": 1}'}, "done_reason": "stop",
                "prompt_eval_count": 10, "eval_count": 2}
        return SimpleNamespace(status_code=200, json=lambda: body, text="")

    monkeypatch.setattr(httpx, "post", post)
    b = budget()
    call(b, purpose="plan", cache=False)
    call(b, purpose="edit", cache=False)
    assert sent == ["base", "edit-model"] and [c["model"] for c in b.calls] == ["base", "edit-model"]


def test_stage_model_lookup():
    from shilpa.settings import Settings

    s = dataclasses.replace(Settings(), model_intake="cheap", model_plan="", model_repair="r", model_edit="")
    assert s.stage_model("intake") == "cheap" and s.stage_model("repair") == "r"
    assert s.stage_model("plan") is None and s.stage_model("edit") is None and s.stage_model("route") is None


# ------------------------------------------------------------------ 3. result cache


@pytest.fixture
def cache():
    c = LLMCache(ttl_s=3600, max_entries=100)
    c.clear()
    yield c
    c.clear()


def test_cache_hit_costs_zero_tokens_and_is_flagged(cache):
    fake = FakeClient({"a": 1})
    b = budget()
    with llm.use_client(fake), llm.use_cache(cache):
        first = call(b)
        second = call(b)
    assert first == second == {"a": 1} and len(fake.requests) == 1
    live, hit = b.calls
    assert live["cached"] is False and live["input_tokens"] == 1000
    assert hit["cached"] is True and hit["input_tokens"] == 0 and hit["output_tokens"] == 0
    assert hit["tokens_saved"] == [1000, 200] and hit["cost_usd"] == 0.0
    assert b.used_input == 1000 and b.used_output == 200  # the hit consumed no budget


def test_cache_key_covers_model_schema_prompt_and_user(cache, monkeypatch):
    fake = FakeClient({"a": 1})
    with llm.use_client(fake), llm.use_cache(cache):
        call(budget(), user="one")
        call(budget(), user="two")
        llm.call_structured(system="S2", user="one", schema_name="x", schema=SCHEMA, budget=budget(), purpose="plan", cache=True)
        with_settings(monkeypatch, aoai_deployment="other")
        call(budget(), user="one")
    assert len(fake.requests) == 4 and cache.count() == 4


def test_repair_and_uncached_calls_bypass_the_cache(cache):
    fake = FakeClient({"a": 1})
    with llm.use_client(fake), llm.use_cache(cache):
        call(budget(), purpose="repair", cache=False)
        call(budget(), purpose="repair", cache=False)
    assert len(fake.requests) == 2 and cache.count() == 0


def test_cache_can_be_disabled(cache, monkeypatch):
    with_settings(monkeypatch, llm_cache=False)
    fake = FakeClient({"a": 1})
    with llm.use_client(fake), llm.use_cache(cache):
        call(budget())
        call(budget())
    assert len(fake.requests) == 2 and cache.count() == 0


def test_fakes_do_not_touch_the_real_cache_without_use_cache(monkeypatch):
    before = LLMCache().count()
    fake = FakeClient({"a": 1})
    with llm.use_client(fake):
        call(budget())
        call(budget())
    assert len(fake.requests) == 2 and LLMCache().count() == before


def test_rejected_replies_are_not_cached(cache):
    fake = FakeClient({"a": 1})

    def reject(data):
        raise ValueError("no good")

    with llm.use_client(fake), llm.use_cache(cache):
        call(budget(), validate=reject)
        assert cache.count() == 0
        call(budget(), validate=lambda d: None)
        assert cache.count() == 1


def test_ttl_and_size_bounds():
    LLMCache().clear()
    expired = LLMCache(ttl_s=-1)
    expired.put("k", {"data": {}})
    assert expired.get("k") is None
    small = LLMCache(ttl_s=3600, max_entries=3)
    small.clear()
    for i in range(6):
        small.put(f"k{i}", {"data": {"i": i}})
        time.sleep(0.01)
    assert small.count() == 3 and small.get("k5") is not None and small.get("k0") is None
    small.clear()


# ------------------------------------------------------------------ 4. provenance and cost


def test_call_records_provenance_cached_tokens_and_cost(monkeypatch):
    with_settings(monkeypatch, aoai_deployment="dep", model_prices={"dep": (2.0, 10.0, 0.5)})
    fake = FakeClient({"a": 1}, cached_tokens=800)
    b = budget()
    with llm.use_client(fake):
        call(b, cache=False, prompt_template="TEMPLATE")
    c = b.calls[0]
    assert c["model"] == "dep" and c["cached"] is False and c["provider_cached_tokens"] == 800
    assert c["prompt_version"] == llm.prompt_version("TEMPLATE") and len(c["prompt_version"]) == 12
    # 200 uncached in x $2 + 800 cached x $0.5 + 200 out x $10, per million tokens
    assert c["cost_usd"] == pytest.approx((200 * 2 + 800 * 0.5 + 200 * 10) / 1e6)


def test_unknown_model_cost_is_none_not_invented():
    from shilpa.settings import MODEL_PRICES_USD_PER_MTOK, Settings

    assert MODEL_PRICES_USD_PER_MTOK == {}  # TODO(user) in settings.py: fill in real prices
    assert Settings().estimate_cost_usd("beam", 1000, 100) is None
    b = budget()
    with llm.use_client(FakeClient({"a": 1})):
        call(b, cache=False)
    assert b.calls[0]["cost_usd"] is None and b.calls[0]["provider_cached_tokens"] is None
    totals = llm.usage_totals(b.calls)
    assert totals["cost_usd"] == 0.0 and totals["cost_unpriced_calls"] == 1 and totals["llm_calls"] == 1


def test_prompt_version_tracks_the_template_not_the_examples(monkeypatch):
    with_settings(monkeypatch, plan_examples_k=3)
    monkeypatch.setattr(planner, "settings", llm.settings)
    assert llm.prompt_version(planner.PLAN_SYSTEM) == llm.prompt_version(planner.PLAN_SYSTEM)
    assert llm.prompt_version(planner.PLAN_SYSTEM) != llm.prompt_version(planner.INTAKE_SYSTEM)


# ------------------------------------------------------------------ planner integration


def plan_answer():
    fx = json.loads((CORPUS / "P01.json").read_text(encoding="utf-8"))
    return {**from_recipe(fx["recipe"]), "change_summary": None}


def test_plan_uses_selected_examples_caches_and_repair_does_not(cache, monkeypatch):
    with_settings(monkeypatch, plan_examples_k=3)
    monkeypatch.setattr(planner, "settings", llm.settings)
    fake = FakeClient(plan_answer())
    req = {"family": "plate", "summary": "plate with four corner holes", "units": "mm", "dimensions": [], "features": ["four corner holes"],
           "assumptions": []}
    b = budget()
    with llm.use_client(fake), llm.use_cache(cache):
        r1 = planner.plan_recipe(req, b)
        r2 = planner.plan_recipe(req, b)
        assert r1 == r2 and len(fake.requests) == 1 and b.calls[1]["cached"] is True
        system = fake.requests[0]["messages"][0]["content"]
        assert system.startswith(planner.PLAN_SYSTEM.split("{examples}")[0]) and system.count("Example - ") == 3
        planner.repair_recipe(r1, {"code": "x"}, None, b)
        planner.repair_recipe(r1, {"code": "x"}, None, b)
    assert len(fake.requests) == 3 and [c["cached"] for c in b.calls[2:]] == [False, False]
    assert all(c["prompt_version"] == llm.prompt_version(planner.PLAN_SYSTEM) for c in b.calls)


def test_invalid_plan_is_not_cached(cache):
    fake = FakeClient({"name": "bad"})
    with llm.use_client(fake), llm.use_cache(cache):
        with pytest.raises(ShilpaError):
            planner.plan_recipe({"family": "plate", "summary": "p"}, budget())
    assert cache.count() == 0


def test_eval_summary_reports_tokens_cache_and_cost():
    import importlib.util

    spec = importlib.util.spec_from_file_location("run_language", Path(__file__).parents[1] / "evals" / "run_language.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    usage = {"llm_calls": 2, "cache_hits": 1, "provider_cached_tokens": 5, "cost_usd": 0.01, "cost_unpriced_calls": 0}
    row = {"id": "L1", "category": "c", "split": "dev", "expected": "build", "outcome": "build", "passed": True, "notes": [],
           "intake_tokens": [100, 10], "job_tokens": [300, 40], "repairs": 0, "intake_s": 1.0, "job_s": 2.0, "usage": usage}
    s = mod.summarize([row, {**row, "id": "L2", "usage": {**usage, "cache_hits": 0}}])
    assert s["tokens"]["total"] == 900 and s["tokens"]["avg_per_task"] == 450
    assert s["cache"] == {"llm_calls": 4, "cache_hits": 1, "hit_rate": 0.25}
    assert s["cost"]["estimated_usd_per_task"] == 0.01 and s["cost"]["unpriced_calls"] == 0
    unpriced = {**usage, "cost_usd": 0.0, "cost_unpriced_calls": 2}
    assert mod.summarize([{**row, "usage": unpriced}])["cost"]["estimated_usd_per_task"] is None
