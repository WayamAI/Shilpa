"""Cloud adapters: blob stores, queue backends and database engine construction.

Local backends always run. Azure backends run against in-memory fakes of the SDK clients (logic), and against
Azurite / the Service Bus emulator when they are reachable (SHILPA_TEST_AZURITE_CONNECTION_STRING, or Azurite on its
default port; SHILPA_TEST_SERVICEBUS_CONNECTION_STRING). PostgreSQL tests live in test_postgres.py.
"""

import dataclasses
import os
import socket
import threading
import uuid

import pytest
from sqlalchemy import select, update

from shilpa import db, queue, queue_servicebus, storage
from shilpa.settings import cloud as real_cloud

from .fakes_azure import FakeBlobService, FakeBroker

AZURITE_CS = os.getenv("SHILPA_TEST_AZURITE_CONNECTION_STRING", "")
SB_CS = os.getenv("SHILPA_TEST_SERVICEBUS_CONNECTION_STRING", "")
# The published, public Azurite development account key (not a secret).
AZURITE_DEFAULT = ("DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;"
                   "BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;")


def _azurite_up() -> bool:
    if AZURITE_CS:
        return True
    try:
        socket.create_connection(("127.0.0.1", 10000), timeout=0.3).close()
        return True
    except OSError:
        return False


@pytest.fixture(scope="module", autouse=True)
def _schema():
    db.init_db()


# ---------------------------------------------------------------- blob stores
@pytest.fixture(params=["local", "azure-fake", "azurite"])
def store(request, tmp_path):
    if request.param == "local":
        yield storage.LocalBlobStore(tmp_path / "blobs")
    elif request.param == "azure-fake":
        yield storage.AzureBlobStore(container="c", service=FakeBlobService(), workdir=str(tmp_path))
    else:
        if not _azurite_up():
            pytest.skip("Azurite is not running on 127.0.0.1:10000 and SHILPA_TEST_AZURITE_CONNECTION_STRING is unset")
        s = storage.AzureBlobStore(container=f"t{uuid.uuid4().hex[:12]}", connection_string=AZURITE_CS or AZURITE_DEFAULT,
                                   workdir=str(tmp_path))
        yield s
        s.container.delete_container()


def test_roundtrip_copy_size_delete(store):
    a = "tenants/t/projects/p/jobs/j/attempts/1/a.json"
    store.write_bytes(a, b'{"x":1}')
    assert store.exists(a)
    assert not store.exists("tenants/t/projects/p/jobs/j/attempts/1/nope")
    store.copy(a, "tenants/t/projects/p/versions/v/a.json")
    assert store.read_bytes("tenants/t/projects/p/versions/v/a.json") == b'{"x":1}'
    assert store.size("tenants/t/projects/p/versions/v/a.json") == 7
    assert b"".join(store.stream("tenants/t/projects/p/versions/v/a.json")) == b'{"x":1}'
    store.delete_prefix("tenants/t/projects/p/jobs")
    assert not store.exists(a)
    assert store.exists("tenants/t/projects/p/versions/v/a.json")


def test_unsafe_keys_rejected(store):
    for bad in ("../x", "/abs", "a/../b"):
        with pytest.raises(ValueError):
            store.exists(bad)


def test_workdir_push_view(store):
    prefix = store.staging_prefix("t", "p", "job", 1)
    with store.workdir(prefix) as d:
        (d / "model.step").write_bytes(b"STEP")
        (d / "sub").mkdir()
        (d / "sub" / "n.txt").write_bytes(b"n")
        store.push_dir(d, prefix)
    assert store.read_bytes(f"{prefix}/model.step") == b"STEP"
    assert store.read_bytes(f"{prefix}/sub/n.txt") == b"n"
    with store.view(prefix) as v:
        assert (v / "model.step").read_bytes() == b"STEP"
        assert (v / "sub" / "n.txt").read_bytes() == b"n"
    local = store.local_path(f"{prefix}/model.step")
    assert (local is None) == isinstance(store, storage.AzureBlobStore)


def test_azure_workdir_is_scratch_and_cleaned(tmp_path):
    s = storage.AzureBlobStore(container="c", service=FakeBlobService(), workdir=str(tmp_path))
    with s.workdir("a/b") as d:
        (d / "f").write_bytes(b"1")
        assert d.exists()
        assert not s.exists("a/b/f")  # nothing is in the store until push_dir
    assert not d.exists()


def test_azure_copy_falls_back_when_not_synchronous(tmp_path):
    s = storage.AzureBlobStore(container="c", service=FakeBlobService(), workdir=str(tmp_path))
    s.write_bytes("a/x", b"hello")
    blob_cls = type(s._blob("a/x"))
    orig = blob_cls.start_copy_from_url
    blob_cls.start_copy_from_url = lambda self, url: {"copy_status": "failed", "copy_id": "x"}
    try:
        s.copy("a/x", "b/x")
    finally:
        blob_cls.start_copy_from_url = orig
    assert s.read_bytes("b/x") == b"hello"


