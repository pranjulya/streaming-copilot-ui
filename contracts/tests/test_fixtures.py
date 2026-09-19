"""Freeze producer contracts; future event handling belongs to consumer tests."""

import copy
import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import validate

CONTRACTS = Path(__file__).resolve().parents[1]
EVENT_TYPES = {
    "response.started",
    "message.delta",
    "usage.updated",
    "heartbeat",
    "message.completed",
    "response.completed",
    "response.cancelled",
    "response.failed",
    "response.snapshot",
}


@pytest.fixture
def validator():
    schema = json.loads((CONTRACTS / "stream-events.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def examples():
    return [
        json.loads(path.read_text())
        for path in sorted((CONTRACTS / "examples").glob("*.json"))
    ]


def test_all_v1_examples_validate_and_roundtrip_as_one_ndjson_line(validator):
    events = examples()
    assert len(events) == 9
    assert {event["type"] for event in events} == EVENT_TYPES
    for event in events:
        validator.validate(event)
        assert event["protocol_version"] == "1.0"
        encoded = json.dumps(event, ensure_ascii=False) + "\n"
        assert len(encoded.splitlines()) == 1
        assert json.loads(encoded) == event
        if event["type"] in {"heartbeat", "response.snapshot"}:
            assert event["sequence"] == event["data"]["last_sequence"]
    assert any("👍" in str(event["data"]) for event in events)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_envelope",
        "bad_uuid",
        "bad_time",
        "bad_major",
        "unknown_type",
        "negative_sequence",
        "wrong_data",
        "zero_persisted_sequence",
    ],
)
def test_invalid_envelopes_are_rejected(validator, mutation):
    event = json.loads((CONTRACTS / "examples/message.delta.json").read_text())
    if mutation == "missing_envelope":
        del event["run_id"]
    elif mutation == "bad_uuid":
        event["run_id"] = "not-a-uuid"
    elif mutation == "bad_time":
        event["occurred_at"] = "yesterday"
    elif mutation == "bad_major":
        event["protocol_version"] = "2.0"
    elif mutation == "unknown_type":
        event["type"] = "tool.started"
    elif mutation == "negative_sequence":
        event["sequence"] = -1
    elif mutation == "zero_persisted_sequence":
        event["sequence"] = 0
    else:
        event["data"] = {"last_sequence": 0}
    assert not validator.is_valid(event)


@pytest.mark.parametrize(
    "event_type,field,bad_value",
    [
        ("response.started", "attempt", 0),
        ("message.delta", "content_index", -1),
        ("usage.updated", "output_tokens", -1),
        ("message.completed", "finish_reason", "cancelled"),
        ("response.completed", "finish_reason", "error"),
        ("response.cancelled", "reason", "timeout"),
        ("response.failed", "code", "internal_stacktrace"),
        ("response.snapshot", "status", "unknown"),
        ("heartbeat", "last_sequence", -1),
    ],
)
def test_event_payload_rules(validator, event_type, field, bad_value):
    event = json.loads((CONTRACTS / f"examples/{event_type}.json").read_text())
    invalid = copy.deepcopy(event)
    invalid["data"][field] = bad_value
    assert not validator.is_valid(invalid)
    del event["data"][field]
    assert not validator.is_valid(event)


def test_openapi_snapshot_has_every_operation_and_problem_responses():
    document = yaml.safe_load((CONTRACTS / "openapi.yaml").read_text())
    validate(document)
    expected = {
        ("/v1/conversations", "post"),
        ("/v1/conversations", "get"),
        ("/v1/conversations/{id}", "get"),
        ("/v1/conversations/{id}", "patch"),
        ("/v1/conversations/{id}/responses", "post"),
        ("/v1/response-runs/{id}/stream", "post"),
        ("/v1/response-runs/{id}", "get"),
        ("/v1/response-runs/{id}/cancel", "post"),
        ("/v1/response-runs/{id}/retry", "post"),
        ("/v1/messages/{user_message_id}/regenerations", "post"),
        ("/health/live", "get"),
        ("/health/ready", "get"),
    }
    actual = {
        (path, method)
        for path, entry in document["paths"].items()
        for method in entry
        if method in {"get", "post", "patch"}
    }
    assert actual == expected
    for path, method in expected:
        operation = document["paths"][path][method]
        assert (
            "application/problem+json" in operation["responses"]["default"]["content"]
        )
        if path.startswith("/v1"):
            assert operation.get("security", document.get("security"))
