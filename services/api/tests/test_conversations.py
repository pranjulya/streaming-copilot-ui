import asyncio
import os
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.main import create_app
from app.settings import Settings

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL for real Postgres"
)


def database_url() -> str:
    return os.environ["TEST_DATABASE_URL"]


async def with_rollback(run: Callable[[AsyncConnection], Awaitable[None]]) -> None:
    engine = create_async_engine(database_url())
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await run(connection)
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


async def expect_constraint(sql: str, params: dict[str, object], sqlstate: str) -> None:
    from sqlalchemy.exc import IntegrityError

    engine = create_async_engine(database_url())
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                with pytest.raises(IntegrityError) as caught:
                    await connection.execute(text(sql), params)
                assert caught.value.orig.sqlstate == sqlstate, (
                    f"expected SQLSTATE {sqlstate}, got {caught.value.orig.sqlstate}"
                )
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


async def new_conversation() -> uuid.UUID:
    conversation_id = uuid.uuid4()
    engine = create_async_engine(database_url())
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO conversations (id, user_id, title, created_at, updated_at)"
                    " VALUES (:id, :user_id, 'title', :now, :now)"
                ),
                {
                    "id": conversation_id,
                    "user_id": f"owner-{conversation_id}",
                    "now": datetime.now(UTC),
                },
            )
    finally:
        await engine.dispose()
    return conversation_id


def test_conversation_queries_are_scoped_to_the_owner() -> None:
    alice_id = uuid.uuid4()
    bob_id = uuid.uuid4()

    async def scenario(connection: AsyncConnection) -> None:
        await connection.execute(
            text("INSERT INTO conversations (id, user_id, title) VALUES (:id, :user_id, 'a')"),
            {"id": alice_id, "user_id": "alice-owner"},
        )
        await connection.execute(
            text("INSERT INTO conversations (id, user_id, title) VALUES (:id, :user_id, 'b')"),
            {"id": bob_id, "user_id": "bob-owner"},
        )
        rows = (
            await connection.execute(
                text("SELECT id FROM conversations WHERE user_id = 'alice-owner'")
            )
        ).all()
        assert [row[0] for row in rows] == [alice_id]

    asyncio.run(with_rollback(scenario))


def test_valid_user_and_assistant_messages_insert() -> None:
    async def scenario() -> None:
        conversation_id = await new_conversation()
        user_message_id = uuid.uuid4()
        engine = create_async_engine(database_url())
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO messages (id, conversation_id, role, content, status,"
                        " client_message_id) VALUES (:id, :cid, 'user', 'hi', 'complete', :cmid)"
                    ),
                    {"id": user_message_id, "cid": conversation_id, "cmid": uuid.uuid4()},
                )
                await connection.execute(
                    text(
                        "INSERT INTO messages (id, conversation_id, role, content, status,"
                        " in_reply_to_id) VALUES (:id, :cid, 'assistant', 'yo', 'complete', :rid)"
                    ),
                    {"id": uuid.uuid4(), "cid": conversation_id, "rid": user_message_id},
                )
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_role_outside_enum_rejected() -> None:
    async def scenario() -> None:
        conversation_id = await new_conversation()
        await expect_constraint(
            "INSERT INTO messages (id, conversation_id, role, content, status, client_message_id)"
            " VALUES (:id, :cid, 'system', 'hi', 'complete', :cmid)",
            {"id": uuid.uuid4(), "cid": conversation_id, "cmid": uuid.uuid4()},
            "23514",
        )

    asyncio.run(scenario())


def test_user_message_requires_client_message_id() -> None:
    async def scenario() -> None:
        conversation_id = await new_conversation()
        await expect_constraint(
            "INSERT INTO messages (id, conversation_id, role, content, status)"
            " VALUES (:id, :cid, 'user', 'hi', 'complete')",
            {"id": uuid.uuid4(), "cid": conversation_id},
            "23514",
        )

    asyncio.run(scenario())


