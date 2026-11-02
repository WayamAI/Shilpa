"""Content-addressed result cache for structured model calls (sqlite file in the var dir).

The key is a sha256 over provider, model, schema name and hash, the full system prompt and the user content, so
any change to the prompt text, examples, model or input is a miss. Entries expire after a TTL and the table is
bounded; the oldest entries are evicted first. Only validated replies are stored (see ``call_structured``).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def prompt_version(system_template: str) -> str:
    """Short hash identifying a system prompt template (recorded on every call)."""
    return sha(system_template)[:12]


def cache_key(provider: str, model: str | None, schema_name: str, schema: dict, system: str, user) -> str:
    parts = [provider, model or "", schema_name, sha(json.dumps(schema, sort_keys=True, default=str)), sha(system),
             user if isinstance(user, str) else json.dumps(user, sort_keys=True, default=str)]
    return sha("\x1f".join(parts))


class LLMCache:
    def __init__(self, path: Path, ttl_s: int = 7 * 24 * 3600, max_entries: int = 2000):
        self.path, self.ttl_s, self.max_entries = Path(path), ttl_s, max_entries

    def _conn(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(self.path, timeout=10)
        c.execute("CREATE TABLE IF NOT EXISTS llm_cache (key TEXT PRIMARY KEY, value TEXT NOT NULL, created REAL NOT NULL)")
        return c

    def get(self, key: str) -> dict | None:
        """The stored entry ({"data", "input_tokens", "output_tokens"}) or None (missing or expired)."""
        try:
            c = self._conn()
            try:
                row = c.execute("SELECT value, created FROM llm_cache WHERE key=?", (key,)).fetchone()
                if row is None:
                    return None
                if time.time() - row[1] > self.ttl_s:
                    c.execute("DELETE FROM llm_cache WHERE key=?", (key,))
                    c.commit()
                    return None
                return json.loads(row[0])
            finally:
                c.close()
        except (sqlite3.Error, OSError, ValueError):
            return None  # a broken cache must never break a request

    def put(self, key: str, entry: dict) -> None:
        try:
            c = self._conn()
            try:
                c.execute("INSERT OR REPLACE INTO llm_cache (key, value, created) VALUES (?,?,?)",
                          (key, json.dumps(entry, default=str), time.time()))
                c.execute("DELETE FROM llm_cache WHERE created < ?", (time.time() - self.ttl_s,))
                c.execute("DELETE FROM llm_cache WHERE key IN "
                          "(SELECT key FROM llm_cache ORDER BY created DESC LIMIT -1 OFFSET ?)", (self.max_entries,))
                c.commit()
            finally:
                c.close()
        except (sqlite3.Error, OSError):
            pass

    def count(self) -> int:
        try:
            c = self._conn()
            try:
                return c.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0]
            finally:
                c.close()
        except (sqlite3.Error, OSError):
            return 0