def test_azure_content_type_and_requires_account_url():
    svc = FakeBlobService()
    s = storage.AzureBlobStore(container="c", service=svc)
    s.write_bytes("v/x.json", b"{}")
    assert svc.containers["c"].types["v/x.json"] == "application/json"
    with pytest.raises(RuntimeError, match="SHILPA_BLOB_ACCOUNT_URL"):
        _ = storage.AzureBlobStore(container="c").container


def test_make_store_selection(monkeypatch):
    monkeypatch.setattr(storage, "cloud", dataclasses.replace(real_cloud, blob_backend="azure", blob_account_url="https://a.blob.core.windows.net"))
    assert isinstance(storage.make_store(), storage.AzureBlobStore)
    monkeypatch.setattr(storage, "cloud", dataclasses.replace(real_cloud, blob_backend="nope"))
    with pytest.raises(RuntimeError):
        storage.make_store()
    assert isinstance(storage.blobs, storage.LocalBlobStore)  # the default for the whole suite


# ---------------------------------------------------------------- queue backends
@pytest.fixture(params=["db", "servicebus-fake", "servicebus-emulator"])
def backend(request, monkeypatch):
    if request.param == "db":
        yield "db"
        return
    if request.param == "servicebus-fake":
        broker = FakeBroker()
        c = dataclasses.replace(real_cloud, queue_backend="servicebus")
        monkeypatch.setattr(queue, "cloud", c)
        monkeypatch.setattr(queue_servicebus, "cloud", c)
        queue_servicebus.use(queue_servicebus.ServiceBusQueue(client=broker.client()))
        yield broker
        queue_servicebus.use(None)
        return
    if not SB_CS:
        pytest.skip("Service Bus emulator not configured: set SHILPA_TEST_SERVICEBUS_CONNECTION_STRING "
                    "(queues 'plan' and 'cad' with duplicate detection)")
    c = dataclasses.replace(real_cloud, queue_backend="servicebus", servicebus_connection_string=SB_CS, servicebus_queue_prefix="")
    monkeypatch.setattr(queue, "cloud", c)
    monkeypatch.setattr(queue_servicebus, "cloud", c)
    queue_servicebus.use(None)
    yield "emulator"
    queue_servicebus.get().close()
    queue_servicebus.use(None)


def _drain(q):
    while (r := queue.receive(q)):
        queue.complete(r)


def test_send_receive_complete(backend):
    _drain("cad")
    assert queue.send("cad", uuid.uuid4().hex, {"job_id": "j1", "attempt": 1}) is True
    r = queue.receive("cad")
    assert r is not None and r.body == {"job_id": "j1", "attempt": 1} and r.delivery_count == 1
    assert queue.renew(r) is True
    assert queue.complete(r) is True
    assert queue.receive("cad") is None
    assert queue.complete(r) is False  # a second settle does not succeed


def test_duplicate_message_id_is_not_delivered_twice(backend):
    _drain("cad")
    mid = uuid.uuid4().hex
    queue.send("cad", mid, {"n": 1})
    queue.send("cad", mid, {"n": 1})
    queue.complete(queue.receive("cad"))
    assert queue.receive("cad") is None


def test_abandon_redelivers_with_count_then_dead_letters(backend):
    _drain("plan")
    queue.send("plan", uuid.uuid4().hex, {"k": "v"})
    r1 = queue.receive("plan")
    assert queue.abandon(r1) is True
    r2 = queue.receive("plan")
    assert r2 is not None and r2.delivery_count == 2
    assert queue.dead_letter(r2, "poison") is True
    assert queue.receive("plan") is None
    if isinstance(backend, FakeBroker):
        assert backend.dead["plan"][0]["description"] == "poison"
    elif backend == "db":
        with db.tx() as s:
            m = s.get(db.QueueMessage, r2.id)
            assert m.state == "dead" and m.dead_reason == "poison"


def test_max_delivery_count_dead_letters(backend, monkeypatch):
    _drain("plan")
    small = dataclasses.replace(queue.settings, max_delivery_count=2)
    monkeypatch.setattr(queue, "settings", small)
    monkeypatch.setattr(queue_servicebus, "settings", small)
    queue.send("plan", uuid.uuid4().hex, {"p": 1})
    for _ in range(2):
        r = queue.receive("plan")
        assert r is not None
        queue.abandon(r)
    assert queue.receive("plan") is None  # the third delivery would exceed the limit: dead-lettered, not returned
    if isinstance(backend, FakeBroker):
        assert len(backend.dead["plan"]) == 1