def test_user_message_requires_complete_status() -> None:
    async def scenario() -> None:
        conversation_id = await new_conversation()
        await expect_constraint(
            "INSERT INTO messages (id, conversation_id, role, content, status,"
            " client_message_id) VALUES (:id, :cid, 'user', 'hi', 'partial', :cmid)",
            {"id": uuid.uuid4(), "cid": conversation_id, "cmid": uuid.uuid4()},
            "23514",
        )

    asyncio.run(scenario())


def test_status_outside_enum_rejected() -> None:
    async def scenario() -> None:
        conversation_id = await new_conversation()
        await expect_constraint(
            "INSERT INTO messages (id, conversation_id, role, content, status, client_message_id)"
            " VALUES (:id, :cid, 'user', 'hi', 'pending', :cmid)",
            {"id": uuid.uuid4(), "cid": conversation_id, "cmid": uuid.uuid4()},
            "23514",
        )

    asyncio.run(scenario())


def test_assistant_message_requires_in_reply_to() -> None:
    async def scenario() -> None:
        conversation_id = await new_conversation()
        await expect_constraint(
            "INSERT INTO messages (id, conversation_id, role, content, status)"
            " VALUES (:id, :cid, 'assistant', 'yo', 'partial')",
            {"id": uuid.uuid4(), "cid": conversation_id},
            "23514",
        )

    asyncio.run(scenario())


def test_duplicate_client_message_id_rejected_within_conversation() -> None:
    async def scenario() -> None:
        conversation_id = await new_conversation()
        client_message_id = uuid.uuid4()
        engine = create_async_engine(database_url())
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO messages (id, conversation_id, role, content, status,"
                        " client_message_id) VALUES (:id, :cid, 'user', 'hi', 'complete', :cmid)"
                    ),
                    {"id": uuid.uuid4(), "cid": conversation_id, "cmid": client_message_id},
                )
        finally:
            await engine.dispose()
        await expect_constraint(
            "INSERT INTO messages (id, conversation_id, role, content, status, client_message_id)"
            " VALUES (:id, :cid, 'user', 'hi again', 'complete', :cmid)",
            {"id": uuid.uuid4(), "cid": conversation_id, "cmid": client_message_id},
            "23505",
        )

    asyncio.run(scenario())


def test_only_one_visible_assistant_per_reply() -> None:
    async def scenario() -> None:
        conversation_id = await new_conversation()
        user_message_id = uuid.uuid4()
        engine = create_async_engine(database_url())
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO messages (id, conversation_id, role, content, status,"
                        " client_message_id) VALUES (:id, :cid, 'user', 'hi', 'complete', :cmid)"
                    ),
                    {"id": user_message_id, "cid": conversation_id, "cmid": uuid.uuid4()},
                )
                await connection.execute(
                    text(
                        "INSERT INTO messages (id, conversation_id, role, content, status,"
                        " in_reply_to_id) VALUES (:id, :cid, 'assistant', 'first', 'complete',"
                        " :rid)"
                    ),
                    {"id": uuid.uuid4(), "cid": conversation_id, "rid": user_message_id},
                )
        finally:
            await engine.dispose()
        await expect_constraint(
            "INSERT INTO messages (id, conversation_id, role, content, status, in_reply_to_id)"
            " VALUES (:id, :cid, 'assistant', 'second visible', 'complete', :rid)",
            {"id": uuid.uuid4(), "cid": conversation_id, "rid": user_message_id},
            "23505",
        )

    asyncio.run(scenario())


