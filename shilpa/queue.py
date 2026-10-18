"""Work dispatch with Service Bus semantics, backed by the database for local runs.

At-least-once delivery, peek-lock with renewal, delivery count and dead letters,
duplicate detection on message_id. Callers must still be idempotent: duplicate
detection does not replace database idempotency (blueprint section 10).

Messages carry IDs only, never file bytes or credentials.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from .db import OutboxEvent, QueueMessage, SessionLocal, now, tx
from .settings import settings

QUEUES = ("plan", "cad")


@dataclass
class Received:
    id: int
    queue: str
    body: dict
    lock_token: str
    delivery_count: int


def enqueue_outbox(session, queue: str, message: dict) -> None:
    """Record a message in the same transaction as the state change that caused it."""
    assert queue in QUEUES
    session.add(OutboxEvent(queue=queue, message=message))


def send(queue: str, message_id: str, body: dict) -> bool:
    """Returns False when the message_id was already sent (duplicate detection)."""
    try:
        with tx() as s:
            s.add(QueueMessage(queue=queue, message_id=message_id, body=body))
        return True
    except IntegrityError:
        return False


def publish_outbox(limit: int = 50) -> int:
    with tx() as s:
        rows = s.scalars(select(OutboxEvent).where(OutboxEvent.published.is_(False)).order_by(OutboxEvent.created_at).limit(limit)).all()
        items = [(r.id, r.queue, r.message) for r in rows]
    n = 0
    for oid, queue, msg in items:
        send(queue, oid, msg)  # duplicate-safe if we crash between send and mark
        with tx() as s:
            s.execute(update(OutboxEvent).where(OutboxEvent.id == oid).values(published=True))
        n += 1
    return n


def receive(queue: str) -> Received | None:
    """Peek-lock one message. Expired locks become visible again."""
    t = now()
    s = SessionLocal()
    try:
        cand = s.scalars(
            select(QueueMessage)
            .where(QueueMessage.queue == queue)
            .where(or_(QueueMessage.state == "ready", (QueueMessage.state == "locked") & (QueueMessage.locked_until < t)))
            .order_by(QueueMessage.id)
            .limit(5)
        ).all()
        for m in cand:
            if m.delivery_count >= settings.max_delivery_count:
                s.execute(update(QueueMessage).where(QueueMessage.id == m.id).values(state="dead", dead_reason="max delivery count exceeded"))
                s.commit()
                continue
            token = str(uuid.uuid4())
            # Compare-and-swap on the previous lock token so only one receiver wins.
            res = s.execute(
                update(QueueMessage)
                .where(QueueMessage.id == m.id)
                .where(QueueMessage.lock_token.is_(m.lock_token) if m.lock_token is None else QueueMessage.lock_token == m.lock_token)
                .where(QueueMessage.state.in_(("ready", "locked")))
                .values(state="locked", lock_token=token, locked_until=t + timedelta(seconds=settings.lock_duration_s),
                        delivery_count=QueueMessage.delivery_count + 1)
            )
            s.commit()
            if res.rowcount == 1:
                return Received(m.id, queue, m.body, token, m.delivery_count + 1)
        return None
    finally:
        s.close()


def _by_lock(r: Received, **values) -> bool:
    with tx() as s:
        res = s.execute(update(QueueMessage).where(QueueMessage.id == r.id).where(QueueMessage.lock_token == r.lock_token).values(**values))
        return res.rowcount == 1


def renew(r: Received) -> bool:
    return _by_lock(r, locked_until=now() + timedelta(seconds=settings.lock_duration_s))


def complete(r: Received) -> bool:
    return _by_lock(r, state="done", lock_token=None)


def abandon(r: Received) -> bool:
    return _by_lock(r, state="ready", lock_token=None, locked_until=None)


def dead_letter(r: Received, reason: str) -> bool:
    return _by_lock(r, state="dead", dead_reason=reason[:2000])
