"""Application configuration via pydantic-settings.

All settings are driven by environment variables with the ``FINALSAY_`` prefix
(see design.md section 2). A ``.env`` file in the working directory is honored.
Defaults keep the demo fully offline: SQLite DB, MOCK comparison model, LOCAL
anchor, and no paid API keys required.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Feature switches and runtime configuration."""

    model_config = SettingsConfigDict(
        env_prefix="FINALSAY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database (SQLite default; Postgres opt-in via FINALSAY_DATABASE_URL).
    database_url: str = "sqlite:///./finalsay.db"

    # Comparison model: mock (default, deterministic/offline) | hf (opt-in).
    comparison_model: str = "mock"
    hf_model_name: str = "facebook/bart-large-mnli"

    # Anchor: local append-only hash chain (default) | polygon (opt-in).
    anchor: str = "local"

    # Confidence gating: below this threshold -> unresolved + reviewer queue.
    confidence_threshold: float = 0.6

    # Auth (HS256 signing secret; dev default, override in production).
    jwt_secret: str = "dev-insecure-finalsay-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 60 * 24

    # Polygon Amoy on-chain anchoring (only used when anchor == "polygon").
    polygon_rpc_url: str | None = None
    polygon_private_key: str | None = None
    polygon_contract: str | None = None

    # OCR: path to the tesseract binary, if present ("auto" -> autodetect).
    tesseract_cmd: str = "auto"


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
