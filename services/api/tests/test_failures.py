"""The failure catalog and the published contract must stay in step.

`app/chat/failures.py` is the single definition for the stream-terminal codes in
`docs/api-and-stream-contracts.md`, and the machine-readable form of that list is
the `response.failed` code enum in `contracts/stream-events.schema.json`. Without
this test a code could be added to one side or dropped from the other, and the
catalog would drift into a list of declarations nothing enforces.
"""

import json
from pathlib import Path

from app.chat.failures import FAILURES, safe_failure

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA = REPO_ROOT / "contracts" / "stream-events.schema.json"


def _documented_terminal_codes() -> list[str]:
    schema = json.loads(SCHEMA.read_text())
    for branch in schema["oneOf"]:
        if branch.get("properties", {}).get("type", {}).get("const") == "response.failed":
            return list(branch["properties"]["data"]["properties"]["code"]["enum"])
    raise AssertionError("contracts/stream-events.schema.json has no response.failed branch")


def test_failure_catalog_matches_the_documented_contract() -> None:
    assert set(FAILURES) == set(_documented_terminal_codes())


def test_every_documented_code_resolves_to_its_own_copy() -> None:
    for code in _documented_terminal_codes():
        assert code in FAILURES, f"{code} is documented but missing from the catalog"
        failure = safe_failure(code)
        assert failure.message == FAILURES[code].message
        assert failure.retryable == FAILURES[code].retryable
