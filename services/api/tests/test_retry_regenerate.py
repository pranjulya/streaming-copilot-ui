import asyncio
import os
import uuid

import pytest
from sqlalchemy import text

from tests.support import (
    build_settings,
    database_url,
    new_user,
    seed_conversation,
    seed_run,
    session_factory,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL for real Postgres"
)


async def seed_turn(
    *,
    title: str = "New conversation",
    run_status: str = "queued",
    archived: bool = False,
    prefix: str = "turn",
) -> tuple[str, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    factory = session_factory()
    user = new_user(prefix)
    async with factory() as session:
        async with session.begin():
            conversation_id = await seed_conversation(session, user, title=title)
            if archived:
                await session.execute(
                    text("UPDATE conversations SET archived_at = now() WHERE id = :id"),
                    {"id": conversation_id},
                )
            from tests.support import seed_messages

            user_message_id, assistant_message_id = await seed_messages(session, conversation_id)
            run_id = await seed_run(
                session,
                conversation_id,
                user,
                user_message_id,
                assistant_message_id,
                status=run_status,
            )
    return user, conversation_id, user_message_id, assistant_message_id, run_id


def actor_for(user: str):
    from app.api.auth import Actor

    return Actor(user_id=user)


async def seed_plain_conversation(
    *, title: str = "New conversation", prefix: str = "plain"
) -> tuple[str, uuid.UUID]:
    factory = session_factory()
    user = new_user(prefix)
    async with factory() as session:
        async with session.begin():
            conversation_id = await seed_conversation(session, user, title=title)
    return user, conversation_id


def create_cmd(
    conversation_id: uuid.UUID,
    *,
    content: str = "Hello there",
    client_message_id: uuid.UUID | None = None,
    key: uuid.UUID | None = None,
    request_hash: str = "hash-one",
):
    from app.chat.responses import CreateResponse

    return CreateResponse(
        conversation_id=conversation_id,
        client_message_id=client_message_id if client_message_id else uuid.uuid4(),
        content=content,
        idempotency_key=key if key else uuid.uuid4(),
        request_hash=request_hash,
    )


async def create_turn(user: str, cmd) -> object:
    from app.chat.responses import create_response

    factory = session_factory()
    async with factory() as session:
        return await create_response(
            cmd, actor_for(user), session=session, settings=build_settings()
        )


async def run_row(run_id: uuid.UUID) -> dict[str, object]:
    factory = session_factory()
    async with factory() as session:
        result = (
            await session.execute(
                text(
                    "SELECT status, attempt, owner_instance_id, lease_expires_at, user_id,"
                    " assistant_message_id, user_message_id FROM response_runs WHERE id = :id"
                ),
                {"id": run_id},
            )
        ).one()
    return dict(result._mapping)


async def conversation_title(conversation_id: uuid.UUID) -> str:
    factory = session_factory()
    async with factory() as session:
        result = await session.execute(
            text("SELECT title FROM conversations WHERE id = :id"), {"id": conversation_id}
        )
        return str(result.scalar_one())


async def visible_assistants(user_message_id: uuid.UUID) -> list[tuple]:
    factory = session_factory()
    async with factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id, version, is_visible, status FROM messages"
                    " WHERE in_reply_to_id = :id ORDER BY version"
                ),
                {"id": user_message_id},
            )
        ).all()
    return [tuple(row) for row in rows]


def test_create_response_builds_turn_and_retitles_first_message() -> None:
    async def scenario() -> None:
        user, conversation_id = await seed_plain_conversation(title="New conversation")
        content = "Explain backpressure in streaming APIs"
        cmd = create_cmd(conversation_id, content=content)
        run = await create_turn(user, cmd)  # type: ignore[arg-type]
        row = await run_row(run.id)  # type: ignore[attr-defined]
        assert row["status"] == "queued"
        assert row["attempt"] == 1
        assert row["owner_instance_id"] is not None
        assert row["lease_expires_at"] is not None
        assert (await conversation_title(conversation_id)) == content[:80]
        assistants = await visible_assistants(row["user_message_id"])  # type: ignore[arg-type]
        assert len(assistants) == 1
        assert assistants[0][2] is True

    asyncio.run(scenario())


