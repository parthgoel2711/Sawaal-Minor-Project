"""Application settings, loaded from environment variables and the repo-root .env file."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> parents[2] is the repository root
ROOT_DIR = Path(__file__).resolve().parents[2]

# Models that accept the server-side refusal fallback parameter.
FALLBACK_CAPABLE_MODELS = {
    "claude-opus-5-5",
    "claude-opus-5",
    "claude-sonnet-5-5",
    "claude-fable-5-1",
    "claude-fable-5-2",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- AI provider ---
    # "auto" uses Claude if an Anthropic key is set, otherwise Groq if a Groq key is set.
    llm_provider: Literal["auto", "anthropic", "groq"] = "auto"
    max_fix_attempts: int = 3  # how many times the AI may repair a failing query
    auto_route: bool = True  # answer from another database when the selected one lacks the data

    # --- Claude ---
    anthropic_api_key: str | None = None
    claude_model: str = "claude-opus-5-5"
    claude_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    claude_fallbacks: bool = True

    # --- Groq (has a free tier) ---
    groq_api_key: str | None = None
    groq_model: str = "openai/gpt-oss-120b"
    # Used when the main model is rate-limited or fails (each model has its own free-tier limit).
    groq_fallback_model: str = "openai/gpt-oss-20b"

    # --- Storage ---
    data_dir: Path = ROOT_DIR / "data"
    frontend_dist: Path = ROOT_DIR / "frontend" / "dist"

    # --- Query execution ---
    max_rows: int = 1000
    query_timeout_seconds: float = 15.0
    max_upload_mb: int = 50
    # Hide columns that look like personal data (email, phone, password, Aadhaar...) in every result.
    mask_pii: bool = True
    # Plain-English questions allowed per client per minute (0 turns the limit off).
    rate_limit_per_minute: int = 30

    # --- Sign-in (off by default: everyone is a local admin) ---
    # Answer a prepared set of questions without any AI key. For presentations; the app labels it "Demo AI".
    demo_mode: bool = False
    auth_enabled: bool = False
    session_hours: int = 12
    # Signs session cookies so they work across several server instances (set this on serverless hosting).
    session_secret: str | None = None
    # Password for the first admin. If empty, one is generated and printed once at first start.
    admin_password: str | None = None
    # Also create demo users (analyst and viewer) with documented passwords. For presentations only.
    demo_users: bool = False
    # Comma-separated tables that viewers may not read or even see (e.g. "payroll,performance_reviews").
    restricted_tables: str = ""

    # Extra databases, as "name=sqlalchemy_url" pairs separated by ";"
    # e.g. "analytics=postgresql+psycopg://readonly:pw@localhost/analytics"
    databases: str = ""

    # Comma-separated list of origins allowed to call the API (dev server by default)
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def has_anthropic_key(self) -> bool:
        return bool(
            self.anthropic_api_key
            or os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        )

    @property
    def has_groq_key(self) -> bool:
        return bool(self.groq_api_key or os.environ.get("GROQ_API_KEY"))

    @property
    def provider(self) -> Literal["anthropic", "groq", "demo"] | None:
        """The AI provider in use, or None when no usable API key is configured."""
        if self.demo_mode:
            return "demo"
        if self.llm_provider == "anthropic":
            return "anthropic" if self.has_anthropic_key else None
        if self.llm_provider == "groq":
            return "groq" if self.has_groq_key else None
        if self.has_anthropic_key:
            return "anthropic"
        if self.has_groq_key:
            return "groq"
        return None

    @property
    def llm_enabled(self) -> bool:
        return self.provider is not None

    @property
    def active_model(self) -> str:
        if self.provider == "demo":
            return "prepared answers"
        return self.groq_model if self.provider == "groq" else self.claude_model

    @property
    def use_fallbacks(self) -> bool:
        return self.claude_fallbacks and self.claude_model in FALLBACK_CAPABLE_MODELS

    @property
    def sample_dir(self) -> Path:
        return self.data_dir / "sample"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def app_db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def restricted_table_set(self) -> frozenset[str]:
        return frozenset(t.strip().lower() for t in self.restricted_tables.split(",") if t.strip())

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def external_databases(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for pair in self.databases.split(";"):
            if "=" not in pair:
                continue
            name, url = pair.split("=", 1)
            if name.strip() and url.strip():
                result[name.strip()] = url.strip()
        return result


@lru_cache
def get_settings() -> Settings:
    return Settings()
