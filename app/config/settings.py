"""App settings loaded from env. Rejects unsafe placeholder secrets in production."""

from functools import lru_cache
from typing import Literal, Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ponytail: any value containing this marker is treated as an unset placeholder.
_PLACEHOLDER = "CHANGE_ME"
_SECRET_FIELDS = (
    "app_secret_key",
    "admin_api_key",
    "admin_password_hash",
    "admin_session_secret",
    "telegram_bot_token",
    "tradingview_webhook_token",
    "tradingview_body_secret",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_env: Literal["local", "staging", "production"] = "local"
    app_secret_key: str = _PLACEHOLDER
    log_level: str = "INFO"
    default_timezone: str = "UTC"

    database_url: str
    redis_url: str = "redis://localhost:6379/0"

    admin_auth_mode: str = "api_key"
    admin_api_key: str = _PLACEHOLDER
    admin_console_enabled: bool = True
    admin_username: str = "admin"
    admin_password_hash: str = _PLACEHOLDER
    admin_session_secret: str = _PLACEHOLDER
    admin_session_ttl_hours: int = 8

    telegram_bot_token: str = _PLACEHOLDER
    telegram_send_timeout_seconds: int = 10
    telegram_health_cache_seconds: int = 300

    tradingview_webhook_token: str = _PLACEHOLDER
    tradingview_body_secret: str = _PLACEHOLDER
    tradingview_allowed_ips: str = ""

    outbox_lock_timeout_seconds: int = 120
    retry_scan_interval_seconds: int = 20
    duplicate_lock_ttl_seconds: int = 60

    stale_grace_minutes: int = 20
    future_candle_buffer_seconds: int = 120

    candle_retention_days: int = 365
    audit_retention_days: int = 365

    mtx_webhook_secret: str = ""
    webhook_future_allowed_skew_seconds: int = 300

    ai_filter_enabled: bool = False
    ai_filter_provider: str = "off"
    ai_filter_api_url: Optional[str] = None
    ai_filter_api_key: Optional[str] = None
    ai_filter_model: str = "gpt-4o-mini"

    @model_validator(mode="after")
    def _reject_placeholders_in_prod(self) -> "Settings":
        if self.app_env != "production":
            return self
        bad = [
            f
            for f in _SECRET_FIELDS
            if _PLACEHOLDER in str(getattr(self, f)) or len(str(getattr(self, f))) < 16
        ]
        if bad:
            raise ValueError(
                f"Refusing to start in production with placeholder/short secrets: {', '.join(bad)}"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