def test_create_response_keeps_renamed_title() -> None:
    async def scenario() -> None:
        user, conversation_id = await seed_plain_conversation(title="Renamed by user")
        await create_turn(user, create_cmd(conversation_id))  # type: ignore[arg-type]
        assert (await conversation_title(conversation_id)) == "Renamed by user"

    asyncio.run(scenario())


def test_create_response_rejects_blank_and_oversized_content() -> None:
    from app.api.errors import AppError

    async def scenario() -> None:
        user, conversation_id = await seed_plain_conversation()
        for content in ("   ", "x" * 8001):
            with pytest.raises(AppError) as caught:
                await create_turn(user, create_cmd(conversation_id, content=content))  # type: ignore[arg-type]
            assert caught.value.code == "validation_failed"
            assert caught.value.status_code == 400

    asyncio.run(scenario())


def test_create_response_idempotent_replay_and_conflict() -> None:
    from app.api.errors import AppError

    async def scenario() -> None:
        user, conversation_id = await seed_plain_conversation()
        key = uuid.uuid4()
        first = await create_turn(  # type: ignore[arg-type]
            user, create_cmd(conversation_id, key=key, request_hash="same")
        )
        replay = await create_turn(  # type: ignore[arg-type]
            user, create_cmd(conversation_id, key=key, request_hash="same")
        )
        assert replay.id == first.id  # type: ignore[attr-defined]
        with pytest.raises(AppError) as caught:
            await create_turn(  # type: ignore[arg-type]
                user, create_cmd(conversation_id, key=key, request_hash="different")
            )
        assert caught.value.code == "idempotency_key_conflict"

    asyncio.run(scenario())


def test_second_create_with_new_key_is_conversation_busy() -> None:
    from app.api.errors import AppError

    async def scenario() -> None:
        user, conversation_id = await seed_plain_conversation()
        await create_turn(user, create_cmd(conversation_id))  # type: ignore[arg-type]
        with pytest.raises(AppError) as caught:
            await create_turn(user, create_cmd(conversation_id))  # type: ignore[arg-type]
        assert caught.value.code == "conversation_busy"
        assert caught.value.status_code == 409
        assert "conversation_id" in caught.value.extensions
        assert "active_run_id" in caught.value.extensions

    asyncio.run(scenario())


def test_duplicate_client_message_id_replays_while_run_is_active() -> None:
    async def scenario() -> None:
        user, conversation_id = await seed_plain_conversation(prefix="dup-cmid")
        client_message_id = uuid.uuid4()
        first = await create_turn(  # type: ignore[arg-type]
            user, create_cmd(conversation_id, client_message_id=client_message_id)
        )
        replay = await create_turn(  # type: ignore[arg-type]
            user,
            create_cmd(
                conversation_id,
                client_message_id=client_message_id,
                key=uuid.uuid4(),
                request_hash="hash-two",
            ),
        )
        assert replay.id == first.id  # type: ignore[attr-defined]

    asyncio.run(scenario())


def test_create_response_enforces_per_user_cap() -> None:
    from app.api.errors import AppError

    async def scenario() -> None:
        user = new_user("cap-create")
        factory = session_factory()
        active_conversations = []
        async with factory() as session:
            async with session.begin():
                for _ in range(3):
                    conversation_id = await seed_conversation(session, user)
                    from tests.support import seed_messages

                    umid, amid = await seed_messages(session, conversation_id)
                    await seed_run(session, conversation_id, user, umid, amid)
                    active_conversations.append(conversation_id)
        spare_conversation = active_conversations[0]
        del spare_conversation
        factory2 = session_factory()
        async with factory2() as session:
            async with session.begin():
                free_conversation_id = await seed_conversation(session, user)
        with pytest.raises(AppError) as caught:
            await create_turn(user, create_cmd(free_conversation_id))  # type: ignore[arg-type]
        assert caught.value.code == "too_many_active_runs"
        assert caught.value.status_code == 409

    asyncio.run(scenario())


