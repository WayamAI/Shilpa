"""Hosting guards, Entra token validation, health probes, log redaction (hosting plan step 3). No network."""

from __future__ import annotations

import dataclasses
import io
import json
import logging
import sys
import time
import types

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import select

import shilpa.settings as cfg
from shilpa import health, logging_setup, telemetry
from shilpa.api import entra
from shilpa.api.app import app
from shilpa.db import Membership, Tenant, User, init_db, tx

TID = "11111111-1111-1111-1111-111111111111"
AUD = "api://shilpa-test"


# ------------------------------------------------------------------ 1. environment guard


def hosted(**kw):
    base = dict(env="staging", entra_tenant_id=TID, entra_audiences=(AUD,), entra_required_scope="access_as_user")
    return dataclasses.replace(cfg.HostingSettings(), **{**base, **kw})


def good_settings(**kw):
    base = dict(auth_mode="entra", llm_provider="azure", llm_mode="on", aoai_endpoint="https://x.openai.azure.com",
                aoai_deployment="gpt", database_url="postgresql+psycopg://u:p@h/db")
    return dataclasses.replace(cfg.Settings(), **{**base, **kw})


def test_local_allows_everything():
    h = dataclasses.replace(cfg.HostingSettings(), env="local")
    s = dataclasses.replace(cfg.Settings(), llm_provider="ollama", auth_mode="dev")
    assert cfg.startup_problems(h, s) == []


def test_default_env_is_local():
    assert cfg.HostingSettings().env in cfg.ENVIRONMENTS


@pytest.mark.parametrize("env", ["dev", "staging", "production"])
def test_hosted_rejects_ollama_and_dev_auth(env):
    msgs = cfg.startup_problems(hosted(env=env), good_settings(llm_provider="ollama"))
    assert any("SHILPA_LLM_PROVIDER=ollama" in m for m in msgs)
    msgs = cfg.startup_problems(hosted(env=env), good_settings(auth_mode="dev"))
    assert any("SHILPA_AUTH_MODE=dev" in m for m in msgs)


def test_hosted_good_config_passes():
    assert cfg.startup_problems(hosted(), good_settings()) == []
    cfg.enforce_startup(hosted(), good_settings())


def test_hosted_missing_settings_named():
    s = good_settings(aoai_endpoint="", aoai_deployment="", database_url="sqlite:///x.db")
    h = hosted(entra_tenant_id="", entra_audiences=(), entra_required_scope="")
    text = "\n".join(cfg.startup_problems(h, s))
    for name in ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT", "DATABASE_URL", "SHILPA_ENTRA_TENANT_ID",
                 "SHILPA_ENTRA_AUDIENCE", "SHILPA_ENTRA_REQUIRED_SCOPE"):
        assert name in text
    with pytest.raises(cfg.ConfigError, match="SHILPA_ENTRA_TENANT_ID"):
        cfg.enforce_startup(h, s)


def test_llm_off_needs_no_azure_openai_settings():
    assert cfg.startup_problems(hosted(), good_settings(llm_mode="off", aoai_endpoint="", aoai_deployment="")) == []


def test_unknown_env_rejected():
    assert "SHILPA_ENV" in cfg.startup_problems(hosted(env="prod"), good_settings())[0]


def test_app_refuses_to_start_in_forbidden_config(monkeypatch):
    monkeypatch.setattr(cfg, "hosting", hosted())
    monkeypatch.setattr(cfg, "settings", dataclasses.replace(cfg.settings, auth_mode="dev"))
    with pytest.raises(cfg.ConfigError, match="SHILPA_AUTH_MODE=dev"):
        with TestClient(app):
            pass


# ------------------------------------------------------------------ 2. Entra tokens

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk(key, kid):
    d = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    return {**d, "kid": kid, "use": "sig", "alg": "RS256"}


def mint(key=_KEY, kid="k1", **over):
    now = int(time.time())
    claims = {"iss": f"https://login.microsoftonline.com/{TID}/v2.0", "aud": AUD, "tid": TID, "oid": "oid-1",
              "preferred_username": "alice@contoso.com", "name": "Alice", "scp": "access_as_user",
              "iat": now, "nbf": now, "exp": now + 600}
    claims.update(over)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


@pytest.fixture
def entra_mode(monkeypatch):
    monkeypatch.setattr(cfg, "hosting", hosted(env="local", entra_auto_provision=False))
    monkeypatch.setattr(cfg, "settings", dataclasses.replace(cfg.settings, auth_mode="entra"))
    import shilpa.api.auth as auth

    monkeypatch.setattr(auth, "settings", cfg.settings)
    docs = {"keys": [_jwk(_KEY, "k1")]}
    calls = []

    def fetch():
        calls.append(1)
        return docs

    cache = entra.JWKSCache(fetch, ttl_s=3600, min_refresh_s=0)
    monkeypatch.setattr(entra, "_jwks_override", cache)
    cache.calls, cache.docs = calls, docs
    return cache


