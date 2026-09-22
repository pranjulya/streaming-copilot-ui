import os

import pytest
from pydantic import ValidationError

from app.settings import Settings


@pytest.fixture(autouse=True)
def clean_settings_environment(monkeypatch):
    # Isolate from developers' secrets and copied .env files.
    for name in list(os.environ):
        if name.lower() in Settings.model_fields:
            monkeypatch.delenv(name)


def test_local_defaults_and_unique_boot_identity():
    first = Settings(_env_file=None)
    assert first.app_env == "development"
    assert first.dev_user_id == "dev-user"
    assert first.instance_id != Settings(_env_file=None).instance_id


def test_environment_values_are_loaded(monkeypatch):
    monkeypatch.setenv("MAX_MESSAGE_CHARS", "40")
    assert Settings(_env_file=None).max_message_chars == 40


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_non_development_fails_without_explicit_credentials(environment):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env=environment)


def production_settings(**overrides):
    return Settings(
        _env_file=None,
        app_env="production",
        database_url="postgresql+asyncpg://app:secret@db.internal/copilot",
        xai_api_key="test-only-key",
        auth_jwt_issuer="https://auth.example.test",
        auth_jwt_audience="copilot",
        auth_jwt_jwks_url="https://auth.example.test/jwks.json",
        **overrides,
    )


def test_production_has_no_development_identity():
    assert production_settings().dev_user_id is None


def test_production_rejects_development_identity():
    with pytest.raises(ValidationError, match="DEV_USER_ID"):
        production_settings(dev_user_id="dev-user")


@pytest.mark.parametrize("field", ["max_message_chars", "lease_seconds", "event_follow_poll_ms"])
def test_nonpositive_limits_rejected(field):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: 0})


def test_lease_renewal_must_precede_expiry():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, lease_seconds=5, lease_renew_seconds=5)


def test_wrong_database_driver_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url="sqlite:///test.db")


def test_invalid_configuration_does_not_echo_secrets():
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, app_env="production", xai_api_key="do-not-log-this-key")
    assert "do-not-log-this-key" not in str(caught.value)
