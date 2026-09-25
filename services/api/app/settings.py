from pathlib import Path
from typing import Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, PositiveInt, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"
LOCAL_DATABASE_URL = "postgresql+asyncpg://copilot:copilot@127.0.0.1:5432/copilot"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_ENV, extra="ignore", env_ignore_empty=True, hide_input_in_errors=True
    )

    app_env: Literal["development", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: SecretStr = SecretStr(LOCAL_DATABASE_URL)
    instance_id: UUID = Field(default_factory=uuid4)
    xai_api_key: SecretStr | None = None
    xai_base_url: str = "https://api.x.ai/v1"
    xai_model: str = "grok-4.6"
    system_prompt: str = (
        "You are a helpful Copilot. Answer in Markdown. Do not claim tool use, browsing, "
        "or private chain-of-thought. If you are unsure, say so."
    )
    dev_user_id: str | None = None
    fake_provider_plan: str = ""
    auth_jwt_issuer: str | None = None
    auth_jwt_audience: str | None = None
    auth_jwt_jwks_url: str | None = None
    auth_jwt_subject_claim: str = "sub"
    auth_cookie_name: str | None = None
    allowed_origins: str = "http://127.0.0.1:3000"
    max_message_chars: PositiveInt = 8000
    max_output_chars: PositiveInt = 100000
    max_request_bytes: PositiveInt = 65536
    context_char_budget: PositiveInt = 120000
    max_active_runs_per_user: PositiveInt = 3
    create_response_per_minute: PositiveInt = 20
    lease_seconds: PositiveInt = 15
    lease_renew_seconds: PositiveInt = 5
    provider_connect_timeout_seconds: PositiveInt = 10
    provider_idle_timeout_seconds: PositiveInt = 30
    generation_timeout_seconds: PositiveInt = 120
    heartbeat_interval_seconds: PositiveInt = 15
    event_follow_poll_ms: PositiveInt = 50
    delta_flush_ms: PositiveInt = 40
    delta_flush_chars: PositiveInt = 24
    shutdown_grace_seconds: PositiveInt = 10
    event_retention_hours: PositiveInt = 24
    idempotency_ttl_hours: PositiveInt = 24

    @model_validator(mode="after")
    def validate_runtime(self) -> Self:
        try:
            url = make_url(self.database_url.get_secret_value())
        except ArgumentError:
            raise ValueError("DATABASE_URL must be a PostgreSQL asyncpg URL") from None
        if url.drivername != "postgresql+asyncpg" or not url.host or not url.database:
            raise ValueError("DATABASE_URL must be a PostgreSQL asyncpg URL with host and database")
        if self.lease_renew_seconds >= self.lease_seconds:
            raise ValueError("LEASE_RENEW_SECONDS must be less than LEASE_SECONDS")
        if self.app_env == "development":
            self.dev_user_id = self.dev_user_id or "dev-user"
        else:
            required = {
                "DATABASE_URL": "database_url" in self.model_fields_set,
                "XAI_API_KEY": self.xai_api_key and self.xai_api_key.get_secret_value().strip(),
                "AUTH_JWT_ISSUER": self.auth_jwt_issuer and self.auth_jwt_issuer.strip(),
                "AUTH_JWT_AUDIENCE": self.auth_jwt_audience and self.auth_jwt_audience.strip(),
                "AUTH_JWT_JWKS_URL": self.auth_jwt_jwks_url and self.auth_jwt_jwks_url.strip(),
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise ValueError("Non-development configuration requires " + ", ".join(missing))
            if self.dev_user_id is not None:
                raise ValueError("DEV_USER_ID must be unset outside development")
        return self
