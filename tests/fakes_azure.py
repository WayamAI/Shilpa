"""In-memory stand-ins for the Azure Blob and Service Bus SDK clients (logic tests; no network)."""

from __future__ import annotations

import time
import uuid
from types import SimpleNamespace

from azure.core.exceptions import ResourceNotFoundError
from azure.servicebus.exceptions import MessageLockLostError


# ---------------------------------------------------------------- blob
class FakeBlob:
    def __init__(self, c: "FakeContainer", name: str):
        self.c, self.name = c, name
        self.url = f"fake://{c.name}/{name}"

    def exists(self):
        return self.name in self.c.data

    def get_blob_properties(self):
        if not self.exists():
            raise ResourceNotFoundError("missing")
        return SimpleNamespace(size=len(self.c.data[self.name]), copy=SimpleNamespace(status="success"))

    def upload_blob(self, data, overwrite=False, content_settings=None):
        if self.exists() and not overwrite:
            raise FileExistsError(self.name)
        self.c.data[self.name] = bytes(data)
        self.c.types[self.name] = getattr(content_settings, "content_type", None)

    def download_blob(self):
        if not self.exists():
            raise ResourceNotFoundError("missing")
        data = self.c.data[self.name]

        class _D:
            def readall(self_):
                return data

            def chunks(self_):
                for i in range(0, len(data), 7):  # small chunks: exercise streaming
                    yield data[i:i + 7]

            def readinto(self_, f):
                f.write(data)
                return len(data)

        return _D()

    def start_copy_from_url(self, url):
        src = url.removeprefix(f"fake://{self.c.name}/")
        self.c.data[self.name] = self.c.data[src]
        self.c.copies += 1
        return {"copy_status": "success", "copy_id": "x"}


class FakeContainer:
    def __init__(self, name):
        self.name, self.data, self.types, self.copies = name, {}, {}, 0

    def get_blob_client(self, name):
        return FakeBlob(self, name)

    def get_container_properties(self):
        return SimpleNamespace(name=self.name)

    def list_blobs(self, name_starts_with=""):
        for n in sorted(self.data):
            if n.startswith(name_starts_with):
                yield SimpleNamespace(name=n)

    def delete_blob(self, name):
        del self.data[name]


class FakeBlobService:
    def __init__(self):
        self.containers: dict[str, FakeContainer] = {}

    def get_container_client(self, name):
        return self.containers.setdefault(name, FakeContainer(name))


# ---------------------------------------------------------------- service bus
class FakeBroker:
    """Queues with peek-lock, delivery counts, duplicate detection by message_id and dead letters."""

    def __init__(self, lock_s: float = 30.0):
        self.queues: dict[str, list[dict]] = {}
        self.dead: dict[str, list[dict]] = {}
        self.seen: dict[str, set] = {}
        self.lock_s = lock_s
        self.sent = 0

    def client(self):
        return FakeSBClient(self)


class FakeMsg:
    def __init__(self, rec):
        self.rec = rec
        self.body = iter([rec["body"]])
        self.message_id = rec["message_id"]
        self.delivery_count = rec["deliveries"]
        self.lock_token = uuid.uuid4()
        rec["token"] = self.lock_token


class FakeReceiver:
    def __init__(self, b: FakeBroker, q: str):
        self.b, self.q = b, q
        self.closed = False

    def receive_messages(self, max_message_count=1, max_wait_time=None):
        now = time.monotonic()
        for rec in self.b.queues.get(self.q, []):
            if rec["locked_until"] is None or rec["locked_until"] < now:
                rec["locked_until"] = now + self.b.lock_s
                m = FakeMsg(rec)
                rec["deliveries"] += 1
                return [m]
        return []

    def _owned(self, m):
        if m.rec.get("token") != m.lock_token or m.rec not in self.b.queues.get(self.q, []) or \
                (m.rec["locked_until"] or 0) < time.monotonic():
            raise MessageLockLostError(message="lock lost")

    def complete_message(self, m):
        self._owned(m)
        self.b.queues[self.q].remove(m.rec)

    def abandon_message(self, m):
        self._owned(m)
        m.rec["locked_until"] = None

    def dead_letter_message(self, m, reason=None, error_description=None):
        self._owned(m)
        self.b.queues[self.q].remove(m.rec)
        self.b.dead.setdefault(self.q, []).append({**m.rec, "reason": reason, "description": error_description})

    def renew_message_lock(self, m):
        self._owned(m)
        m.rec["locked_until"] = time.monotonic() + self.b.lock_s

    def close(self):
        self.closed = True


class FakeSender:
    def __init__(self, b: FakeBroker, q: str):
        self.b, self.q = b, q

    def send_messages(self, msg):
        self.b.sent += 1
        seen = self.b.seen.setdefault(self.q, set())
        if msg.message_id in seen:
            return  # duplicate detection: accepted and dropped
        seen.add(msg.message_id)
        body = msg.body if isinstance(msg.body, (bytes, str)) else b"".join(msg.body)
        self.b.queues.setdefault(self.q, []).append(
            {"message_id": msg.message_id, "body": body if isinstance(body, bytes) else body.encode(),
             "deliveries": 0, "locked_until": None})

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeSBClient:
    def __init__(self, b: FakeBroker):
        self.b = b

    def get_queue_receiver(self, name, **kw):
        return FakeReceiver(self.b, name)

    def get_queue_sender(self, name):
        return FakeSender(self.b, name)

    def close(self):
        pass
