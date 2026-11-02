"""Structured logging with redaction (hosting plan section 1, blueprint section 17).

Outside ``SHILPA_ENV=local`` every record is one JSON line. Secrets never reach a handler: bearer and JWT-shaped
strings, SAS and key query parameters, and credential key=value pairs are masked in messages, and fields that
hold prompts, recipes or tokens are replaced by their size. Log ids and sizes, not bodies.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone

_BODY_KEYS = {"prompt", "recipe", "system", "user_content", "messages", "body", "content", "input", "output", "data"}
SENSITIVE_KEYS = _BODY_KEYS | {
    "authorization", "proxy-authorization", "cookie", "set-cookie", "token", "access_token", "id_token",
    "refresh_token", "password", "secret", "api_key", "apikey", "client_secret", "connection_string",
    "sas", "sig", "signature"}

_PATTERNS = [
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+"), r"\1 [REDACTED]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*"), "[REDACTED_JWT]"),
    (re.compile(r"(?i)\b(SharedAccessSignature|AccountKey|SharedAccessKey|InstrumentationKey)=[^;\s&\"']+"),
     r"\1=[REDACTED]"),
    (re.compile(r"(?i)([?&;\s\"'])(sig|sv|se|sp|spr|srt|ss|st|sr|skoid|sktid|access_token|id_token|refresh_token|token|"
                r"api[-_]?key|client_secret|password|secret|code)=[^&\s\"';]+"), r"\1\2=[REDACTED]"),
    (re.compile(r"(?i)\b(authorization|api-key|x-api-key|cookie)\s*[:=]\s*[^\s,;\"'}]+(\s+[^\s,;\"'}]+)?"),
     r"\1: [REDACTED]"),
]


def redact_text(text: str) -> str:
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    return text


def redact(value, key: str | None = None):
    """Redact a log field: body keys collapse to ``<redacted:N>`` (size), other secrets to a marker,
    and every string is pattern-masked."""
    k = (key or "").lower()
    if k in SENSITIVE_KEYS:
        if k in _BODY_KEYS:
            try:
                n = len(value) if hasattr(value, "__len__") else len(json.dumps(value, default=str))
            except Exception:
                n = 0
            return f"<redacted:{n}>"
        return "[REDACTED]"
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {str(a): redact(b, str(a)) for a, b in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(x) for x in value]
    return value


_STD = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime", "taskName"}


class RedactingFilter(logging.Filter):
    """Mutates the record in place, so it protects every handler it is attached to (including exporters)."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact_text(record.getMessage())
            record.args = ()
        except Exception:
            record.msg, record.args = "[unformattable log message]", ()
        for k in [k for k in record.__dict__ if k not in _STD]:
            record.__dict__[k] = redact(record.__dict__[k], k)
        if record.exc_info and record.exc_info[1] is not None:
            record.exc_text = redact_text(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = redact_text(record.exc_text)
        return True


class JsonFormatter(logging.Formatter):
    def __init__(self, env: str = ""):
        super().__init__()
        self.env = env

    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
               "level": record.levelname, "logger": record.name, "message": record.getMessage(), "env": self.env}
        for k, v in record.__dict__.items():
            if k not in _STD:
                out[k] = v
        if record.exc_text:
            out["exception"] = record.exc_text
        return json.dumps(out, default=str)


def attach_redaction() -> None:
    """Put the redacting filter on every root handler (call again after an exporter adds its own)."""
    for h in logging.getLogger().handlers:
        if not any(isinstance(f, RedactingFilter) for f in h.filters):
            h.addFilter(RedactingFilter())


def configure_logging(env: str, level: str = "INFO", stream=None) -> None:
    """JSON + redaction when ``env`` is not local; local keeps the developer's plain logging untouched."""
    if env == "local":
        return
    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, "_shilpa", False):
            root.removeHandler(h)
    h = logging.StreamHandler(stream or sys.stdout)
    h._shilpa = True  # type: ignore[attr-defined]
    h.setFormatter(JsonFormatter(env))
    root.addHandler(h)
    root.setLevel(level)
    attach_redaction()
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
