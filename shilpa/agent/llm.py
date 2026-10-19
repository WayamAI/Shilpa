"""Azure OpenAI gateway with structured outputs and a shared job budget (blueprint section 9).

Every call goes through ``call_structured``. It charges the job budget before and
after the call, and turns refusals, truncation, timeouts and malformed JSON into
typed ShilpaErrors so the workflow persists a clear result instead of an empty
success. SDK retries are disabled so retries are not multiplied across layers.

Kill switch: with ``SHILPA_LLM=off`` (the default when ``AZURE_OPENAI_ENDPOINT`` is
empty) every call raises ``PlannerDisabled`` before any client is created, so no
request can reach a paid API. Tests install a fake client with ``use_client``;
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

_UNSUPPORTED_KEYWORDS = {
    "default", "title", "minLength", "maxLength", "minItems", "maxItems",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "discriminator", "format",
}


PLANNER_DISABLED_MESSAGE = ("The AI planner is disabled on this server (SHILPA_LLM=off), so requests in plain language "
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
) -> dict:
    ensure_enabled()
    budget.check()
    import openai

    max_out = min(max_output_tokens, budget.output_tokens - budget.used_output)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    t0 = time.time()
    client = _client()
    if timeout_s is not None and hasattr(client, "with_options"):
        client = client.with_options(timeout=timeout_s)

    def create():
        return client.chat.completions.create(
            model=settings.aoai_deployment,
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
    budget.calls.append({"purpose": purpose, "input_tokens": in_tok, "output_tokens": out_tok,
                         "ms": round((time.time() - t0) * 1000), "model": resp.model})

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
