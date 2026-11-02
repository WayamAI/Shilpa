"""Model gateway with structured outputs and a shared job budget (blueprint section 9).

Two services, chosen by ``SHILPA_LLM_PROVIDER``: Azure OpenAI (``azure``, strict
JSON-schema structured outputs enforced by the service) and Ollama Cloud
(``ollama``, its native chat API). Ollama Cloud does not enforce the schema for
reasoning models, so the schema goes into the system prompt, thinking is turned
off, the reply is parsed leniently (markdown fences stripped), checked against
the schema with ``jsonschema``, and sent back once with the validation errors
when it does not match.

Every call goes through ``call_structured``. It charges the job budget before and
after the call, and turns refusals, truncation, timeouts and malformed JSON into
typed ShilpaErrors so the workflow persists a clear result instead of an empty
success. SDK retries are disabled so retries are not multiplied across layers.

Kill switch: with ``SHILPA_LLM=off`` (the default when ``AZURE_OPENAI_ENDPOINT`` is
empty) every call raises ``PlannerDisabled`` before any real client is created (the
check sits in ``_client``, ahead of the SDK import), so no request can reach a paid
API. Tests install a fake client with ``use_client`` (or by patching ``_client``);
a fake never leaves the process, so it is allowed while the switch is off.
"""

from __future__ import annotations

import copy
import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from ..contracts.errors import ErrorCode, ShilpaError
from ..settings import settings
from .llm_cache import LLMCache, cache_key, prompt_version

_UNSUPPORTED_KEYWORDS = {
    "default", "title", "minLength", "maxLength", "minItems", "maxItems",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "discriminator", "format",
}


PLANNER_DISABLED_MESSAGE = ("The AI planner is disabled on this server (SHILPA_LLM=off; Azure OpenAI is not configured "
                            "or is switched off), so requests in plain language "
                            "cannot be planned. Start from a reference part, assembly or sheet-metal example instead, "
                            "or edit parameters directly.")


class PlannerDisabled(ShilpaError):
    """Raised for every model call while the kill switch is off. Never retryable."""

    def __init__(self, message: str = PLANNER_DISABLED_MESSAGE):
        super().__init__(ErrorCode.INTERNAL, message, details={"planner": "disabled"})
        self.info.retryable = False


# A fake client installed by tests (``use_client``). Real clients are only ever built by ``_client``.
_client_override: Any = None


@contextmanager
def use_client(fake: Any) -> Iterator[Any]:
    """Route every ``call_structured`` through ``fake`` (an object with ``chat.completions.create``)."""
    global _client_override
    prev, _client_override = _client_override, fake
    try:
        yield fake
    finally:
        _client_override = prev


# Result cache. Real calls use the llm_cache table in the application database; a fake client (tests) only caches when a test
# installs a cache explicitly with ``use_cache``, so fakes never read or write the developer's real cache.
_cache_override: LLMCache | None = None


@contextmanager
def use_cache(cache: LLMCache) -> Iterator[LLMCache]:
    global _cache_override
    prev, _cache_override = _cache_override, cache
    try:
        yield cache
    finally:
        _cache_override = prev


def _active_cache() -> LLMCache | None:
    if not settings.llm_cache:
        return None
    if _cache_override is not None:
        return _cache_override
    if _client_override is not None:
        return None
    return LLMCache(settings.llm_cache_ttl_s, settings.llm_cache_max_entries)


def _record(budget: "Budget", *, purpose: str, input_tokens: int, output_tokens: int, ms: int, model: str | None,
            version: str, cached: bool = False, provider_cached_tokens: int | None = None, **extra) -> None:
    """One budget.calls entry: usage plus provenance (model, prompt version, cache flags) and estimated cost."""
    cost = 0.0 if cached else settings.estimate_cost_usd(model, input_tokens, output_tokens, provider_cached_tokens)
    budget.calls.append({"purpose": purpose, "input_tokens": input_tokens, "output_tokens": output_tokens, "ms": ms,
                         "model": model, "prompt_version": version, "cached": cached,
                         "provider_cached_tokens": provider_cached_tokens, "cost_usd": cost, **extra})