def test_retry_from_failed_creates_new_version_with_lease() -> None:
    from app.chat.responses import retry_run

    async def scenario() -> None:
        user, _, user_message_id, _, source_run_id = await seed_turn(run_status="failed")
        settings = build_settings()
        factory = session_factory()
        async with factory() as session:
            new_run = await retry_run(
                source_run_id, actor_for(user), session=session, settings=settings
            )
        row = await run_row(new_run.id)
        assert row["status"] == "queued"
        assert row["attempt"] == 2
        assert row["user_message_id"] == user_message_id
        assert row["owner_instance_id"] is not None
        assert row["lease_expires_at"] is not None
        assistants = await visible_assistants(user_message_id)
        assert len(assistants) == 2
        assert assistants[0][2] is False
        assert assistants[1][1] == 2
        assert assistants[1][2] is True

    asyncio.run(scenario())


def test_retry_respects_per_user_cap() -> None:
    from app.api.errors import AppError
    from app.chat.responses import retry_run

    async def scenario() -> None:
        user = new_user("cap-retry")
        factory = session_factory()
        async with factory() as session:
            async with session.begin():
                for _ in range(3):
                    conversation_id = await seed_conversation(session, user)
                    from tests.support import seed_messages

                    umid, amid = await seed_messages(session, conversation_id)
                    await seed_run(session, conversation_id, user, umid, amid)
                source_conversation = await seed_conversation(session, user)
                from tests.support import seed_messages

                umid, amid = await seed_messages(session, source_conversation)
                source_run = await seed_run(
                    session, source_conversation, user, umid, amid, status="failed"
                )
        with pytest.raises(AppError) as caught:
            async with session_factory()() as session:
                await retry_run(
                    source_run, actor_for(user), session=session, settings=build_settings()
                )
        assert caught.value.code == "too_many_active_runs"

    asyncio.run(scenario())


def test_retry_and_regenerate_reject_archived_conversation() -> None:
    from app.api.errors import AppError
    from app.chat.responses import regenerate_message, retry_run

    async def scenario() -> None:
        user, conversation_id, user_message_id, _, source_run_id = await seed_turn(
            run_status="failed", archived=True
        )
        with pytest.raises(AppError) as caught:
            async with session_factory()() as session:
                await retry_run(
                    source_run_id, actor_for(user), session=session, settings=build_settings()
                )
        assert caught.value.code == "conversation_archived"

        user2, conversation2, user_message2, _, _ = await seed_turn(
            run_status="failed", archived=True, prefix="arch-regen"
        )
        del conversation_id, conversation2
        with pytest.raises(AppError) as caught:
            async with session_factory()() as session:
                await regenerate_message(
                    user_message2, actor_for(user2), session=session, settings=build_settings()
                )
        assert caught.value.code == "conversation_archived"
        del user_message_id

    asyncio.run(scenario())


def test_retry_from_completed_or_streaming_rejected() -> None:
    from app.api.errors import AppError
    from app.chat.responses import retry_run

    async def scenario() -> None:
        for status in ("completed", "streaming"):
            user, _, _, _, run_id = await seed_turn(run_status=status, prefix=f"retry-{status}")
            with pytest.raises(AppError) as caught:
                async with session_factory()() as session:
                    await retry_run(
                        run_id, actor_for(user), session=session, settings=build_settings()
                    )
            assert caught.value.code == "invalid_run_state"

    asyncio.run(scenario())


def test_regenerate_while_active_is_busy() -> None:
    from app.api.errors import AppError
    from app.chat.responses import regenerate_message

    async def scenario() -> None:
        user, _, user_message_id, _, active_run_id = await seed_turn(run_status="streaming")
        with pytest.raises(AppError) as caught:
            async with session_factory()() as session:
                await regenerate_message(
                    user_message_id, actor_for(user), session=session, settings=build_settings()
                )
        assert caught.value.code == "conversation_busy"
        assert caught.value.extensions["active_run_id"] == str(active_run_id)

    asyncio.run(scenario())


def test_regenerate_from_completed_hides_previous_answer() -> None:
    from app.chat.responses import regenerate_message

    async def scenario() -> None:
        user, _, user_message_id, _, _ = await seed_turn(run_status="completed")
        factory = session_factory()
        async with factory() as session:
            new_run = await regenerate_message(
                user_message_id, actor_for(user), session=session, settings=build_settings()
            )
        row = await run_row(new_run.id)
        assert row["status"] == "queued"
        assert row["attempt"] == 1
        assistants = await visible_assistants(user_message_id)
        assert len(assistants) == 2
        assert assistants[0][2] is False
        assert assistants[1][1] == 2
        assert assistants[1][2] is True

    asyncio.run(scenario())