def test_hidden_assistant_version_allowed_for_same_reply() -> None:
    async def scenario() -> None:
        conversation_id = await new_conversation()
        user_message_id = uuid.uuid4()
        engine = create_async_engine(database_url())
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO messages (id, conversation_id, role, content, status,"
                        " client_message_id) VALUES (:id, :cid, 'user', 'hi', 'complete', :cmid)"
                    ),
                    {"id": user_message_id, "cid": conversation_id, "cmid": uuid.uuid4()},
                )
                await connection.execute(
                    text(
                        "INSERT INTO messages (id, conversation_id, role, content, status,"
                        " in_reply_to_id) VALUES (:id, :cid, 'assistant', 'v1', 'complete', :rid)"
                    ),
                    {"id": uuid.uuid4(), "cid": conversation_id, "rid": user_message_id},
                )
                await connection.execute(
                    text(
                        "INSERT INTO messages (id, conversation_id, role, content, status,"
                        " in_reply_to_id, version, is_visible)"
                        " VALUES (:id, :cid, 'assistant', 'v2 hidden', 'complete', :rid, 2, FALSE)"
                    ),
                    {"id": uuid.uuid4(), "cid": conversation_id, "rid": user_message_id},
                )
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def auth_probe_app(**overrides: object):
    from fastapi import Depends

    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://a:b@127.0.0.1:1/db",
        **overrides,  # type: ignore[arg-type]
    )
    app = create_app(settings)

    from app.api.auth import Actor, require_actor

    @app.get("/v1/_auth-probe")
    def probe(actor: Actor = Depends(require_actor)) -> dict[str, str]:
        return {"user_id": actor.user_id}

    return app


def staging_settings_overrides() -> dict[str, object]:
    return {
        "app_env": "staging",
        "xai_api_key": "test-key",
        "auth_jwt_issuer": "https://auth.example.test",
        "auth_jwt_audience": "copilot",
        "auth_jwt_jwks_url": "https://auth.example.test/jwks.json",
    }


def test_missing_actor_returns_unauthenticated_problem() -> None:
    from fastapi.testclient import TestClient

    app = auth_probe_app(**staging_settings_overrides())
    with TestClient(app) as client:
        response = client.get("/v1/_auth-probe")
    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "unauthenticated"
    assert body["type"] == "https://copilot.local/problems/unauthenticated"
    assert body["status"] == 401
    uuid.UUID(body["diagnostic_id"])


def test_dev_user_header_sets_actor_user_id() -> None:
    from fastapi.testclient import TestClient

    with TestClient(auth_probe_app()) as client:
        response = client.get("/v1/_auth-probe", headers={"X-Dev-User": "alice"})
    assert response.status_code == 200
    assert response.json() == {"user_id": "alice"}


def test_dev_header_rejected_outside_development() -> None:
    from fastapi.testclient import TestClient

    app = auth_probe_app(**staging_settings_overrides())
    with TestClient(app) as client:
        response = client.get("/v1/_auth-probe", headers={"X-Dev-User": "alice"})
    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"


def test_missing_dev_header_falls_back_to_configured_user() -> None:
    from fastapi.testclient import TestClient

    with TestClient(auth_probe_app(dev_user_id="configured-user")) as client:
        response = client.get("/v1/_auth-probe")
    assert response.status_code == 200
    assert response.json() == {"user_id": "configured-user"}


def test_blank_dev_header_falls_back_to_configured_user() -> None:
    from fastapi.testclient import TestClient

    with TestClient(auth_probe_app(dev_user_id="configured-user")) as client:
        response = client.get("/v1/_auth-probe", headers={"X-Dev-User": "   "})
    assert response.status_code == 200
    assert response.json() == {"user_id": "configured-user"}


def api_client(user_id: str) -> TestClient:
    settings = Settings(_env_file=None, database_url=os.environ["TEST_DATABASE_URL"])
    return TestClient(create_app(settings), headers={"X-Dev-User": user_id})