def usage_totals(calls: list[dict], prior: dict | None = None) -> dict:
    """Cost and cache counters for a list of budget.calls entries, added to ``prior`` (a budget_used dict).

    cost_usd sums the estimated cost of calls whose model has a listed price; calls without one are counted in
    cost_unpriced_calls instead of being guessed.
    """
    prior = prior or {}
    return {"llm_calls": prior.get("llm_calls", 0) + len(calls),
            "cache_hits": prior.get("cache_hits", 0) + sum(1 for c in calls if c.get("cached")),
            "provider_cached_tokens": prior.get("provider_cached_tokens", 0) + sum(c.get("provider_cached_tokens") or 0 for c in calls),
            "cost_usd": round(prior.get("cost_usd", 0.0) + sum(c.get("cost_usd") or 0.0 for c in calls), 6),
            "cost_unpriced_calls": prior.get("cost_unpriced_calls", 0) + sum(1 for c in calls if c.get("cost_usd") is None)}


def ensure_enabled() -> None:
    """Raise the typed, user-facing error when the kill switch is off and no fake client is installed."""
    if _client_override is None and not settings.llm_enabled:
        raise PlannerDisabled()


@dataclass
class Budget:
    """Mutable view of one job's remaining LLM budget. Persisted by the caller."""

    input_tokens: int
    output_tokens: int
    deadline: float  # time.time() epoch seconds
    used_input: int = 0
    used_output: int = 0
    calls: list[dict] = field(default_factory=list)

    def check(self) -> None:
        if time.time() > self.deadline:
            raise ShilpaError(ErrorCode.BUDGET_EXHAUSTED, "job elapsed-time budget exhausted")
        if self.used_input >= self.input_tokens or self.used_output >= self.output_tokens:
            raise ShilpaError(ErrorCode.BUDGET_EXHAUSTED, "job token budget exhausted")


def strict_schema(schema: dict) -> dict:
    """Convert a pydantic JSON schema into the strict structured-output subset.

    Every object gets additionalProperties false and all properties required;
    properties that were optional become nullable. Unsupported keywords are dropped
    (pydantic re-validates the result anyway).
    """
    schema = copy.deepcopy(schema)

    def walk(node):
        if isinstance(node, dict):
            for k in list(node):
                if k in _UNSUPPORTED_KEYWORDS:
                    node.pop(k)
            if "const" in node:
                node["enum"] = [node.pop("const")]
            if node.get("type") == "object" and "properties" in node:
                req = set(node.get("required", []))
                for name, prop in node["properties"].items():
                    if name not in req:
                        node["properties"][name] = _nullable(prop)
                node["required"] = list(node["properties"])
                node["additionalProperties"] = False
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(schema)
    return schema


def _nullable(prop: dict) -> dict:
    if "anyOf" in prop:
        if not any(p.get("type") == "null" for p in prop["anyOf"]):
            prop["anyOf"].append({"type": "null"})
        return prop
    if "$ref" in prop:
        return {"anyOf": [prop, {"type": "null"}]}
    t = prop.get("type")
    if isinstance(t, str) and t != "null":
        prop["type"] = [t, "null"]
    elif isinstance(t, list) and "null" not in t:
        prop["type"] = t + ["null"]
    if "enum" in prop and None not in prop["enum"]:
        prop["enum"] = prop["enum"] + [None]
    return prop


def _client():
    if _client_override is not None:
        return _client_override
    ensure_enabled()  # the kill switch is checked before the SDK is even imported
    from openai import AzureOpenAI

    if not settings.llm_configured:
        raise ShilpaError(
            ErrorCode.INTERNAL,
            "Azure OpenAI is not configured: set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT in .env",
        )
    kwargs = dict(azure_endpoint=settings.aoai_endpoint, api_version=settings.aoai_api_version,
                  timeout=settings.aoai_timeout_s, max_retries=0)
    if settings.aoai_api_key:
        return AzureOpenAI(api_key=settings.aoai_api_key, **kwargs)
    # Keyless Entra ID: the local az CLI login, or DefaultAzureCredential (managed identity in Azure).
    return AzureOpenAI(azure_ad_token_provider=_token_provider(), **kwargs)


