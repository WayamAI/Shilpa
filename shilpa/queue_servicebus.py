"""Azure Service Bus backend for ``shilpa.queue`` (SHILPA_QUEUE_BACKEND=servicebus).

Same semantics as the database queue: at-least-once, peek-lock with renewal, delivery count, dead letters,
duplicate detection on message_id. The queue entities (``plan`` and ``cad``, optionally prefixed) must exist
with duplicate detection enabled, a lock duration matching SHILPA_LOCK_DURATION_S and MaxDeliveryCount set
(infrastructure, not created here). Authentication is DefaultAzureCredential (managed identity); a
connection string is accepted only for the local emulator.

A message lock belongs to the receiver link that received it, so receivers are long-lived, one per queue,
and every settlement goes through that receiver.
"""

from __future__ import annotations

import json
import logging
import threading

from .settings import cloud, settings

log = logging.getLogger("shilpa.servicebus")


class ServiceBusQueue:
    def __init__(self, client=None):
        self._client = client
        self._lock = threading.RLock()
        self._receivers: dict[str, object] = {}
        self._senders: dict[str, object] = {}

    # -- plumbing ---------------------------------------------------------------------------------
    def _name(self, queue: str) -> str:
        return f"{cloud.servicebus_queue_prefix}{queue}"

    def client(self):
        with self._lock:
            if self._client is None:
                from azure.servicebus import ServiceBusClient

                if cloud.servicebus_connection_string:
                    self._client = ServiceBusClient.from_connection_string(cloud.servicebus_connection_string)
                else:
                    if not cloud.servicebus_namespace:
                        raise RuntimeError("SHILPA_SERVICEBUS_NAMESPACE is required when SHILPA_QUEUE_BACKEND=servicebus")
                    from azure.identity import DefaultAzureCredential

                    self._client = ServiceBusClient(cloud.servicebus_namespace, DefaultAzureCredential())
            return self._client

    def _receiver(self, queue: str):
        with self._lock:
            r = self._receivers.get(queue)
            if r is None:
                from azure.servicebus import ServiceBusReceiveMode

                r = self.client().get_queue_receiver(self._name(queue), receive_mode=ServiceBusReceiveMode.PEEK_LOCK,
                                                     max_wait_time=cloud.servicebus_wait_s)
                self._receivers[queue] = r
            return r

    def _sender(self, queue: str):
        with self._lock:
            sn = self._senders.get(queue)
            if sn is None:
                sn = self.client().get_queue_sender(self._name(queue))
                self._senders[queue] = sn
            return sn

    def _drop(self, queue: str) -> None:
        with self._lock:
            for table in (self._receivers, self._senders):
                obj = table.pop(queue, None)
                if obj is not None:
                    try:
                        obj.close()
                    except Exception:  # noqa: BLE001 - a broken link is being discarded anyway
                        pass

    def close(self) -> None:
        for q in list(self._receivers) + list(self._senders):
            self._drop(q)
        if self._client is not None:
            self._client.close()
            self._client = None

    def ping(self) -> None:
        """Open (and close) a sender link on each queue: proves reachability, the queue names and Send rights."""
        for q in ("plan", "cad"):
            with self.client().get_queue_sender(self._name(q)):
                pass

    # -- queue interface ----------------------------------------------------------------------------
    def send(self, queue: str, message_id: str, body: dict) -> bool:
        """The broker drops a repeated message_id inside its duplicate-detection window; that is not an error here."""
        from azure.servicebus import ServiceBusMessage

        msg = ServiceBusMessage(json.dumps(body), message_id=message_id, content_type="application/json")
        try:
            self._sender(queue).send_messages(msg)
        except Exception:
            self._drop(queue)  # reconnect on the next call
            raise
        return True

    def receive(self, queue: str):
        from .queue import Received

        try:
            with self._lock:
                msgs = self._receiver(queue).receive_messages(max_message_count=1, max_wait_time=cloud.servicebus_wait_s)
        except Exception:
            log.exception("service bus receive failed; reconnecting")
            self._drop(queue)
            return None
        if not msgs:
            return None
        m = msgs[0]
        delivery = int(getattr(m, "delivery_count", 0) or 0) + 1  # SDK reports prior deliveries
        try:
            body = json.loads(b"".join(m.body).decode("utf-8"))
        except Exception:  # noqa: BLE001 - poison payload: never redeliver it
            self._settle(queue, "dead_letter_message", m, reason="undecodable body")
            return None
        if delivery > settings.max_delivery_count:
            self._settle(queue, "dead_letter_message", m, reason="max delivery count exceeded")
            return None
        return Received(0, queue, body, str(getattr(m, "lock_token", "")), delivery, handle=m)

    def _settle(self, queue: str, op: str, msg, **kw) -> bool:
        from azure.servicebus.exceptions import MessageLockLostError, ServiceBusError

        try:
            with self._lock:
                getattr(self._receiver(queue), op)(msg, **kw)
            return True
        except MessageLockLostError:
            return False  # the lock expired and the message may be redelivered elsewhere
        except ServiceBusError:
            log.warning("service bus %s failed", op, exc_info=True)
            return False

    def renew(self, r) -> bool:
        from azure.servicebus.exceptions import ServiceBusError

        try:
            with self._lock:
                self._receiver(r.queue).renew_message_lock(r.handle)
            return True
        except ServiceBusError:
            return False

    def complete(self, r) -> bool:
        return self._settle(r.queue, "complete_message", r.handle)

    def abandon(self, r) -> bool:
        return self._settle(r.queue, "abandon_message", r.handle)

    def dead_letter(self, r, reason: str) -> bool:
        return self._settle(r.queue, "dead_letter_message", r.handle, reason="dead-lettered", error_description=reason[:2000])


_instance: ServiceBusQueue | None = None
_guard = threading.Lock()


def get() -> ServiceBusQueue:
    global _instance
    with _guard:
        if _instance is None:
            _instance = ServiceBusQueue()
        return _instance


def use(q: ServiceBusQueue | None) -> None:
    """Install (tests) or clear the process-wide instance."""
    global _instance
    _instance = q
