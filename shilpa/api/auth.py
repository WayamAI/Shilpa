"""Identity and tenant resolution (blueprint section 17).

Local mode uses dev bearer tokens of the form ``dev:<email>`` for seeded users.
Entra ID JWT validation (issuer, audience, signature, expiry) replaces this in
Azure; the rest of the API only ever sees the resulting Principal. Tenant comes
from verified membership, never from a request field.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, HTTPException
from sqlalchemy import select

from ..db import Membership, Tenant, User, tx
from ..settings import settings

WRITE_ROLES = {"org_admin", "project_editor"}


@dataclass(frozen=True)
class Principal:
    user_id: str
    email: str
    name: str
    tenant_id: str
    tenant_name: str
    role: str

    @property
    def can_write(self) -> bool:
        return self.role in WRITE_ROLES


DEV_SEED = [
    # tenant, email, name, role
    ("Wayam (dev)", "dev@wayam.local", "Dev Engineer", "org_admin"),
    ("Wayam (dev)", "viewer@wayam.local", "Read-only Viewer", "project_viewer"),
    ("Other Org (isolation tests)", "other@example.com", "Other Tenant User", "org_admin"),
]


def seed_dev_identities() -> None:
    with tx() as s:
        tenants = {t.name: t for t in s.scalars(select(Tenant)).all()}
        for tname, email, name, role in DEV_SEED:
            t = tenants.get(tname)
            if t is None:
                t = Tenant(name=tname)
                s.add(t)
                s.flush()
                tenants[tname] = t
            u = s.scalars(select(User).where(User.email == email)).first()
            if u is None:
                u = User(email=email, name=name)
                s.add(u)
                s.flush()
            if not s.scalars(select(Membership).where(Membership.user_id == u.id, Membership.tenant_id == t.id)).first():
                s.add(Membership(tenant_id=t.id, user_id=u.id, role=role))


def principal(authorization: str | None = Header(default=None)) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, detail={"code": "unauthenticated", "message": "missing bearer token"})
    token = authorization.split(" ", 1)[1].strip()
    if settings.auth_mode != "dev":
        raise HTTPException(401, detail={"code": "unauthenticated", "message": "Entra validation not configured"})
    if not token.startswith("dev:"):
        raise HTTPException(401, detail={"code": "unauthenticated", "message": "invalid token"})
    email = token[4:]
    with tx() as s:
        row = s.execute(
            select(User, Membership, Tenant)
            .join(Membership, Membership.user_id == User.id)
            .join(Tenant, Tenant.id == Membership.tenant_id)
            .where(User.email == email)
        ).first()
        if row is None:
            raise HTTPException(401, detail={"code": "unauthenticated", "message": "unknown user"})
        u, m, t = row
        return Principal(u.id, u.email, u.name, t.id, t.name, m.role)


def require_write(p: Principal) -> None:
    if not p.can_write:
        raise HTTPException(403, detail={"code": "forbidden", "message": "your role cannot modify this project"})