@lru_cache(maxsize=1)
def _token_provider():
    from azure.identity import AzureCliCredential, DefaultAzureCredential, get_bearer_token_provider

    cred = AzureCliCredential(process_timeout=30) if settings.aoai_auth == "azure_cli" else DefaultAzureCredential()
    return get_bearer_token_provider(cred, "https://cognitiveservices.azure.com/.default")


# ---------------------------------------------------------------- Ollama Cloud

OLLAMA_SCHEMA_RULES = (
    "\n\nRespond with exactly one JSON object and nothing else: no markdown fences, no prose before or after. "
    "It must validate against the JSON Schema below. Use exactly these property names and no others; every listed "
    "property is required (use null where the schema allows null and the value is unknown); string values must be one "
    "of the enum values where an enum is given.\nJSON Schema:\n")


def _json_object(text: str) -> dict:
    """The JSON object in a reply, tolerating markdown fences and text around it."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        t = t.rsplit("```", 1)[0]
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j < i:
        raise json.JSONDecodeError("no JSON object in the reply", t, 0)
    return json.loads(t[i:j + 1])


def _ollama_messages(system: str, user: str | list, schema: dict) -> list[dict]:
    """Ollama chat messages: the schema goes into the system prompt (Ollama Cloud does not enforce ``format``
    for reasoning models), and OpenAI-style content parts become text plus base64 ``images``."""
    msg: dict[str, Any] = {"role": "user", "content": user}
    if isinstance(user, list):
        texts, images = [], []
        for part in user:
            if part.get("type") == "text":
                texts.append(part["text"])
            elif part.get("type") == "image_url":
                url = part["image_url"]["url"]
                images.append(url.split(",", 1)[1] if url.startswith("data:") else url)
        msg = {"role": "user", "content": "\n\n".join(texts), **({"images": images} if images else {})}
    return [{"role": "system", "content": system + OLLAMA_SCHEMA_RULES + json.dumps(schema)}, msg]


def _ollama_model(messages: list[dict], stage: str | None = None) -> str:
    """The vision model for requests that carry images, else the stage's model, else the text model."""
    has_images = any(m.get("images") for m in messages)
    if has_images:
        return settings.ollama_vision_model or settings.ollama_model
    return settings.stage_model(stage) or settings.ollama_model


def _ollama_chat(messages: list[dict], schema: dict, max_out: int, timeout: float, model: str | None = None) -> dict:
    import httpx

    ensure_enabled()
    if not settings.llm_configured:
        raise ShilpaError(ErrorCode.INTERNAL, "Ollama Cloud is not configured: set OLLAMA_API_KEY and OLLAMA_MODEL in .env")
    body = {"model": model or _ollama_model(messages), "messages": messages, "stream": False, "format": schema, "think": False,
            "options": {"temperature": 0, "num_predict": max_out}}
    headers = {"Authorization": f"Bearer {settings.ollama_api_key}"}
    r = None
    for attempt in (1, 2):  # one retry for a dropped connection, rate limit or server error; none for timeouts
        try:
            r = httpx.post(f"{settings.ollama_base_url}/api/chat", json=body, timeout=timeout, headers=headers)
        except httpx.TimeoutException:
            raise ShilpaError(ErrorCode.MODEL_TIMEOUT, f"model call timed out after {timeout:g} s")
        except httpx.HTTPError as exc:
            if attempt == 2:
                raise ShilpaError(ErrorCode.INTERNAL, f"model service unreachable: {type(exc).__name__}")
            time.sleep(2)
            continue
        if r.status_code in (429, 500, 502, 503, 504) and attempt == 1:
            time.sleep(2)
            continue
        break
    if r.status_code != 200:
        detail = r.text[:200].replace(settings.ollama_api_key, "***") if settings.ollama_api_key else r.text[:200]
        raise ShilpaError(ErrorCode.INTERNAL, f"model service error {r.status_code}: {detail}")
    return r.json()


