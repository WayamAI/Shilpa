"""Runtime configuration from environment / .env (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


# Price table: model name -> (input USD per 1M tokens, output USD per 1M tokens[, cached-input USD per 1M tokens]).
# TODO(user): fill in the real prices for your Ollama Cloud models and Azure deployments. They are deliberately
# empty: unknown models get ``cost_usd: None`` rather than an invented number. The same table can be supplied
# without editing code as JSON in SHILPA_MODEL_PRICES, e.g. '{"beam": [0.5, 1.5], "gpt-4o": [2.5, 10, 1.25]}'.
MODEL_PRICES_USD_PER_MTOK: dict[str, tuple[float, ...]] = {}


def _prices() -> dict[str, tuple[float, ...]]:
    import json

    table = dict(MODEL_PRICES_USD_PER_MTOK)
    raw = os.getenv("SHILPA_MODEL_PRICES", "").strip()
    if raw:
        table.update({k: tuple(float(x) for x in v) for k, v in json.loads(raw).items()})
    return table


@dataclass(frozen=True)
class Budgets:
    """Per-job budgets shared by every call and retry (blueprint section 9)."""

    cad_operations: int = _int("SHILPA_BUDGET_CAD_OPERATIONS", 50)
    cad_executions: int = _int("SHILPA_BUDGET_CAD_EXECUTIONS", 3)
    repair_calls: int = _int("SHILPA_BUDGET_REPAIR_CALLS", 2)
    input_tokens: int = _int("SHILPA_BUDGET_INPUT_TOKENS", 60_000)
    output_tokens: int = _int("SHILPA_BUDGET_OUTPUT_TOKENS", 24_000)
    elapsed_s: int = _int("SHILPA_BUDGET_ELAPSED_S", 15 * 60)


@dataclass(frozen=True)
class Settings:
    var_dir: Path = Path(os.getenv("SHILPA_VAR_DIR", ROOT / "var"))
    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{(ROOT / 'var' / 'shilpa.db').as_posix()}")
    auth_mode: str = os.getenv("SHILPA_AUTH_MODE", "dev")  # dev | entra
    # Azure OpenAI (the only cloud dependency in local mode)
    aoai_endpoint: str = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    aoai_api_key: str = os.getenv("AZURE_OPENAI_API_KEY", "")
    aoai_auth: str = os.getenv("AZURE_OPENAI_AUTH", "default")  # key | azure_cli | default
    aoai_api_version: str = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
    aoai_deployment: str = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
    aoai_timeout_s: float = float(os.getenv("AZURE_OPENAI_TIMEOUT_S", 90))
    # Which model service the planner uses: azure (Azure OpenAI) or ollama (Ollama Cloud, native chat API).
    llm_provider: str = os.getenv("SHILPA_LLM_PROVIDER", "azure").strip().lower()
    ollama_api_key: str = os.getenv("OLLAMA_API_KEY", "")
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "https://ollama.com").rstrip("/")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "beam")  # best on evals/screen_models.py and the G2 holdout
    # Requests with images (drawings) go here: the text model may not accept images (beam does not).
    ollama_vision_model: str = os.getenv("OLLAMA_VISION_MODEL", "kimi-k3")  # 26/26 on evals/run_drawings.py, fastest
    ollama_timeout_s: float = float(os.getenv("OLLAMA_TIMEOUT_S", 120))
    # Kill switch for every model call: SHILPA_LLM=off|on. Defaults to off when no service is configured,
    # so a checkout without credentials can never reach a paid API by accident.
    llm_mode: str = os.getenv("SHILPA_LLM", "on" if (os.getenv("AZURE_OPENAI_ENDPOINT") or (
        os.getenv("SHILPA_LLM_PROVIDER", "").lower() == "ollama" and os.getenv("OLLAMA_API_KEY"))) else "off"
    ).strip().lower()
    # Per-stage model overrides (blank = the provider's single default model above). For Azure these are
    # deployment names, for Ollama model names. Stages: intake, plan, repair, edit.
    model_intake: str = os.getenv("SHILPA_MODEL_INTAKE", "").strip()
    model_plan: str = os.getenv("SHILPA_MODEL_PLAN", "").strip()
    model_repair: str = os.getenv("SHILPA_MODEL_REPAIR", "").strip()
    model_edit: str = os.getenv("SHILPA_MODEL_EDIT", "").strip()
    # Number of golden examples embedded in each plan prompt, chosen per request by keyword similarity.
    plan_examples_k: int = _int("SHILPA_PLAN_EXAMPLES_K", 3)
    # Content-addressed result cache for intake and plan calls (never repair/edit). 0/off disables it.
    llm_cache: bool = os.getenv("SHILPA_LLM_CACHE", "on").strip().lower() not in ("off", "0", "false", "no")
    llm_cache_ttl_s: int = _int("SHILPA_LLM_CACHE_TTL_S", 7 * 24 * 3600)
    llm_cache_max_entries: int = _int("SHILPA_LLM_CACHE_MAX_ENTRIES", 2000)
    model_prices: dict = field(default_factory=_prices)
    # Worker
    worker_timeout_s: int = _int("SHILPA_WORKER_TIMEOUT_S", 300)
    lock_duration_s: int = _int("SHILPA_LOCK_DURATION_S", 60)
    max_delivery_count: int = _int("SHILPA_MAX_DELIVERY_COUNT", 5)
    budgets: Budgets = field(default_factory=Budgets)

    @property
    def blob_root(self) -> Path:
        return self.var_dir / "blobs"

    @property
    def llm_enabled(self) -> bool:
        """False when the kill switch is off: no model call may leave this process."""
        return self.llm_mode not in ("off", "0", "false", "no", "disabled")

    @property
    def llm_configured(self) -> bool:
        if self.llm_provider == "ollama":
            return self.llm_enabled and bool(self.ollama_api_key and self.ollama_model)
        return self.llm_enabled and bool(self.aoai_endpoint and self.aoai_deployment)

    @property
    def llm_model(self) -> str:
        """The model or deployment name calls go to (for logs and the health endpoint)."""
        return self.ollama_model if self.llm_provider == "ollama" else self.aoai_deployment

    def stage_model(self, stage: str | None) -> str | None:
        """The model override for a stage (intake | plan | repair | edit), or None for the provider default."""
        return {"intake": self.model_intake, "plan": self.model_plan, "repair": self.model_repair,
                "edit": self.model_edit}.get(stage or "") or None

    def estimate_cost_usd(self, model: str | None, input_tokens: int, output_tokens: int,
                          cached_input_tokens: int | None = None) -> float | None:
        """Estimated USD for one call from the price table; None when the model has no listed price."""
        price = self.model_prices.get(model or "")
        if not price or len(price) < 2:
            return None
        cached = min(cached_input_tokens or 0, input_tokens)
        cached_rate = price[2] if len(price) > 2 else price[0]
        return round(((input_tokens - cached) * price[0] + cached * cached_rate + output_tokens * price[1]) / 1e6, 6)

    @property
    def planner_status(self) -> str:
        """disabled (kill switch) | online | not_configured."""
        if not self.llm_enabled:
            return "disabled"
        return "online" if self.llm_configured else "not_configured"


settings = Settings()


# ============================================================================================================
# Hosting block (azure hosting plan, step 3): environment name, Entra ID and telemetry settings, startup guard.
# Kept separate from ``Settings`` above. Read at call time through ``hosting`` so tests can replace it.
# ============================================================================================================
ENVIRONMENTS = ("local", "dev", "staging", "production")


class ConfigError(RuntimeError):
    """The process refuses to start: a setting is forbidden or missing in this environment."""


def _csv(name: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in os.getenv(name, "").split(",") if x.strip())


def _flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.strip().lower() in ("1", "true", "on", "yes")


@dataclass(frozen=True)
class HostingSettings:
    env: str = os.getenv("SHILPA_ENV", "local").strip().lower()
    # Entra ID access-token validation (used when SHILPA_AUTH_MODE=entra)
    entra_tenant_id: str = os.getenv("SHILPA_ENTRA_TENANT_ID", "").strip()
    entra_audiences: tuple[str, ...] = field(default_factory=lambda: _csv("SHILPA_ENTRA_AUDIENCE"))
    entra_required_scope: str = os.getenv("SHILPA_ENTRA_REQUIRED_SCOPE", "").strip()
    entra_required_role: str = os.getenv("SHILPA_ENTRA_REQUIRED_ROLE", "").strip()
    entra_authority: str = os.getenv("SHILPA_ENTRA_AUTHORITY", "https://login.microsoftonline.com").rstrip("/")
    entra_jwks_url: str = os.getenv("SHILPA_ENTRA_JWKS_URL", "").strip()  # default derived from authority + tenant
    entra_leeway_s: int = _int("SHILPA_ENTRA_LEEWAY_S", 60)
    entra_jwks_ttl_s: int = _int("SHILPA_ENTRA_JWKS_TTL_S", 3600)
    entra_auto_provision: bool = _flag("SHILPA_ENTRA_AUTO_PROVISION", False)
    entra_default_role: str = os.getenv("SHILPA_ENTRA_DEFAULT_ROLE", "project_viewer").strip()
    # Telemetry
    appinsights_connection_string: str = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "").strip()
    log_level: str = os.getenv("SHILPA_LOG_LEVEL", "INFO").strip().upper()

    @property
    def is_hosted(self) -> bool:
        return self.env != "local"

    @property
    def entra_jwks_uri(self) -> str:
        return self.entra_jwks_url or f"{self.entra_authority}/{self.entra_tenant_id}/discovery/v2.0/keys"

    @property
    def entra_issuers(self) -> tuple[str, ...]:
        """Accepted ``iss`` values: v2.0 and v1.0 token formats for the configured tenant."""
        t = self.entra_tenant_id
        return (f"{self.entra_authority}/{t}/v2.0", f"https://sts.windows.net/{t}/")


def startup_problems(h: HostingSettings | None = None, s: Settings | None = None) -> list[str]:
    """Every reason this configuration must not start, each naming the variable. Empty means fine."""
    h, s = h or hosting, s or settings
    if h.env not in ENVIRONMENTS:
        return [f"SHILPA_ENV={h.env!r} is not one of {', '.join(ENVIRONMENTS)}"]
    problems: list[str] = []
    if h.env != "local":
        if s.llm_provider == "ollama":
            problems.append(f"SHILPA_LLM_PROVIDER=ollama is not allowed when SHILPA_ENV={h.env}: engineering data "
                            "must not go to a non-Azure model host (use SHILPA_LLM_PROVIDER=azure)")
        if s.auth_mode == "dev":
            problems.append(f"SHILPA_AUTH_MODE=dev is not allowed when SHILPA_ENV={h.env} (use SHILPA_AUTH_MODE=entra)")
        elif s.auth_mode != "entra":
            problems.append(f"SHILPA_AUTH_MODE={s.auth_mode!r} is not valid (entra)")
        if s.database_url.startswith("sqlite"):
            problems.append(f"DATABASE_URL must point at PostgreSQL when SHILPA_ENV={h.env} (it is unset or SQLite)")
        if s.llm_provider not in ("azure", "ollama"):
            problems.append(f"SHILPA_LLM_PROVIDER={s.llm_provider!r} is not valid (azure)")
        if s.llm_enabled and s.llm_provider == "azure":
            if not s.aoai_endpoint:
                problems.append("AZURE_OPENAI_ENDPOINT is required (or set SHILPA_LLM=off)")
            if not s.aoai_deployment:
                problems.append("AZURE_OPENAI_DEPLOYMENT is required (or set SHILPA_LLM=off)")
    if s.auth_mode == "entra":
        if not h.entra_tenant_id:
            problems.append("SHILPA_ENTRA_TENANT_ID is required when SHILPA_AUTH_MODE=entra")
        if not h.entra_audiences:
            problems.append("SHILPA_ENTRA_AUDIENCE is required when SHILPA_AUTH_MODE=entra (API app id URI and/or client id)")
        if not (h.entra_required_scope or h.entra_required_role):
            problems.append("SHILPA_ENTRA_REQUIRED_SCOPE or SHILPA_ENTRA_REQUIRED_ROLE is required when SHILPA_AUTH_MODE=entra")
    if h.entra_auto_provision and h.entra_default_role not in ("org_admin", "project_editor", "project_viewer", "ops_admin"):
        problems.append(f"SHILPA_ENTRA_DEFAULT_ROLE={h.entra_default_role!r} is not a known role")
    return problems


def enforce_startup(h: HostingSettings | None = None, s: Settings | None = None) -> None:
    problems = startup_problems(h, s)
    if problems:
        raise ConfigError("Refusing to start:\n  - " + "\n  - ".join(problems))


hosting = HostingSettings()


# ============================================================================================================
# Cloud adapters block (azure hosting plan, step 2): PostgreSQL pooling/auth, blob backend, queue backend.
# Defaults are the local ones (SQLite file, filesystem blobs, database queue). Read through ``cloud``.
# ============================================================================================================
@dataclass(frozen=True)
class CloudSettings:
    # PostgreSQL (DATABASE_URL stays the connection string; these tune the pool and auth)
    database_auth: str = os.getenv("DATABASE_AUTH", "password").strip().lower()  # password | entra
    db_pool_size: int = _int("SHILPA_DB_POOL_SIZE", 5)
    db_max_overflow: int = _int("SHILPA_DB_MAX_OVERFLOW", 5)
    db_pool_timeout_s: int = _int("SHILPA_DB_POOL_TIMEOUT_S", 30)
    db_pool_recycle_s: int = _int("SHILPA_DB_POOL_RECYCLE_S", 1800)  # below the ~60 min Entra token lifetime
    db_connect_timeout_s: int = _int("SHILPA_DB_CONNECT_TIMEOUT_S", 10)
    db_entra_scope: str = os.getenv("DATABASE_ENTRA_SCOPE", "https://ossrdbms-aad.database.windows.net/.default")
    # Blob storage: local | azure
    blob_backend: str = os.getenv("SHILPA_BLOB_BACKEND", "local").strip().lower()
    blob_account_url: str = os.getenv("SHILPA_BLOB_ACCOUNT_URL", "").strip()  # https://<account>.blob.core.windows.net
    blob_container: str = os.getenv("SHILPA_BLOB_CONTAINER", "artifacts").strip()
    blob_connection_string: str = os.getenv("SHILPA_BLOB_CONNECTION_STRING", "").strip()  # Azurite / emulator only
    blob_workdir: str = os.getenv("SHILPA_WORKDIR", "").strip()  # scratch root for staging; default: system temp
    # Queue: db | servicebus
    queue_backend: str = os.getenv("SHILPA_QUEUE_BACKEND", "db").strip().lower()
    servicebus_namespace: str = os.getenv("SHILPA_SERVICEBUS_NAMESPACE", "").strip()  # <ns>.servicebus.windows.net
    servicebus_connection_string: str = os.getenv("SHILPA_SERVICEBUS_CONNECTION_STRING", "").strip()  # emulator only
    servicebus_queue_prefix: str = os.getenv("SHILPA_SERVICEBUS_QUEUE_PREFIX", "").strip()
    servicebus_wait_s: float = float(os.getenv("SHILPA_SERVICEBUS_WAIT_S", 1))


cloud = CloudSettings()
