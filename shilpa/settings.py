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
    ollama_model: str = os.getenv("OLLAMA_MODEL", "deepseek-v4.1-flash")
    ollama_timeout_s: float = float(os.getenv("OLLAMA_TIMEOUT_S", 120))
    # Kill switch for every model call: SHILPA_LLM=off|on. Defaults to off when no service is configured,
    # so a checkout without credentials can never reach a paid API by accident.
    llm_mode: str = os.getenv("SHILPA_LLM", "on" if (os.getenv("AZURE_OPENAI_ENDPOINT") or (
        os.getenv("SHILPA_LLM_PROVIDER", "").lower() == "ollama" and os.getenv("OLLAMA_API_KEY"))) else "off"
    ).strip().lower()
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

    @property
    def planner_status(self) -> str:
        """disabled (kill switch) | online | not_configured."""
        if not self.llm_enabled:
            return "disabled"
        return "online" if self.llm_configured else "not_configured"


settings = Settings()
