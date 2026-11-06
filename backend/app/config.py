from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "production", "test"] = "development"

    database_url: str
    # Connection pool. Hosted databases cap connections (Aiven free: 15), so keep this small.
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=5, ge=0, le=50)
    # Only read by the test suite; must point at a disposable database.
    test_database_url: str | None = None
    # Used to derive per-session CSRF tokens. Must be long and random; never shipped to browsers.
    secret_key: str = Field(min_length=32)

    allowed_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    allowed_hosts: Annotated[list[str], NoDecode] = ["localhost", "127.0.0.1"]

    # Cookies. In production COOKIE_SECURE must be true; the cookie then uses the __Host- prefix.
    cookie_secure: bool = True
    cookie_samesite: Literal["strict", "lax"] = "strict"

    # Sessions: absolute lifetime and idle timeout.
    session_ttl_minutes: int = Field(default=12 * 60, ge=5)
    session_idle_minutes: int = Field(default=60, ge=1)

    # Login rate limiting (failed attempts within the window). Turn on for any internet-facing deployment.
    login_rate_limit_enabled: bool = True
    login_max_failures_per_user: int = Field(default=5, ge=1)
    login_max_failures_per_ip: int = Field(default=20, ge=1)
    login_window_seconds: int = Field(default=15 * 60, ge=1)

    max_users: int = 2

    # Folder with the built website (frontend/dist). When set, the API also serves the site, so
    # pages, API and WebSocket share one origin (needed for the strict session cookie).
    static_dir: str | None = None
    # Minimum account password length enforced by the admin CLI.
    min_password_length: int = Field(default=12, ge=1, le=256)

    # Messaging
    message_rate_limit: int = Field(default=30, ge=1)
    message_rate_window_seconds: int = Field(default=60, ge=1)
    # How often an open WebSocket re-checks that its session is still valid.
    ws_auth_recheck_seconds: float = Field(default=30, ge=0.05)

    @field_validator("database_url", "test_database_url")
    @classmethod
    def _psycopg_driver(cls, value: str | None) -> str | None:
        # Hosting providers (Aiven, Render, Heroku...) hand out postgres:// URLs; use the psycopg 3 driver.
        if value and value.startswith(("postgres://", "postgresql://")):
            return "postgresql+psycopg://" + value.split("://", 1)[1]
        return value

    @field_validator("allowed_origins", "allowed_hosts", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def session_cookie_name(self) -> str:
        # __Host- cookies are only accepted over HTTPS with Secure, Path=/ and no Domain.
        return "__Host-duo_session" if self.cookie_secure else "duo_session"

    @property
    def docs_enabled(self) -> bool:
        return self.environment == "development"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()  # type: ignore[call-arg]
    if settings.environment == "production" and not settings.cookie_secure:
        raise RuntimeError("COOKIE_SECURE must be true in production")
    return settings