def test_regenerate_replays_same_key_while_new_run_is_queued() -> None:
    from app.chat.responses import regenerate_message

    async def scenario() -> None:
        user, _, user_message_id, _, _ = await seed_turn(
            run_status="completed", prefix="regen-replay"
        )
        key = uuid.uuid4()
        factory = session_factory()
        async with factory() as session:
            first = await regenerate_message(
                user_message_id,
                actor_for(user),
                session=session,
                settings=build_settings(),
                idempotency_key=key,
                request_hash="regen-same",
            )
        async with factory() as session:
            replay = await regenerate_message(
                user_message_id,
                actor_for(user),
                session=session,
                settings=build_settings(),
                idempotency_key=key,
                request_hash="regen-same",
            )
        assert replay.id == first.id
        assistants = await visible_assistants(user_message_id)
        assert len(assistants) == 2

    asyncio.run(scenario())


def test_expired_idempotency_key_still_replays_active_run() -> None:
    async def scenario() -> None:
        user, conversation_id = await seed_plain_conversation(prefix="ttl-active")
        key = uuid.uuid4()
        first = await create_turn(  # type: ignore[arg-type]
            user, create_cmd(conversation_id, key=key, request_hash="same")
        )
        factory = session_factory()
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        "UPDATE idempotency_records SET expires_at = now() - interval '1 hour'"
                        " WHERE key = :key"
                    ),
                    {"key": key},
                )
        replay = await create_turn(  # type: ignore[arg-type]
            user, create_cmd(conversation_id, key=key, request_hash="same")
        )
        assert replay.id == first.id  # type: ignore[attr-defined]

    asyncio.run(scenario())


def test_create_turn_locks_conversation_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy import text as sql_text
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.chat import responses as responses_mod

    async def scenario() -> None:
        user, conversation_id = await seed_plain_conversation(prefix="row-lock")
        original = responses_mod._owned_conversation
        locked = asyncio.Event()
        release = asyncio.Event()

        async def hold_row(session: object, conversation_id: uuid.UUID, user_id: str) -> object:
            conversation = await original(session, conversation_id, user_id)  # type: ignore[arg-type]
            locked.set()
            await release.wait()
            return conversation

        monkeypatch.setattr(responses_mod, "_owned_conversation", hold_row)

        async def probe_lock() -> None:
            await locked.wait()
            engine = create_async_engine(database_url())
            try:
                async with engine.connect() as connection:
                    with pytest.raises(DBAPIError) as caught:
                        await connection.execute(
                            sql_text(
                                "SELECT id FROM conversations WHERE id = :id FOR UPDATE NOWAIT"
                            ),
                            {"id": conversation_id},
                        )
                    assert caught.value.orig.sqlstate == "55P03"  # type: ignore[union-attr]
            finally:
                release.set()
                await engine.dispose()

        await asyncio.gather(
            create_turn(user, create_cmd(conversation_id)),  # type: ignore[arg-type]
            probe_lock(),
        )

    asyncio.run(scenario())


def test_failed_creation_rolls_back_and_keeps_previous_answer_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.chat.responses import retry_run

    async def scenario() -> None:
        user, _, user_message_id, _, source_run_id = await seed_turn(run_status="failed")
        before = await visible_assistants(user_message_id)
        assert len(before) == 1
        assert before[0][2] is True

        def boom(*args: object, **kwargs: object) -> None:
            raise RuntimeError("insert failed")

        monkeypatch.setattr("app.chat.responses._queued_run", boom)
        with pytest.raises(RuntimeError, match="insert failed"):
            async with session_factory()() as session:
                await retry_run(
                    source_run_id, actor_for(user), session=session, settings=build_settings()
                )

        after = await visible_assistants(user_message_id)
        assert after == before
        runs = await run_row(source_run_id)
        assert runs["status"] == "failed"

    asyncio.run(scenario())
