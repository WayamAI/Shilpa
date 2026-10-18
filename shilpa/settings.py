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
    output_tokens: int = _int("SHILPA_BUDGET_OUTPUT_TOKENS", 12_000)
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
    # Worker
    worker_timeout_s: int = _int("SHILPA_WORKER_TIMEOUT_S", 120)
    lock_duration_s: int = _int("SHILPA_LOCK_DURATION_S", 60)
    max_delivery_count: int = _int("SHILPA_MAX_DELIVERY_COUNT", 5)
    budgets: Budgets = field(default_factory=Budgets)

    @property
    def blob_root(self) -> Path:
        return self.var_dir / "blobs"

    @property
    def llm_configured(self) -> bool:
        return bool(self.aoai_endpoint and self.aoai_deployment)


settings = Settings()