def bearer(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_valid_token_validates(entra_mode):
    c = entra.validate_token(mint())
    assert c["oid"] == "oid-1" and c["tid"] == TID


@pytest.mark.parametrize("over,status", [
    (dict(iss="https://login.microsoftonline.com/other/v2.0"), 401),
    (dict(aud="api://someone-else"), 401),
    (dict(exp=int(time.time()) - 3600), 401),
    (dict(nbf=int(time.time()) + 3600), 401),
    (dict(tid="22222222-2222-2222-2222-222222222222"), 401),
    (dict(exp=None), 401),
    (dict(scp="other_scope"), 403),
])
def test_bad_claims_rejected(entra_mode, over, status):
    with pytest.raises(Exception) as e:
        entra.validate_token(mint(**over))
    assert e.value.status_code == status


def test_leeway_allows_small_clock_skew(entra_mode):
    entra.validate_token(mint(exp=int(time.time()) - 20, nbf=int(time.time()) + 20))


def test_wrong_signature_and_alg_rejected(entra_mode):
    with pytest.raises(Exception) as e:
        entra.validate_token(mint(key=_OTHER))
    assert e.value.status_code == 401
    forged = jwt.encode({"aud": AUD, "iss": "x"}, "s" * 32, algorithm="HS256", headers={"kid": "k1"})
    with pytest.raises(Exception) as e:
        entra.validate_token(forged)
    assert e.value.status_code == 401
    with pytest.raises(Exception) as e:
        entra.validate_token("not.a.jwt")
    assert e.value.status_code == 401


def test_role_satisfies_requirement(entra_mode, monkeypatch):
    monkeypatch.setattr(cfg, "hosting", hosted(env="local", entra_required_scope="", entra_required_role="Shilpa.User"))
    entra.validate_token(mint(scp=None, roles=["Shilpa.User"]))
    with pytest.raises(Exception) as e:
        entra.validate_token(mint(scp="access_as_user"))
    assert e.value.status_code == 403


def test_jwks_cached_and_refreshed_on_unknown_kid(entra_mode):
    entra.validate_token(mint())
    entra.validate_token(mint())
    assert len(entra_mode.calls) == 1  # cached
    entra_mode.docs["keys"].append(_jwk(_OTHER, "k2"))  # key rotation
    entra.validate_token(mint(key=_OTHER, kid="k2"))
    assert len(entra_mode.calls) == 2
    with pytest.raises(Exception) as e:  # unknown kid stays rejected
        entra.validate_token(mint(kid="nope"))
    assert e.value.status_code == 401


def test_jwks_unreachable_fails_closed(monkeypatch):
    def boom():
        raise OSError("down")

    monkeypatch.setattr(cfg, "hosting", hosted(env="local"))
    monkeypatch.setattr(entra, "_jwks_override", entra.JWKSCache(boom))
    with pytest.raises(Exception) as e:
        entra.validate_token(mint())
    assert e.value.status_code == 401


def test_api_maps_entra_user_to_membership(entra_mode):
    init_db()
    with tx() as s:
        t = Tenant(name="Contoso")
        u = User(email="alice@contoso.com", name="Alice")
        s.add_all([t, u])
        s.flush()
        s.add(Membership(tenant_id=t.id, user_id=u.id, role="project_editor"))
    with TestClient(app) as c:
        r = c.get("/v1/me", headers=bearer(mint()))
        assert r.status_code == 200, r.text
        assert r.json()["email"] == "alice@contoso.com"
        assert c.get("/v1/me").status_code == 401
        assert c.get("/v1/me", headers=bearer(mint(exp=1))).status_code == 401
        assert c.get("/v1/me", headers=bearer("dev:alice@contoso.com")).status_code == 401  # dev tokens off


def test_unknown_user_403_unless_auto_provision(entra_mode, monkeypatch):
    tok = mint(preferred_username="newbie@contoso.com")
    with TestClient(app) as c:
        assert c.get("/v1/me", headers=bearer(tok)).status_code == 403
        monkeypatch.setattr(cfg, "hosting", hosted(env="local", entra_auto_provision=True))
        r = c.get("/v1/me", headers=bearer(tok))
        assert r.status_code == 200, r.text
        assert r.json()["email"] == "newbie@contoso.com"
        # second call reuses the same tenant and user
        assert c.get("/v1/me", headers=bearer(tok)).status_code == 200
    with tx() as s:
        assert len(s.scalars(select(User).where(User.email == "newbie@contoso.com")).all()) == 1
        assert len(s.scalars(select(Tenant).where(Tenant.name == f"entra:{TID}")).all()) == 1


def test_token_without_email_is_403(entra_mode):
    with TestClient(app) as c:
        assert c.get("/v1/me", headers=bearer(mint(preferred_username=None))).status_code == 403


# ------------------------------------------------------------------ 4. health


def test_live_needs_no_dependencies(monkeypatch):
    monkeypatch.setattr(health, "CHECKS", {"database": lambda: 1 / 0})
    with TestClient(app) as c:
        r = c.get("/v1/health/live")
        assert r.status_code == 200 and r.json() == {"ok": True}
        assert c.get("/v1/health").status_code == 200  # unchanged


def test_ready_ok_on_defaults():
    with TestClient(app) as c:
        r = c.get("/v1/health/ready")
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body["checks"]) == {"database", "queue", "storage"} and body["ok"] is True


