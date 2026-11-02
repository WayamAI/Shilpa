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