def test_lost_lock_cannot_settle(backend):
    if backend == "emulator":
        pytest.skip("lock expiry needs a short lock duration on the emulator queue")
    _drain("cad")
    queue.send("cad", uuid.uuid4().hex, {"a": 1})
    r = queue.receive("cad")
    if backend == "db":
        with db.tx() as s:  # the lock expires and another receiver takes the message
            s.execute(update(db.QueueMessage).where(db.QueueMessage.id == r.id).values(locked_until=db.now().replace(year=2000)))
    else:
        backend.queues["cad"][0]["locked_until"] = 0
    r2 = queue.receive("cad")
    assert r2 is not None and r2.delivery_count == 2
    assert queue.complete(r) is False and queue.renew(r) is False
    assert queue.complete(r2) is True


def test_outbox_dispatch(backend):
    _drain("cad")
    with db.tx() as s:
        queue.enqueue_outbox(s, "cad", {"job_id": "outbox-1", "attempt": 1})
    assert queue.publish_outbox() >= 1
    with db.tx() as s:
        assert not s.scalars(select(db.OutboxEvent).where(db.OutboxEvent.published.is_(False))).all()
    got = []
    while (r := queue.receive("cad")):
        got.append(r.body)
        queue.complete(r)
    assert {"job_id": "outbox-1", "attempt": 1} in got


def test_ping_on_every_backend(backend, store):
    queue.ping()
    store.ping() if hasattr(store, "ping") else None


def test_servicebus_requires_namespace(monkeypatch):
    monkeypatch.setattr(queue_servicebus, "cloud", dataclasses.replace(real_cloud, servicebus_namespace="", servicebus_connection_string=""))
    with pytest.raises(RuntimeError, match="SHILPA_SERVICEBUS_NAMESPACE"):
        queue_servicebus.ServiceBusQueue().client()


def test_receive_failure_returns_none_and_reconnects():
    broker = FakeBroker()
    sb = queue_servicebus.ServiceBusQueue(client=broker.client())
    sb.send("cad", "m1", {"x": 1})
    sb._receiver("cad").receive_messages = lambda **kw: (_ for _ in ()).throw(RuntimeError("link detached"))
    assert sb.receive("cad") is None
    assert "cad" not in sb._receivers  # dropped; the next call opens a fresh link
    assert sb.receive("cad") is not None


def test_db_queue_concurrent_receivers_claim_each_message_once():
    _drain("cad")
    ids = [uuid.uuid4().hex for _ in range(30)]
    for i in ids:
        queue.send("cad", i, {"id": i})
    got, lock = [], threading.Lock()

    def worker():
        while (r := queue.receive("cad")):
            with lock:
                got.append(r.body["id"])
            queue.complete(r)

    ts = [threading.Thread(target=worker) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(got) == sorted(ids)


# ---------------------------------------------------------------- database engine
def test_database_url_normalised():
    assert db.normalise_database_url("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert db.normalise_database_url("postgres://u@h/db") == "postgresql+psycopg://u@h/db"
    assert db.normalise_database_url("postgresql+psycopg://u@h/db") == "postgresql+psycopg://u@h/db"
    assert db.normalise_database_url("sqlite:///x.db") == "sqlite:///x.db"


def test_postgres_engine_pool_and_no_sqlite_pragmas(monkeypatch):
    monkeypatch.setattr(db, "cloud", dataclasses.replace(real_cloud, db_pool_size=3, db_max_overflow=2, db_pool_recycle_s=900))
    eng = db.make_engine("postgresql://u:pw@localhost:5432/shilpa")  # lazy: nothing connects
    assert eng.dialect.name == "postgresql" and eng.dialect.driver == "psycopg"
    assert eng.pool.size() == 3 and eng.pool._max_overflow == 2 and eng.pool._recycle == 900
    assert eng.pool._pre_ping is True
    assert not [f for f in eng.pool.dispatch.connect if "sqlite" in getattr(f, "__name__", "")]  # no sqlite pragmas


def test_entra_token_used_as_password_per_connection(monkeypatch):
    tokens = iter(["tok-1", "tok-2"])
    monkeypatch.setattr(db, "cloud", dataclasses.replace(real_cloud, database_auth="entra"))
    monkeypatch.setattr(db, "_entra_token", lambda: next(tokens))
    eng = db.make_engine("postgresql://identity-name@h.postgres.database.azure.com/shilpa?sslmode=require")
    for expect in ("tok-1", "tok-2"):
        params = {"user": "identity-name", "password": "stale"}
        eng.dialect.dispatch.do_connect(eng.dialect, None, (), params)
        assert params["password"] == expect


def test_entra_token_scope(monkeypatch):
    calls = []

    class Cred:
        def get_token(self, scope):
            calls.append(scope)
            return type("T", (), {"token": "abc"})()

    monkeypatch.setattr(db, "_credential", Cred())
    assert db._entra_token() == "abc"
    assert calls == ["https://ossrdbms-aad.database.windows.net/.default"]


def test_sqlite_engine_keeps_pragmas():
    assert db.engine.dialect.name == "sqlite" and db.engine.pool.dispatch.connect
