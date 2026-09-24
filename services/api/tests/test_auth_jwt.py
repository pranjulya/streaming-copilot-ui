import asyncio
import os
import time
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt import encode as jwt_encode

from tests.support import database_url, new_user

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL for real Postgres"
)

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC_KEY = (
    KEY.public_key()
    .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    .decode()
)
ISSUER = "https://auth.example.test"
AUDIENCE = "copilot"


def make_token(
    *,
    subject: str = "user-1",
    issuer: str = ISSUER,
    audience: str = AUDIENCE,
    expires_in: int = 300,
    key=KEY,
) -> str:
    now = int(time.time())
    return jwt_encode(
        {
            "sub": subject,
            "iss": issuer,
            "aud": audience,
            "iat": now,
            "exp": now + expires_in,
        },
        key,
        algorithm="RS256",
    )


def staging_app(**overrides: object):
    from fastapi import Depends

    from app.api.auth import Actor, require_actor
    from app.main import create_app
    from app.settings import Settings

    settings = Settings(
        _env_file=None,
        app_env="staging",
        database_url=database_url(),
        xai_api_key="test-key",
        auth_jwt_issuer=ISSUER,
        auth_jwt_audience=AUDIENCE,
        auth_jwt_jwks_url="https://auth.example.test/jwks.json",
        **overrides,  # type: ignore[arg-type]
    )
    app = create_app(settings)

    @app.get("/v1/_jwt-probe")
    def jwt_probe(actor: Actor = Depends(require_actor)) -> dict[str, str]:
        return {"user_id": actor.user_id, "mode": actor.auth_mode}

    original_lifespan_started = app.router.lifespan_context

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan_with_stub_key(current_app):
        async with original_lifespan_started(current_app) as state:
            current_app.state.jwt_verifier._key_resolver = (  # noqa: SLF001
                lambda token: KEY.public_key()
            )
            yield state

    app.router.lifespan_context = lifespan_with_stub_key
    return app


def test_valid_token_scopes_the_actor() -> None:
    with TestClient(staging_app()) as client:
        response = client.get(
            "/v1/_jwt-probe", headers={"Authorization": f"Bearer {make_token(subject='alice')}"}
        )
    assert response.status_code == 200
    assert response.json() == {"user_id": "alice", "mode": "bearer"}


def test_invalid_tokens_are_401() -> None:
    bad_cases = [
        ("expired", make_token(expires_in=-60)),
        ("wrong issuer", make_token(issuer="https://evil.example")),
        ("wrong audience", make_token(audience="someone-else")),
        (
            "bad signature",
            make_token(key=rsa.generate_private_key(public_exponent=65537, key_size=2048)),
        ),
        ("garbage", "not-a-jwt"),
        ("missing", None),
    ]
    with TestClient(staging_app()) as client:
        for name, token in bad_cases:
            headers = {} if token is None else {"Authorization": f"Bearer {token}"}
            response = client.get("/v1/_jwt-probe", headers=headers)
            assert response.status_code == 401, name
            assert response.json()["code"] == "unauthenticated", name


def test_dev_header_is_still_refused_outside_development() -> None:
    with TestClient(staging_app()) as client:
        response = client.get("/v1/_jwt-probe", headers={"X-Dev-User": "alice"})
    assert response.status_code == 401


def test_cookie_auth_requires_csrf_and_allowed_origin() -> None:
    settings_overrides = {"auth_cookie_name": "session"}

    async def scenario() -> None:
        with TestClient(staging_app(**settings_overrides)) as client:
            token = make_token(subject="cookie-user")
            client.cookies.set("session", token)
            read = client.get("/v1/_jwt-probe")
            assert read.status_code == 200
            assert read.json() == {"user_id": "cookie-user", "mode": "cookie"}

            post = client.post("/v1/conversations", json={})
            assert post.status_code == 401
            assert post.json()["code"] == "unauthenticated"

            client.cookies.set("csrf_token", "csrf-value")
            missing_origin = client.post(
                "/v1/conversations",
                json={},
                headers={"X-CSRF-Token": "csrf-value"},
            )
            assert missing_origin.status_code == 401

            wrong_origin = client.post(
                "/v1/conversations",
                json={},
                headers={
                    "X-CSRF-Token": "csrf-value",
                    "Origin": "https://evil.example",
                },
            )
            assert wrong_origin.status_code == 401

            allowed = client.post(
                "/v1/conversations",
                json={},
                headers={
                    "X-CSRF-Token": "csrf-value",
                    "Origin": "http://127.0.0.1:3000",
                    "Idempotency-Key": str(uuid.uuid4()),
                },
            )
            assert allowed.status_code == 201

    asyncio.run(scenario())


def test_missing_subject_claim_is_401() -> None:
    now = int(time.time())
    import jwt as pyjwt

    token = pyjwt.encode(
        {"iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + 300},
        KEY,
        algorithm="RS256",
    )
    with TestClient(staging_app()) as client:
        response = client.get("/v1/_jwt-probe", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_alg_none_and_hs256_tokens_are_401() -> None:
    now = int(time.time())
    claims = {
        "sub": "alice",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + 300,
    }
    import jwt as pyjwt

    hs = pyjwt.encode(claims, "not-an-rsa-secret", algorithm="HS256")
    header = (
        __import__("base64").urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
    )
    payload = (
        __import__("base64")
        .urlsafe_b64encode(__import__("json").dumps(claims).encode())
        .rstrip(b"=")
        .decode()
    )
    none_token = f"{header}.{payload}."
    with TestClient(staging_app()) as client:
        for token in (hs, none_token):
            response = client.get("/v1/_jwt-probe", headers={"Authorization": f"Bearer {token}"})
            assert response.status_code == 401
            assert response.json()["code"] == "unauthenticated"


def test_hash_user_id_is_stable_and_never_raw() -> None:
    from app.api.auth_jwt import hash_user_id

    assert hash_user_id("alice") == hash_user_id("alice")
    assert "alice" not in hash_user_id("alice")
    assert hash_user_id(new_user("u")) != hash_user_id(new_user("u"))
