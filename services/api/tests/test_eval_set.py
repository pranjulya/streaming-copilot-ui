import asyncio
import importlib.util
import json
import os
import uuid
from pathlib import Path

import pytest

from tests.support import database_url, new_user

_RUN_EVAL_PATH = Path(__file__).resolve().parents[3] / "eval" / "run_eval.py"
_RUN_EVAL_SPEC = importlib.util.spec_from_file_location("run_eval", _RUN_EVAL_PATH)
assert _RUN_EVAL_SPEC and _RUN_EVAL_SPEC.loader
run_eval = importlib.util.module_from_spec(_RUN_EVAL_SPEC)
_RUN_EVAL_SPEC.loader.exec_module(run_eval)

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL for real Postgres"
)

EVAL_SET = Path(__file__).resolve().parents[3] / "eval" / "set.json"


def _case_text(case: dict) -> str:
    if "turns" in case:
        return " ".join(str(turn.get("content", "")) for turn in case["turns"])
    return str(case.get("prompt", ""))


def test_eval_set_is_versioned_and_valid() -> None:
    data = json.loads(EVAL_SET.read_text())
    assert data["version"]
    assert "never asserts exact free-form equality" in data["policy"]
    kinds = {case["kind"] for case in data["cases"]}
    assert kinds == {"context", "safety", "format", "limits", "instruction", "domain"}
    for case in data["cases"]:
        assert case["id"]
        assert "prompt" in case or ("turns" in case and case["turns"])
        assert set(case["expect"]) >= {"finish_reason", "non_empty"}
        # The set ships in the repository: no secrets and no user data.
        lowered = json.dumps(case).lower()
        for forbidden in ("api_key", "xai-", "bearer", "password"):
            assert forbidden not in lowered


def test_eval_set_context_retention_is_multi_turn() -> None:
    data = json.loads(EVAL_SET.read_text())
    case = next(item for item in data["cases"] if item["kind"] == "context")
    assert len(case.get("turns") or []) >= 2
    assert "ORCHID" in _case_text(case)


def test_eval_set_refusal_asks_for_disallowed_assistance() -> None:
    data = json.loads(EVAL_SET.read_text())
    case = next(item for item in data["cases"] if item["kind"] == "safety")
    text = _case_text(case).lower()
    assert "unethical" not in text
    assert case["expect"].get("live_must_refuse") is True


def test_eval_set_markdown_and_truncation_can_fail() -> None:
    data = json.loads(EVAL_SET.read_text())
    markdown = next(item for item in data["cases"] if item["kind"] == "format")
    truncation = next(item for item in data["cases"] if item["kind"] == "limits")
    assert markdown["expect"].get("live_must_match") == "markdown_list"
    assert truncation["expect"].get("max_content_chars") == 100000


def test_eval_set_contains_no_prompt_echo_expectations() -> None:
    data = json.loads(EVAL_SET.read_text())
    for case in data["cases"]:
        assert "equals" not in case["expect"], "CI must assert structure, not exact text"


def test_eval_baseline_omits_prompt_and_response_text() -> None:
    baseline_path = EVAL_SET.parent / "baseline.json"
    data = json.loads(baseline_path.read_text())
    assert data["set_version"]
    assert data["mode"] == "live"
    blob = json.dumps(data).lower()
    for forbidden in ("prompt", "response", "orchid", "api_key"):
        assert forbidden not in blob
    for result in data.get("results", []):
        assert "content" not in result
        assert set(result) <= {
            "id",
            "kind",
            "passed",
            "finish_reason",
            "terminal_event",
            "content_length",
            "input_tokens",
            "output_tokens",
            "latency_ms",
        }


def test_evaluate_case_structure_fails_when_content_exceeds_cap() -> None:
    case = {
        "id": "truncation-limit",
        "kind": "limits",
        "expect": {"finish_reason": "stop", "non_empty": True, "max_content_chars": 8},
    }
    over = run_eval.evaluate_case_structure(case, "response.completed", "stop", "x" * 9)
    under = run_eval.evaluate_case_structure(case, "response.completed", "stop", "short")
    assert over["passed"] is False
    assert under["passed"] is True


def test_evaluate_case_structure_ignores_live_rubric_in_fake_mode() -> None:
    case = {
        "id": "refusal-boundary",
        "kind": "safety",
        "expect": {
            "finish_reason": "stop",
            "non_empty": True,
            "live_must_refuse": True,
            "live_must_contain": ["ORCHID"],
        },
    }
    result = run_eval.evaluate_case_structure(
        case, "response.completed", "stop", "A safe, structural answer.", mode="fake"
    )
    assert result["passed"] is True


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
                    turns = case.get("turns") or [{"content": case["prompt"]}]
                    terminal = "unknown"
                    finish_reason = None
                    content = ""
                    for turn in turns:
                        with client.stream(
                            "POST",
                            f"/v1/conversations/{conversation_id}/responses",
                            json={
                                "client_message_id": str(uuid.uuid4()),
                                "content": turn["content"],
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
                    scored = run_eval.evaluate_case_structure(
                        case, terminal, finish_reason, content, mode="fake"
                    )
                    results.append(scored)
        for scored in results:
            assert scored["passed"], scored["id"]
        # Content never lands in logs, even during evaluation runs.
        assert "A safe, structural answer" not in caplog.text

    asyncio.run(scenario())
