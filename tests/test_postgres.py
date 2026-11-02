"""PostgreSQL path. Runs only when TEST_DATABASE_URL points at a disposable PostgreSQL database, e.g.

    TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55432/postgres uv run pytest tests/test_postgres.py

Every test works in its own schema (dropped afterwards), so the database itself is not modified.
"""

import os
import threading
import uuid

import pytest
from sqlalchemy import select, text

URL = os.getenv("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL is not set (PostgreSQL tests are opt-in)")


@pytest.fixture()
def pg(monkeypatch):
    from shilpa import db

    base = db.make_engine(URL)
    schema = f"t_{uuid.uuid4().hex[:10]}"
    with base.begin() as c:
        c.execute(text(f'CREATE SCHEMA "{schema}"'))
    eng = db.make_engine(f"{URL}{'&' if '?' in URL else '?'}options=-csearch_path%3D{schema}")  # every connection uses the schema
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db.SessionLocal, "kw", {**db.SessionLocal.kw, "bind": eng})
    db.Base.metadata.create_all(eng)
    yield db
    eng.dispose()
    with base.begin() as c:
        c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    base.dispose()


def test_schema_and_json_roundtrip(pg):
    with pg.tx() as s:
        t = pg.Tenant(name="acme")
        s.add(t)
        s.flush()
        s.add(pg.OutboxEvent(queue="cad", message={"a": [1, 2]}))
    with pg.tx() as s:
        assert s.scalars(select(pg.OutboxEvent)).one().message == {"a": [1, 2]}
        assert s.scalars(select(pg.Tenant)).one().created_at.tzinfo is not None


def test_queue_peek_lock_is_exclusive_under_concurrency(pg):
    from shilpa import queue

    ids = [uuid.uuid4().hex for _ in range(60)]
    for i in ids:
        assert queue.send("cad", i, {"id": i})
    assert queue.send("cad", ids[0], {"id": ids[0]}) is False  # unique (queue, message_id)
    got, lock = [], threading.Lock()

    def worker():
        while (r := queue.receive("cad")):
            with lock:
                got.append(r.body["id"])
            queue.complete(r)

    ts = [threading.Thread(target=worker) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(got) == sorted(ids)  # every message exactly once


def test_outbox_dispatchers_take_disjoint_rows(pg):
    from shilpa import queue

    with pg.tx() as s:
        for i in range(40):
            queue.enqueue_outbox(s, "plan", {"i": i})
    counts = []

    def run():
        counts.append(queue.publish_outbox(limit=10))

    for _ in range(3):  # rounds of concurrent dispatchers
        ts = [threading.Thread(target=run) for _ in range(4)]
        [t.start() for t in ts]
        [t.join() for t in ts]
    assert sum(counts) == 40
    n = 0
    while (r := queue.receive("plan")):
        n += 1
        queue.complete(r)
    assert n == 40


def test_init_db_is_idempotent_with_advisory_lock(pg):
    pg.init_db()
    pg.init_db()
