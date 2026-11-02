"""Liveness and readiness probes (hosting plan section 5).

Liveness never touches a dependency. Readiness checks the database, the queue backend and blob storage through
the module-level interfaces. A backend may expose ``ping()`` (queue module / blob store); without it a cheap
fallback is used. The planner status is reported but never required.
"""

from __future__ import annotations

from typing import Callable

from sqlalchemy import func, select, text


def _db() -> None:
    from .db import engine

    with engine.connect() as c:
        c.execute(text("SELECT 1"))


def _queue() -> None:
    from . import queue

    ping = getattr(queue, "ping", None)
    if callable(ping):
        ping()
        return
    from .db import QueueMessage, tx  # database-backed queue: its table must be readable

    with tx() as s:
        s.scalar(select(func.count()).select_from(QueueMessage).where(QueueMessage.state == "locked"))


def _storage() -> None:
    from . import storage

    ping = getattr(storage.blobs, "ping", None)
    if callable(ping):
        ping()
        return
    storage.blobs.exists("health/readiness-probe")


CHECKS: dict[str, Callable[[], None]] = {"database": _db, "queue": _queue, "storage": _storage}


def readiness() -> tuple[bool, dict]:
    from .settings import settings

    results: dict[str, dict] = {}
    for name, fn in CHECKS.items():
        try:
            fn()
            results[name] = {"ok": True}
        except Exception as e:  # report the class only: messages can carry connection strings
            results[name] = {"ok": False, "error": type(e).__name__}
    return all(r["ok"] for r in results.values()), {"checks": results, "planner": settings.planner_status}
