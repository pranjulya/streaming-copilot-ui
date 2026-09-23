import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from tests.support import database_url, new_user, seed_conversation, seed_messages, session_factory
from tests.test_conversations import api_client
from tests.test_retry_regenerate import actor_for, writer_factory

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL for real Postgres"
)

SNAPSHOT_KEYS = {
    "id",
    "conversation_id",
    "user_message_id",
    "assistant_message_id",
    "status",
    "attempt",
    "last_sequence",
    "cancel_requested_at",
    "error_code",
    "diagnostic_id",
    "partial_content",
    "created_at",
    "completed_at",
}


async def seed_live_run(
    user: str, *, status: str = "queued"
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    from tests.support import seed_run

    factory = session_factory()
    async with factory() as session:
        async with session.begin():
            conversation_id = await seed_conversation(session, user)
            user_message_id, assistant_message_id = await seed_messages(session, conversation_id)
            run_id = await seed_run(
                session,
                conversation_id,
                user,
                user_message_id,
                assistant_message_id,
                status=status,
                owner_instance_id=uuid.uuid4(),
                lease_expires_at=datetime.now(UTC) + timedelta(minutes=10),
            )
    return run_id, conversation_id, user_message_id, assistant_message_id


def test_get_run_returns_snapshot_and_cross_user_is_404() -> None:
    async def scenario() -> None:
        user = new_user("getsnap")
        with api_client(user) as client:
            run_id, conversation_id, user_message_id, assistant_message_id = await seed_live_run(
                user, status="streaming"
            )
            response = client.get(f"/v1/response-runs/{run_id}")
            assert response.status_code == 200
            body = response.json()
            assert set(body) == SNAPSHOT_KEYS
            assert body["id"] == str(run_id)
            assert body["conversation_id"] == str(conversation_id)
            assert body["user_message_id"] == str(user_message_id)
            assert body["assistant_message_id"] == str(assistant_message_id)
            assert body["status"] == "streaming"
            assert body["attempt"] == 1
            assert body["last_sequence"] == 0
            assert body["cancel_requested_at"] is None
            assert body["error_code"] is None
            assert body["diagnostic_id"] is None
            assert body["partial_content"] == ""
            assert body["created_at"]
            assert body["completed_at"] is None

            missing = client.get(f"/v1/response-runs/{uuid.uuid4()}")
            assert missing.status_code == 404
            assert missing.json()["code"] == "not_found"

        with api_client(new_user("snapintruder")) as client:
            foreign = client.get(f"/v1/response-runs/{run_id}")
            assert foreign.status_code == 404
            assert foreign.headers["content-type"] == "application/problem+json"
            assert foreign.json()["code"] == "not_found"

    asyncio.run(scenario())


def test_cancel_sets_flag_is_idempotent_and_terminal_is_noop() -> None:
    from app.chat.event_writer import CompletionResult, complete_run, start_run

    async def scenario() -> None:
        user = new_user("cancelhttp")
        with api_client(user) as client:
            run_id, *_ = await seed_live_run(user, status="queued")
            first = client.post(f"/v1/response-runs/{run_id}/cancel", json={})
            assert first.status_code == 200
            body = first.json()
            assert body["cancel_requested_at"] is not None
            assert body["status"] == "queued"

            second = client.post(f"/v1/response-runs/{run_id}/cancel", json={})
            assert second.status_code == 200
            assert second.json()["cancel_requested_at"] == body["cancel_requested_at"]

            completed_run, *_ = await seed_live_run(user, status="queued")
            factory = writer_factory()
            async with factory() as session:
                await start_run(completed_run, session=session)
            async with factory() as session:
                await complete_run(
                    completed_run,
                    CompletionResult(content="done", finish_reason="stop"),
                    session=session,
                )
            noop = client.post(f"/v1/response-runs/{completed_run}/cancel", json={})
            assert noop.status_code == 200
            noop_body = noop.json()
            assert noop_body["status"] == "completed"
            assert noop_body["cancel_requested_at"] is None
            assert noop_body["partial_content"] == "done"

            missing = client.post(f"/v1/response-runs/{uuid.uuid4()}/cancel", json={})
            assert missing.status_code == 404

    asyncio.run(scenario())


def test_conversation_detail_includes_hidden_messages_and_active_run() -> None:
    from app.chat.event_writer import SafeFailure, fail_run, start_run
    from app.chat.responses import CreateResponse, create_response, retry_run
    from app.settings import Settings

    async def scenario() -> None:
        user = new_user("detailruns")
        settings = Settings(_env_file=None, database_url=database_url())
        with api_client(user) as client:
            created = client.post(
                "/v1/conversations", json={}, headers={"Idempotency-Key": str(uuid.uuid4())}
            )
            assert created.status_code == 201
            conversation_id = created.json()["id"]
            client_message_id = uuid.uuid4()

            factory = writer_factory()
            async with factory() as session:
                first_run = await create_response(
                    CreateResponse(
                        conversation_id=uuid.UUID(conversation_id),
                        client_message_id=client_message_id,
                        content="First question",
                        idempotency_key=uuid.uuid4(),
                        request_hash="h1",
                    ),
                    actor_for(user),
                    session=session,
                    settings=settings,
                )
            async with factory() as session:
                await start_run(first_run.id, session=session)
            async with factory() as session:
                await fail_run(
                    first_run.id,
                    SafeFailure(code="provider_unavailable", message="down"),
                    session=session,
                )
            async with factory() as session:
                second_run = await retry_run(
                    first_run.id, actor_for(user), session=session, settings=settings
                )

            detail = client.get(f"/v1/conversations/{conversation_id}")
            assert detail.status_code == 200
            payload = detail.json()
            assert payload["conversation"]["active_run_id"] == str(second_run.id)
            assert payload["active_run"]["id"] == str(second_run.id)
            assert payload["active_run"]["status"] == "queued"
            assert payload["active_run"]["partial_content"] == ""
            assert payload["active_run"]["attempt"] == 2

            messages = payload["messages"]["items"]
            assert [message["role"] for message in messages] == [
                "user",
                "assistant",
                "assistant",
            ]
            assert [message["is_visible"] for message in messages] == [True, False, True]
            assert payload["messages"]["next_cursor"] is None

            listed = client.get("/v1/conversations").json()["items"]
            match = [item for item in listed if item["id"] == conversation_id]
            assert match and match[0]["active_run_id"] == str(second_run.id)

    asyncio.run(scenario())
