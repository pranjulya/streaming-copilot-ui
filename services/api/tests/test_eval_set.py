import asyncio
import json
import os
import uuid
from pathlib import Path

import pytest

from tests.support import database_url, new_user

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL for real Postgres"
)

EVAL_SET = Path(__file__).resolve().parents[3] / "eval" / "set.json"


def test_eval_set_is_versioned_and_valid() -> None:
    data = json.loads(EVAL_SET.read_text())
    assert data["version"]
    assert "never asserts exact free-form equality" in data["policy"]
    kinds = {case["kind"] for case in data["cases"]}
    assert kinds == {"context", "safety", "format", "limits"}
    for case in data["cases"]:
        assert case["id"] and case["prompt"]
        assert set(case["expect"]) >= {"finish_reason", "non_empty"}
        # The set ships in the repository: no secrets and no user data.
        lowered = json.dumps(case).lower()
        for forbidden in ("api_key", "xai-", "bearer", "password"):
            assert forbidden not in lowered


def test_eval_set_contains_no_prompt_echo_expectations() -> None:
    data = json.loads(EVAL_SET.read_text())
    for case in data["cases"]:
        assert "equals" not in case["expect"], "CI must assert structure, not exact text"


def test_fake_mode_evaluation_passes_structurally(caplog) -> None:
    import logging

    from app.chat.event_writer import Usage
    from app.main import create_app
    from app.providers.fake import FakeProvider
    from app.settings import Settings

    async def scenario() -> None:
        settings = Settings(_env_file=None, database_url=database_url(), app_env="development")
        provider = FakeProvider(
            deltas=["A safe, structural answer."], finish_reason="stop", usage=Usage(3, 4)
        )
        app = create_app(settings, provider=provider)
        results = []
        with caplog.at_level(logging.INFO):
            from fastapi.testclient import TestClient

            with TestClient(app, headers={"X-Dev-User": new_user("eval")}) as client:
                for case in json.loads(EVAL_SET.read_text())["cases"]:
                    created = client.post(
                        "/v1/conversations",
                        json={},
                        headers={"Idempotency-Key": str(uuid.uuid4())},
                    )
                    conversation_id = created.json()["id"]
                    terminal = "unknown"
                    finish_reason = None
                    content = ""
                    with client.stream(
                        "POST",
                        f"/v1/conversations/{conversation_id}/responses",
                        json={
                            "client_message_id": str(uuid.uuid4()),
                            "content": case["prompt"],
                        },
                        headers={"Idempotency-Key": str(uuid.uuid4())},
                    ) as response:
                        for line in b"".join(response.iter_bytes()).decode().splitlines():
                            if not line:
                                continue
                            event = json.loads(line)
                            if event["type"].startswith("response.") and event["type"].endswith(
                                ("completed", "failed", "cancelled")
                            ):
                                terminal = event["type"]
                                finish_reason = event["data"].get("finish_reason")
                            if event["type"] == "message.completed":
                                content = str(event["data"].get("content", ""))
                    results.append((case["id"], terminal, finish_reason, content))
        for case_id, terminal, finish_reason, content in results:
            assert terminal == "response.completed", case_id
            assert finish_reason == "stop", case_id
            assert content.strip(), case_id
        # Content never lands in logs, even during evaluation runs.
        assert "A safe, structural answer" not in caplog.text

    asyncio.run(scenario())