def new_user(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def create_conversation_request(
    client: TestClient, body: dict[str, object], key: str | None = None
) -> dict[str, object]:
    headers = {"Idempotency-Key": key} if key is not None else {}
    response = client.post("/v1/conversations", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_and_list_newest_first_with_opaque_cursor() -> None:
    with api_client(new_user("list")) as client:
        key = str(uuid.uuid4())
        create_conversation_request(client, {"title": "first"}, key)
        create_conversation_request(client, {"title": "second"}, str(uuid.uuid4()))
        create_conversation_request(client, {"title": "third"}, str(uuid.uuid4()))

        page_one = client.get("/v1/conversations", params={"limit": 2})
        assert page_one.status_code == 200
        payload_one = page_one.json()
        assert [item["title"] for item in payload_one["items"]] == ["third", "second"]
        assert isinstance(payload_one["next_cursor"], str)
        assert payload_one["next_cursor"]

        page_two = client.get(
            "/v1/conversations",
            params={"limit": 2, "cursor": payload_one["next_cursor"]},
        )
        assert page_two.status_code == 200
        payload_two = page_two.json()
        assert [item["title"] for item in payload_two["items"]] == ["first"]
        assert payload_two["next_cursor"] is None


def test_get_and_patch_other_users_conversation_return_404_not_403() -> None:
    with api_client(new_user("owner")) as client:
        conversation = create_conversation_request(client, {"title": "private"}, str(uuid.uuid4()))
    conversation_id = conversation["id"]

    with api_client(new_user("intruder")) as client:
        fetched = client.get(f"/v1/conversations/{conversation_id}")
        assert fetched.status_code == 404
        assert fetched.headers["content-type"] == "application/problem+json"
        assert fetched.json()["code"] == "not_found"

        patched = client.patch(
            f"/v1/conversations/{conversation_id}",
            json={"title": "stolen"},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert patched.status_code == 404
        assert patched.json()["code"] == "not_found"


def test_patch_title_archive_and_restore() -> None:
    with api_client(new_user("patch")) as client:
        conversation = create_conversation_request(client, {"title": "before"}, str(uuid.uuid4()))
        conversation_id = conversation["id"]

        renamed = client.patch(
            f"/v1/conversations/{conversation_id}",
            json={"title": "  After  "},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert renamed.status_code == 200
        assert renamed.json()["title"] == "After"

        archived = client.patch(
            f"/v1/conversations/{conversation_id}",
            json={"archived": True},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert archived.status_code == 200
        assert archived.json()["archived_at"] is not None

        default_titles = [item["title"] for item in client.get("/v1/conversations").json()["items"]]
        assert "After" not in default_titles
        archived_titles = [
            item["title"]
            for item in client.get("/v1/conversations", params={"include_archived": True}).json()[
                "items"
            ]
        ]
        assert "After" in archived_titles

        restored = client.patch(
            f"/v1/conversations/{conversation_id}",
            json={"archived": False},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert restored.status_code == 200
        assert restored.json()["archived_at"] is None
        default_titles = [item["title"] for item in client.get("/v1/conversations").json()["items"]]
        assert "After" in default_titles


def test_duplicate_idempotency_key_replays_or_conflicts() -> None:
    with api_client(new_user("idem")) as client:
        key = str(uuid.uuid4())
        first = create_conversation_request(client, {"title": "once"}, key)
        replay = create_conversation_request(client, {"title": "once"}, key)
        assert replay["id"] == first["id"]

        conflict = client.post(
            "/v1/conversations",
            json={"title": "different"},
            headers={"Idempotency-Key": key},
        )
        assert conflict.status_code == 409
        assert conflict.headers["content-type"] == "application/problem+json"
        assert conflict.json()["code"] == "idempotency_key_conflict"


def test_create_defaults_to_new_conversation_title() -> None:
    with api_client(new_user("default")) as client:
        conversation = create_conversation_request(client, {}, str(uuid.uuid4()))
        assert conversation["title"] == "New conversation"
        assert conversation["active_run_id"] is None
        assert conversation["archived_at"] is None


def test_list_limit_out_of_range_rejected() -> None:
    with api_client(new_user("limit")) as client:
        for limit in (0, 101):
            response = client.get("/v1/conversations", params={"limit": limit})
            assert response.status_code == 400
            body = response.json()
            assert body["code"] == "validation_failed"
            assert body["type"] == "https://copilot.local/problems/validation_failed"


def test_missing_or_invalid_idempotency_key_rejected() -> None:
    with api_client(new_user("nokey")) as client:
        missing = client.post("/v1/conversations", json={"title": "x"})
        assert missing.status_code == 400
        assert missing.json()["code"] == "validation_failed"

        invalid = client.post(
            "/v1/conversations",
            json={"title": "x"},
            headers={"Idempotency-Key": "not-a-uuid"},
        )
        assert invalid.status_code == 400
        assert invalid.json()["code"] == "validation_failed"

        conversation = create_conversation_request(client, {"title": "x"}, str(uuid.uuid4()))
        patch_missing = client.patch(f"/v1/conversations/{conversation['id']}", json={"title": "y"})
        assert patch_missing.status_code == 400
        assert patch_missing.json()["code"] == "validation_failed"


def test_patch_requires_at_least_one_valid_field() -> None:
    with api_client(new_user("fields")) as client:
        conversation = create_conversation_request(client, {"title": "x"}, str(uuid.uuid4()))
        conversation_id = conversation["id"]
        cases: list[dict[str, object]] = [
            {},
            {"title": "   "},
            {"title": "x" * 121},
            {"title": 42},
            {"archived": "yes"},
            {"unknown": 1},
        ]
        for body in cases:
            response = client.patch(
                f"/v1/conversations/{conversation_id}",
                json=body,
                headers={"Idempotency-Key": str(uuid.uuid4())},
            )
            assert response.status_code == 400, body
            assert response.json()["code"] == "validation_failed"


def test_patch_idempotency_replay_does_not_reapply() -> None:
    with api_client(new_user("patchidem")) as client:
        conversation = create_conversation_request(client, {"title": "x"}, str(uuid.uuid4()))
        conversation_id = conversation["id"]
        key = str(uuid.uuid4())

        first = client.patch(
            f"/v1/conversations/{conversation_id}",
            json={"title": "once-patched"},
            headers={"Idempotency-Key": key},
        )
        assert first.status_code == 200
        replay = client.patch(
            f"/v1/conversations/{conversation_id}",
            json={"title": "once-patched"},
            headers={"Idempotency-Key": key},
        )
        assert replay.status_code == 200
        assert replay.json() == first.json()

        conflict = client.patch(
            f"/v1/conversations/{conversation_id}",
            json={"title": "other-patch"},
            headers={"Idempotency-Key": key},
        )
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "idempotency_key_conflict"


def test_get_conversation_detail_returns_messages_oldest_first_with_cursor() -> None:
    async def seed(conversation_id: str) -> list[str]:
        engine = create_async_engine(database_url())
        base = datetime.now(UTC)
        ids = [uuid.uuid4() for _ in range(3)]
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO messages (id, conversation_id, role, content, status,"
                        " client_message_id, created_at, updated_at)"
                        " VALUES (:id, :cid, 'user', 'question', 'complete', :cmid, :t, :t)"
                    ),
                    {
                        "id": ids[0],
                        "cid": conversation_id,
                        "cmid": uuid.uuid4(),
                        "t": base,
                    },
                )
                await connection.execute(
                    text(
                        "INSERT INTO messages (id, conversation_id, role, content, status,"
                        " in_reply_to_id, created_at, updated_at)"
                        " VALUES (:id, :cid, 'assistant', 'answer v1', 'complete', :rid, :t, :t)"
                    ),
                    {
                        "id": ids[1],
                        "cid": conversation_id,
                        "rid": ids[0],
                        "t": base.replace(microsecond=base.microsecond + 1),
                    },
                )
                await connection.execute(
                    text(
                        "INSERT INTO messages (id, conversation_id, role, content, status,"
                        " in_reply_to_id, version, is_visible, created_at, updated_at)"
                        " VALUES (:id, :cid, 'assistant', 'answer v2 hidden', 'complete', :rid, 2,"
                        " FALSE, :t, :t)"
                    ),
                    {
                        "id": ids[2],
                        "cid": conversation_id,
                        "rid": ids[0],
                        "t": base.replace(microsecond=base.microsecond + 2),
                    },
                )
        finally:
            await engine.dispose()
        return [str(message_id) for message_id in ids]

    with api_client(new_user("detail")) as client:
        conversation = create_conversation_request(client, {"title": "detail"}, str(uuid.uuid4()))
        seeded = asyncio.run(seed(conversation["id"]))

        detail = client.get(f"/v1/conversations/{conversation['id']}", params={"limit": 2})
        assert detail.status_code == 200
        payload = detail.json()
        assert payload["conversation"]["id"] == conversation["id"]
        assert payload["active_run"] is None
        messages = payload["messages"]["items"]
        assert [message["id"] for message in messages] == seeded[:2]
        assert messages[0]["is_visible"] is True
        cursor = payload["messages"]["next_cursor"]
        assert isinstance(cursor, str) and cursor

        second_page = client.get(
            f"/v1/conversations/{conversation['id']}",
            params={"limit": 2, "cursor": cursor},
        )
        assert second_page.status_code == 200
        remaining = second_page.json()["messages"]
        assert [message["id"] for message in remaining["items"]] == seeded[2:]
        assert remaining["items"][0]["is_visible"] is False
        assert remaining["next_cursor"] is None


def test_invalid_cursor_and_path_are_rejected() -> None:
    with api_client(new_user("badinput")) as client:
        conversation = create_conversation_request(client, {"title": "x"}, str(uuid.uuid4()))

        bad_path = client.get("/v1/conversations/not-a-uuid")
        assert bad_path.status_code == 400
        assert bad_path.json()["code"] == "validation_failed"

        bad_cursor = client.get(f"/v1/conversations/{conversation['id']}", params={"cursor": "!!!"})
        assert bad_cursor.status_code == 400
        assert bad_cursor.json()["code"] == "validation_failed"

        bad_list_cursor = client.get("/v1/conversations", params={"cursor": "!!!"})
        assert bad_list_cursor.status_code == 400
        assert bad_list_cursor.json()["code"] == "validation_failed"


def test_message_pagination_index_exists() -> None:
    async def scenario() -> None:
        engine = create_async_engine(database_url())
        try:
            async with engine.connect() as connection:
                rows = (
                    await connection.execute(
                        text("SELECT indexdef FROM pg_indexes WHERE tablename = 'messages'")
                    )
                ).all()
        finally:
            await engine.dispose()
        definitions = [row[0] for row in rows]
        assert any(
            "ix_messages_conversation_created_at_id" in definition for definition in definitions
        ), definitions

    asyncio.run(scenario())


def test_database_failure_on_v1_returns_service_unavailable_problem() -> None:
    settings = Settings(_env_file=None, database_url="postgresql+asyncpg://a:secret@127.0.0.1:1/db")
    app = create_app(settings)
    with TestClient(app, headers={"X-Dev-User": "alice"}) as client:
        response = client.get("/v1/conversations")
    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "service_unavailable"
    assert body["type"] == "https://copilot.local/problems/service_unavailable"
    assert "secret" not in response.text
    assert "127.0.0.1" not in response.text


def test_unexpected_error_returns_internal_error_problem() -> None:
    settings = Settings(_env_file=None, database_url=os.environ["TEST_DATABASE_URL"])
    app = create_app(settings)

    @app.get("/v1/_explode")
    def explode() -> None:
        raise RuntimeError("private detail")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/v1/_explode")
    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "internal_error"
    assert body["type"] == "https://copilot.local/problems/internal_error"
    assert "private detail" not in response.text