def _call_ollama(system: str, user: str | list, schema: dict, budget: Budget, max_out: int, purpose: str,
                 timeout_s: float | None, version: str = "") -> dict:
    """One schema-checked call, with one repair round when the reply does not match the schema."""
    from jsonschema import Draft202012Validator

    validator = Draft202012Validator(schema)
    messages = _ollama_messages(system, user, schema)
    model = _ollama_model(messages, purpose)
    timeout = timeout_s or settings.ollama_timeout_s
    for attempt in (1, 2):
        budget.check()
        t0 = time.time()
        d = _ollama_chat(messages, schema, max_out, timeout, model)
        in_tok, out_tok = int(d.get("prompt_eval_count") or 0), int(d.get("eval_count") or 0)
        budget.used_input += in_tok
        budget.used_output += out_tok
        _record(budget, purpose=purpose + (" (repair)" if attempt == 2 else ""), input_tokens=in_tok,
                output_tokens=out_tok, ms=round((time.time() - t0) * 1000), model=d.get("model") or model,
                version=version)
        content = (d.get("message") or {}).get("content") or ""
        if d.get("done_reason") == "length":
            raise ShilpaError(ErrorCode.MODEL_TRUNCATED, "model output was truncated; no partial plan is accepted")
        try:
            data = _json_object(content)
            problems = [f"{'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}"
                        for e in validator.iter_errors(data)]
        except json.JSONDecodeError as exc:
            data, problems = None, [f"the reply was not a JSON object ({exc.msg})"]
        if not problems:
            return data
        if attempt == 2:
            raise ShilpaError(ErrorCode.INVALID_SCHEMA, "model reply does not match the schema after one repair: "
                              + "; ".join(problems[:5]))
        messages = messages + [{"role": "assistant", "content": content},
                               {"role": "user", "content": "That reply does not match the JSON Schema: "
                                + "; ".join(problems[:12]) + ". Send the corrected JSON object only."}]
    raise AssertionError("unreachable")


def call_structured(
    *,
    system: str,
    user: str | list,
    schema_name: str,
    schema: dict,
    budget: Budget,
    max_output_tokens: int = 4000,
    purpose: str = "",
    timeout_s: float | None = None,
    cache: bool = False,
    validate: Any = None,
    prompt_template: str | None = None,
) -> dict:
    """One structured call. ``purpose`` doubles as the stage (intake | plan | repair | edit) that selects the model.

    ``cache=True`` serves/stores the reply in the content-addressed cache (only intake and plan opt in; a cache hit
    is recorded as 0 tokens with ``cached: true``). ``validate`` is run on a fresh reply before it is cached (an exception means
    do not store it), so a reply the caller would reject is never stored. ``prompt_template`` is the static part of the system prompt
    whose hash is recorded as ``prompt_version`` (defaults to the whole system prompt).
    """
    # The kill switch is enforced in ``_client`` / ``_ollama_chat``: no request leaves while SHILPA_LLM=off.
    budget.check()
    version = prompt_version(prompt_template or system)
    store = _active_cache() if cache else None
    key = None
    if store is not None:
        if settings.llm_provider == "ollama":
            has_images = isinstance(user, list) and any(p.get("type") == "image_url" for p in user)
            model = (settings.ollama_vision_model or settings.ollama_model) if has_images \
                else (settings.stage_model(purpose) or settings.ollama_model)
        else:
            model = settings.stage_model(purpose) or settings.aoai_deployment
        key = cache_key(settings.llm_provider, model, schema_name, schema, system, user)
        t0 = time.time()
        hit = store.get(key)
        if hit is not None:
            _record(budget, purpose=purpose, input_tokens=0, output_tokens=0, ms=round((time.time() - t0) * 1000),
                    model=model, version=version, cached=True,
                    tokens_saved=[hit.get("input_tokens", 0), hit.get("output_tokens", 0)])
            return copy.deepcopy(hit["data"])
    n_before = len(budget.calls)
    data = _call_provider(system, user, schema_name, schema, budget, max_output_tokens, purpose, timeout_s, version)
    if store is not None and key is not None:
        ok = True
        if validate is not None:
            try:
                validate(data)
            except Exception:  # noqa: BLE001 - the caller will reject this reply itself; just do not cache it
                ok = False
        if ok:
            made = budget.calls[n_before:]
            store.put(key, {"data": data, "input_tokens": sum(c["input_tokens"] for c in made),
                            "output_tokens": sum(c["output_tokens"] for c in made)})
    return data


