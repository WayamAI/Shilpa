"""Content-addressed result cache for structured model calls (a table in the application database).

The key is a sha256 over provider, model, schema name and hash, the full system prompt and the user content, so
any change to the prompt text, examples, model or input is a miss. Entries expire after a TTL and the table is
bounded; the oldest entries are evicted first. Only validated replies are stored (see ``call_structured``).
"""

from __future__ import annotations

import hashlib
import json
import time

from sqlalchemy import Float, String, Text, delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, SessionLocal, engine


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def prompt_version(system_template: str) -> str:
    """Short hash identifying a system prompt template (recorded on every call)."""
    return sha(system_template)[:12]


def cache_key(provider: str, model: str | None, schema_name: str, schema: dict, system: str, user) -> str:
    parts = [provider, model or "", schema_name, sha(json.dumps(schema, sort_keys=True, default=str)), sha(system),
             user if isinstance(user, str) else json.dumps(user, sort_keys=True, default=str)]
    return sha("\x1f".join(parts))


class LLMCacheEntry(Base):
    """One cached reply. Disposable: created on demand, never migrated, safe to truncate at any time."""

    __tablename__ = "llm_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    created: Mapped[float] = mapped_column(Float, index=True)


_ready = False


def _ensure_table() -> None:
    global _ready
    if not _ready:
        LLMCacheEntry.__table__.create(engine, checkfirst=True)
        _ready = True


class LLMCache:
    """Same semantics as the former sqlite file: TTL on read, oldest-first eviction beyond ``max_entries``.
    Works on SQLite and PostgreSQL, and is shared by every replica. Any database error is a miss."""

    def __init__(self, ttl_s: int = 7 * 24 * 3600, max_entries: int = 2000):
        self.ttl_s, self.max_entries = ttl_s, max_entries

    def get(self, key: str) -> dict | None:
        """The stored entry ({"data", "input_tokens", "output_tokens"}) or None (missing or expired)."""
        try:
            _ensure_table()
            with SessionLocal() as s:
                row = s.get(LLMCacheEntry, key)
                if row is None:
                    return None
                if time.time() - row.created > self.ttl_s:
                    s.delete(row)
                    s.commit()
                    return None
                return json.loads(row.value)
        except (SQLAlchemyError, OSError, ValueError):
            return None  # a broken cache must never break a request

    def put(self, key: str, entry: dict) -> None:
        try:
            _ensure_table()
            now = time.time()
            with SessionLocal() as s:
                s.merge(LLMCacheEntry(key=key, value=json.dumps(entry, default=str), created=now))
                s.execute(delete(LLMCacheEntry).where(LLMCacheEntry.created < now - self.ttl_s))
                s.flush()
                if s.scalar(select(func.count()).select_from(LLMCacheEntry)) > self.max_entries:
                    keep = select(LLMCacheEntry.key).order_by(LLMCacheEntry.created.desc()).limit(self.max_entries)
                    s.execute(delete(LLMCacheEntry).where(LLMCacheEntry.key.not_in(keep.scalar_subquery())))
                s.commit()
        except (SQLAlchemyError, OSError):
            pass

    def count(self) -> int:
        try:
            _ensure_table()
            with SessionLocal() as s:
                return s.scalar(select(func.count()).select_from(LLMCacheEntry)) or 0
        except (SQLAlchemyError, OSError):
            return 0

    def clear(self) -> None:
        try:
            _ensure_table()
            with SessionLocal() as s:
                s.execute(delete(LLMCacheEntry))
                s.commit()
        except (SQLAlchemyError, OSError):
            pass
