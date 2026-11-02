"""Entra ID access-token validation and mapping to Shilpa identities (blueprint section 17).

Validated: RS256 signature against the tenant's JWKS, issuer (the configured tenant, v1 or v2 format), audience
(the API's app id URI and/or client id), exp and nbf with a small leeway, the tenant claim, and a required scope
(``scp``) or app role (``roles``). The result is mapped onto the existing Tenant, User and Membership rows.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import jwt
from fastapi import HTTPException
from sqlalchemy import select

from .. import settings as cfg
from ..db import Membership, Tenant, User, tx


def _deny(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message})


class JWKSCache:
    """Signing keys by ``kid``. Cached for ``ttl_s``; an unknown kid triggers one refresh (rate limited, so a
    flood of forged kids cannot turn into a flood of requests to the identity provider)."""

    def __init__(self, fetch: Callable[[], dict], ttl_s: int = 3600, min_refresh_s: int = 30):
        self._fetch, self.ttl_s, self.min_refresh_s = fetch, ttl_s, min_refresh_s
        self._keys: dict[str, jwt.PyJWK] = {}
        self._loaded = 0.0
        self._attempted = 0.0
        self._lock = threading.Lock()

    def _refresh(self) -> None:
        self._attempted = time.monotonic()
        doc = self._fetch()
        keys = {}
        for k in doc.get("keys", []):
            if k.get("kty") == "RSA" and k.get("kid") and k.get("use", "sig") == "sig":
                keys[k["kid"]] = jwt.PyJWK.from_dict(k)
        if not keys:
            raise ValueError("JWKS document holds no RSA signing keys")
        self._keys, self._loaded = keys, time.monotonic()

    def key(self, kid: str):
        with self._lock:
            now = time.monotonic()
            if not self._keys or now - self._loaded > self.ttl_s:
                if now - self._attempted >= 1 or not self._keys:
                    self._refresh()
            if kid not in self._keys and time.monotonic() - self._attempted >= self.min_refresh_s:
                self._refresh()
            if kid not in self._keys:
                raise KeyError(kid)
            return self._keys[kid].key


def _http_fetch() -> dict:
    import httpx

    r = httpx.get(cfg.hosting.entra_jwks_uri, timeout=10)
    r.raise_for_status()
    return r.json()


_jwks: JWKSCache | None = None
_jwks_override: JWKSCache | None = None  # tests install a fake


def jwks() -> JWKSCache:
    global _jwks
    if _jwks_override is not None:
        return _jwks_override
    if _jwks is None:
        _jwks = JWKSCache(_http_fetch, cfg.hosting.entra_jwks_ttl_s)
    return _jwks


def validate_token(token: str) -> dict:
    """The verified claims, or HTTPException 401 (bad token) / 403 (valid token, not allowed in)."""
    h = cfg.hosting
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256" or not header.get("kid"):
            raise _deny(401, "unauthenticated", "invalid token")
        key = jwks().key(header["kid"])
        claims = jwt.decode(
            token, key, algorithms=["RS256"], audience=list(h.entra_audiences), issuer=list(h.entra_issuers),
            leeway=h.entra_leeway_s, options={"require": ["exp", "iss", "aud"], "verify_nbf": True},
        )
    except HTTPException:
        raise
    except KeyError:
        raise _deny(401, "unauthenticated", "unknown signing key") from None
    except jwt.ExpiredSignatureError:
        raise _deny(401, "unauthenticated", "token expired") from None
    except jwt.InvalidTokenError:
        raise _deny(401, "unauthenticated", "invalid token") from None
    except Exception:  # JWKS unreachable or malformed: fail closed
        raise _deny(401, "unauthenticated", "token could not be verified") from None
    if claims.get("tid") != h.entra_tenant_id:
        raise _deny(401, "unauthenticated", "token is from another tenant")
    scopes = set(str(claims.get("scp", "")).split())
    roles = set(claims.get("roles") or [])
    ok = (h.entra_required_scope and h.entra_required_scope in scopes) or (
        h.entra_required_role and h.entra_required_role in roles)
    if not ok:
        raise _deny(403, "forbidden", "token lacks the required scope or role")
    return claims


def claim_email(claims: dict) -> str | None:
    for name in ("preferred_username", "upn", "email"):
        v = claims.get(name)
        if isinstance(v, str) and "@" in v:
            return v.strip().lower()
    return None


def resolve(claims: dict):
    """Map verified claims to a Principal via email -> User -> Membership; auto-provision only when enabled."""
    from .auth import Principal

    email = claim_email(claims)
    if email is None:
        raise _deny(403, "forbidden", "token carries no user email")
    h = cfg.hosting
    with tx() as s:
        row = s.execute(
            select(User, Membership, Tenant).join(Membership, Membership.user_id == User.id)
            .join(Tenant, Tenant.id == Membership.tenant_id).where(User.email == email)
        ).first()
        if row is None:
            if not h.entra_auto_provision:
                raise _deny(403, "forbidden", "user is not provisioned")
            tname = f"entra:{claims['tid']}"
            t = s.scalars(select(Tenant).where(Tenant.name == tname)).first()
            if t is None:
                t = Tenant(name=tname)
                s.add(t)
                s.flush()
            u = s.scalars(select(User).where(User.email == email)).first()
            if u is None:
                u = User(email=email, name=str(claims.get("name") or email))
                s.add(u)
                s.flush()
            m = Membership(tenant_id=t.id, user_id=u.id, role=h.entra_default_role)
            s.add(m)
            s.flush()
            return Principal(u.id, u.email, u.name, t.id, t.name, m.role)
        u, m, t = row
        return Principal(u.id, u.email, u.name, t.id, t.name, m.role)
