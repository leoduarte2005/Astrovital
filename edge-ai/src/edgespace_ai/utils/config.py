"""Environment-driven configuration for Edge Space AI."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from ``EDGESPACE_*`` environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="EDGESPACE_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    ai_host: str = Field(default="127.0.0.1", description="TCP bind host for IPC server")
    ai_port: int = Field(default=5006, ge=0, le=65535, description="TCP bind port for IPC server")
    models_dir: Path = Field(default=Path("./models"), description="Directory containing ONNX models")
    db_path: Path = Field(default=Path("../data/edgespace.db"), description="SQLite database path")
    ort_threads: int = Field(default=2, ge=1, le=64, description="ONNX Runtime intra-op thread count")
    disable_slm: bool = Field(default=False, description="Disable local GGUF SLM conversational synthesizer")

    log_level: str = Field(default="INFO", description="Structured log level")
    ipc_hi_pri_cap: int = Field(default=64, ge=1, description="High-priority queue capacity")
    ipc_lo_pri_cap: int = Field(default=8, ge=1, description="Low-priority queue capacity")
    ipc_max_window_age_ms: int = Field(
        default=1000,
        ge=0,
        description="Maximum age (ms) for queued CSI_WINDOW frames before drop (0 disables age drop)",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached runtime settings instance."""
    return Settings()


def clear_settings_cache() -> None:
    """Clear the cached settings instance (useful in tests)."""
    get_settings.cache_clear()

