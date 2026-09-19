from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def _load_env_file() -> None:
    """Minimal .env loader that never logs values and does not overwrite real env vars."""
    env_path = ROOT_DIR / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


_load_env_file()


@dataclass(frozen=True)
class Settings:
    root_dir: Path = ROOT_DIR
    database_path: Path = Path(os.getenv("MAAL_DATABASE_PATH", str(ROOT_DIR / "maal.db"))).resolve()
    llm_provider: str = os.getenv("MAAL_LLM_PROVIDER", "deterministic")
    llm_model: str = os.getenv("MAAL_LLM_MODEL", "claude-sonnet-4-6")
    llm_timeout_seconds: float = float(os.getenv("MAAL_LLM_TIMEOUT_SECONDS", "60"))
    llm_max_retries: int = min(2, max(0, int(os.getenv("MAAL_LLM_MAX_RETRIES", "2"))))
    allowed_origins: tuple[str, ...] = tuple(
        item.strip()
        for item in os.getenv(
            "MAAL_ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000"
        ).split(",")
        if item.strip()
    )
    api_token: str | None = os.getenv("MAAL_API_TOKEN") or None
    prompt_version: str = "maal-prompts-1.0"
    schema_version: str = "2.0"
    pipeline_version: str = "maal-state-machine-2.0"
    connector_timeout_seconds: float = float(os.getenv("MAAL_CONNECTOR_TIMEOUT_SECONDS", "30"))
    connector_max_retries: int = min(2, max(0, int(os.getenv("MAAL_CONNECTOR_MAX_RETRIES", "2"))))
    connector_user_agent: str = os.getenv(
        "MAAL_CONNECTOR_USER_AGENT", "Maal-Regulatory-Monitor/2.0 (+local compliance demo)"
    )
    regulatory_storage_dir: Path = Path(
        os.getenv("MAAL_REGULATORY_STORAGE_DIR", str(ROOT_DIR / "data" / "regulatory" / "raw"))
    ).resolve()
    max_regulatory_document_bytes: int = int(
        os.getenv("MAAL_MAX_REGULATORY_DOCUMENT_BYTES", str(25 * 1024 * 1024))
    )


settings = Settings()