def test_ready_503_names_failing_dependency_without_leaking_message(monkeypatch):
    def bad():
        raise RuntimeError("password=hunter2 host=secret")

    monkeypatch.setitem(health.CHECKS, "queue", bad)
    with TestClient(app) as c:
        r = c.get("/v1/health/ready")
    assert r.status_code == 503
    assert r.json()["checks"]["queue"] == {"ok": False, "error": "RuntimeError"}
    assert "hunter2" not in r.text


def test_ready_uses_backend_ping_when_present(monkeypatch):
    import shilpa.queue as q
    import shilpa.storage as st

    seen = []
    monkeypatch.setattr(q, "ping", lambda: seen.append("q"), raising=False)
    monkeypatch.setattr(st.blobs, "ping", lambda: seen.append("s"), raising=False)
    ok, _ = health.readiness()
    assert ok and seen == ["q", "s"]


# ------------------------------------------------------------------ 5. logging


def _emit(msg, *args, **extra):
    buf = io.StringIO()
    root = logging.getLogger()
    saved = root.handlers[:], root.level
    try:
        logging_setup.configure_logging("staging", "INFO", stream=buf)
        logging.getLogger("shilpa.test").info(msg, *args, extra=extra)
    finally:
        root.handlers[:] = saved[0]
        root.setLevel(saved[1])
    return buf.getvalue()


def test_local_logging_untouched():
    root = logging.getLogger()
    before = list(root.handlers)
    logging_setup.configure_logging("local")
    assert root.handlers == before


def test_json_logs_redact_secrets():
    jwt_like = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjM0In0.c2lnbmF0dXJl"
    out = _emit("calling https://acct.blob.core.windows.net/c/b?sv=2024&sig=SECRETSIG&se=2030 with Bearer %s", jwt_like,
                authorization="Bearer abc.def", prompt="make me a 20mm cube with secret details",
                recipe={"ops": [1, 2, 3]}, job_id="j-1")
    rec = json.loads(out)
    assert rec["level"] == "INFO" and rec["env"] == "staging" and rec["job_id"] == "j-1"
    for leaked in ("SECRETSIG", jwt_like, "abc.def", "secret details", "20mm cube"):
        assert leaked not in out
    assert rec["prompt"].startswith("<redacted:") and rec["recipe"].startswith("<redacted:")
    assert rec["authorization"] == "[REDACTED]"


def test_exceptions_are_redacted():
    buf = io.StringIO()
    root = logging.getLogger()
    saved = root.handlers[:], root.level
    try:
        logging_setup.configure_logging("production", "INFO", stream=buf)
        try:
            raise ValueError("failed with AccountKey=abcd1234== in connection")
        except ValueError:
            logging.getLogger("shilpa.test").exception("boom")
    finally:
        root.handlers[:] = saved[0]
        root.setLevel(saved[1])
    assert "abcd1234" not in buf.getvalue() and "AccountKey=[REDACTED]" in buf.getvalue()


def test_redact_helpers():
    assert logging_setup.redact({"x": {"token": "t", "n": 1}})["x"] == {"token": "[REDACTED]", "n": 1}
    assert "bar" not in logging_setup.redact_text("GET /v1/x?api_key=bar&a=1")


def test_telemetry_is_noop_without_connection_string():
    assert telemetry.setup_telemetry(None, connection_string="") is False


def test_telemetry_degrades_without_package(monkeypatch):
    monkeypatch.setitem(sys.modules, "azure.monitor.opentelemetry", None)  # makes the import fail
    assert telemetry.setup_telemetry(None, connection_string="InstrumentationKey=x") is False


def test_telemetry_configures_exporter_when_available(monkeypatch):
    got = {}
    mod = types.ModuleType("azure.monitor.opentelemetry")
    mod.configure_azure_monitor = lambda **kw: got.update(kw)
    monkeypatch.setitem(sys.modules, "azure.monitor.opentelemetry", mod)
    assert telemetry.setup_telemetry(None, connection_string="InstrumentationKey=x") is True
    assert got == {"connection_string": "InstrumentationKey=x"}
