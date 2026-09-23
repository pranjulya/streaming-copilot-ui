"""Offline evaluation runner (Phase 08).

Fake mode is the CI gate: it drives the real HTTP surface with the deterministic
provider and asserts structure, never free-form text. Live mode is manual and
requires XAI_API_KEY plus a running API; it writes a report for comparison.

Reports deliberately contain no prompt or response text: case id, terminal
status, finish reason, and content length only.
"""

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

API = os.environ.get("EVAL_API", "http://127.0.0.1:8000")
EVAL_SET = Path(__file__).resolve().parent / "set.json"
DEV_HEADERS = {"X-Dev-User": os.environ.get("EVAL_USER", "eval-runner")}


def load_set() -> dict:
    return json.loads(EVAL_SET.read_text())


def evaluate_case_structure(
    case: dict, terminal_type: str, finish_reason: str | None, content: str
) -> dict:
    expectations = case["expect"]
    passed = (
        terminal_type == "response.completed"
        and finish_reason == expectations.get("finish_reason", "stop")
        and (not expectations.get("non_empty", False) or bool(content.strip()))
    )
    return {
        "id": case["id"],
        "kind": case["kind"],
        "terminal_event": terminal_type,
        "finish_reason": finish_reason,
        "content_length": len(content),
        "passed": passed,
    }


async def run_against_api() -> dict:
    import httpx

    results = []
    async with httpx.AsyncClient(base_url=API, timeout=httpx.Timeout(120)) as client:
        for case in load_set()["cases"]:
            created = await client.post(
                "/v1/conversations",
                json={},
                headers={**DEV_HEADERS, "Idempotency-Key": str(uuid.uuid4())},
            )
            created.raise_for_status()
            conversation_id = created.json()["id"]
            terminal_type = "unknown"
            finish_reason: str | None = None
            content = ""
            async with client.stream(
                "POST",
                f"/v1/conversations/{conversation_id}/responses",
                json={
                    "client_message_id": str(uuid.uuid4()),
                    "content": case["prompt"],
                },
                headers={**DEV_HEADERS, "Idempotency-Key": str(uuid.uuid4())},
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    event = json.loads(line)
                    if event["type"] in (
                        "response.completed",
                        "response.failed",
                        "response.cancelled",
                    ):
                        terminal_type = event["type"]
                        finish_reason = event["data"].get("finish_reason")
                    if event["type"] == "message.completed":
                        content = str(event["data"].get("content", ""))
            results.append(
                evaluate_case_structure(case, terminal_type, finish_reason, content)
            )
    return {
        "set_version": load_set()["version"],
        "mode": os.environ.get("EVAL_MODE", "fake"),
        "results": results,
        "passed": all(item["passed"] for item in results),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    report = asyncio.run(run_against_api())
    text = json.dumps(report, indent=2)
    if args.out:
        Path(args.out).write_text(text)
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