def _call_provider(system, user, schema_name, schema, budget, max_output_tokens, purpose, timeout_s, version) -> dict:
    max_out = min(max_output_tokens, budget.output_tokens - budget.used_output)
    if _client_override is None and settings.llm_provider == "ollama":
        ensure_enabled()
        return _call_ollama(system, user, schema, budget, max_out, purpose, timeout_s, version)
    import openai

    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    t0 = time.time()
    model = settings.stage_model(purpose) or settings.aoai_deployment
    client = _client()
    if timeout_s is not None and hasattr(client, "with_options"):
        client = client.with_options(timeout=timeout_s)

    def create():
        return client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_schema", "json_schema": {"name": schema_name, "strict": True, "schema": schema}},
            max_completion_tokens=max_out,
        )

    try:
        try:
            resp = create()
        except (openai.InternalServerError, openai.APIConnectionError) as exc:
            if isinstance(exc, openai.APITimeoutError):
                raise
            # One retry for a transient service error; this is the only retry layer (SDK retries are off).
            budget.check()
            time.sleep(2)
            resp = create()
    except openai.APITimeoutError:
        raise ShilpaError(ErrorCode.MODEL_TIMEOUT, f"model call timed out after {timeout_s or settings.aoai_timeout_s:g} s")
    except openai.BadRequestError as exc:
        body = getattr(exc, "body", None) or {}
        code = (body.get("code") if isinstance(body, dict) else None) or ""
        if "content_filter" in str(code) or "content_filter" in str(exc) or "flagged" in str(exc).lower():
            raise ShilpaError(ErrorCode.MODEL_REFUSAL, "the model service declined this request (content safety filter); "
                              "remove unrelated instructions or code from the text and try again")
        raise ShilpaError(ErrorCode.INTERNAL, f"model request rejected: {exc}")
    except openai.APIError as exc:
        raise ShilpaError(ErrorCode.INTERNAL, f"model service error: {exc}")

    usage = resp.usage
    in_tok = usage.prompt_tokens if usage else 0
    out_tok = usage.completion_tokens if usage else 0
    budget.used_input += in_tok
    budget.used_output += out_tok
    details = getattr(usage, "prompt_tokens_details", None)
    provider_cached = getattr(details, "cached_tokens", None) if details is not None else None
    _record(budget, purpose=purpose, input_tokens=in_tok, output_tokens=out_tok, ms=round((time.time() - t0) * 1000),
            model=getattr(resp, "model", None) or model, version=version,
            provider_cached_tokens=provider_cached if isinstance(provider_cached, int) else None)

    choice = resp.choices[0]
    msg = choice.message
    if getattr(msg, "refusal", None):
        raise ShilpaError(ErrorCode.MODEL_REFUSAL, f"model refused: {msg.refusal}")
    if choice.finish_reason == "length":
        raise ShilpaError(ErrorCode.MODEL_TRUNCATED, "model output was truncated; no partial plan is accepted")
    if choice.finish_reason == "content_filter":
        raise ShilpaError(ErrorCode.MODEL_REFUSAL, "model output was blocked by the content filter")
    try:
        return json.loads(msg.content or "")
    except json.JSONDecodeError as exc:
        raise ShilpaError(ErrorCode.INVALID_SCHEMA, f"model returned malformed JSON: {exc}")
