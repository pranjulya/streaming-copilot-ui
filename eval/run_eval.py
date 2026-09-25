"""Offline evaluation runner (Phase 08).

Fake mode is the CI gate: it drives the real HTTP surface with the deterministic
provider and asserts structure, never free-form text. Live mode is manual and
requires XAI_API_KEY plus a running API; it writes a report for comparison.

Reports deliberately contain no prompt or response text: case id, kind, terminal
status, finish reason, content length, pass/fail, and token counts only.
"""

import argparse
import asyncio
import json
import os
import re
import sys
import uuid
from collections.abc import Iterable
from pathlib import Path

API = os.environ.get("EVAL_API", "http://127.0.0.1:8000")
EVAL_SET = Path(__file__).resolve().parent / "set.json"
BASELINE = Path(__file__).resolve().parent / "baseline.json"
DEV_HEADERS = {"X-Dev-User": os.environ.get("EVAL_USER", "eval-runner")}

TERMINAL_EVENTS = ("response.completed", "response.failed", "response.cancelled")


def load_set() -> dict:
    return json.loads(EVAL_SET.read_text())


def case_turns(case: dict) -> list[dict]:
    if case.get("turns"):
        return list(case["turns"])
    return [{"content": case["prompt"]}]


def parse_turn(lines: Iterable[str]) -> tuple[str, str | None, str, dict]:
    """Fold one turn's NDJSON lines into (terminal, finish_reason, content, usage).

    Shared by the offline runner and the CI test so their parsing cannot drift.
    Only the assistant answer is kept; prompt text never enters the result.
    """
    terminal_type = "unknown"
    finish_reason: str | None = None
    content = ""
    usage: dict = {"input_tokens": None, "output_tokens": None}
    for line in lines:
        if not line:
            continue
        event = json.loads(line)
        if event["type"] in TERMINAL_EVENTS:
            terminal_type = event["type"]
            finish_reason = event["data"].get("finish_reason")
            if "usage" in event["data"]:
                usage = event["data"]["usage"]
        if event["type"] == "message.completed":
            content = str(event["data"].get("content", ""))
    return terminal_type, finish_reason, content, usage


def evaluate_case_structure(
    case: dict,
    terminal_type: str,
    finish_reason: str | None,
    content: str,
    mode: str = "fake",
) -> dict:
    expectations = case["expect"]
    passed = (
        terminal_type == "response.completed"
        and finish_reason == expectations.get("finish_reason", "stop")
        and (not expectations.get("non_empty", False) or bool(content.strip()))
    )
    max_chars = expectations.get("max_content_chars")
    if max_chars is not None and len(content) > int(max_chars):
        passed = False
    if mode == "live":
        needles = expectations.get("live_must_contain") or []
        if needles and not all(needle.lower() in content.lower() for needle in needles):
            passed = False
        banned = expectations.get("live_must_not_contain") or []
        if banned and any(token.lower() in content.lower() for token in banned):
            passed = False
        if expectations.get("live_must_refuse"):
            lowered = content.lower()
            refused = any(
                token in lowered
                for token in (
                    "can't",
                    "cannot",
                    "won't",
                    "unable",
                    "not able",
                    "i'm sorry",
                    "i am sorry",
                    "against",
                )
            )
            if not refused:
                passed = False
        if expectations.get("live_must_match") == "markdown_list" and not re.search(
            r"(?m)^\s*[-*]\s+\S", content
        ):
            passed = False
    return {
        "id": case["id"],
        "kind": case["kind"],
        "terminal_event": terminal_type,
        "finish_reason": finish_reason,
        "content_length": len(content),
        "passed": passed,
    }


def attach_baseline(report: dict) -> dict:
    if not BASELINE.exists():
        report["baseline"] = "missing"
        return report
    baseline = json.loads(BASELINE.read_text())
    if not baseline.get("results"):
        report["baseline"] = "unrecorded"
        return report
    previous = {item["id"]: item.get("passed") for item in baseline["results"]}
    report["baseline"] = "compared"
    report["baseline_regressions"] = [
        item["id"]
        for item in report["results"]
        if previous.get(item["id"]) is True and item["passed"] is False
    ]
    return report


async def run_against_api() -> dict:
    import httpx

    mode = os.environ.get("EVAL_MODE", "fake")
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
            usage = {"input_tokens": None, "output_tokens": None}
            for turn in case_turns(case):
                async with client.stream(
                    "POST",
                    f"/v1/conversations/{conversation_id}/responses",
                    json={
                        "client_message_id": str(uuid.uuid4()),
                        "content": turn["content"],
                    },
                    headers={**DEV_HEADERS, "Idempotency-Key": str(uuid.uuid4())},
                ) as response:
                    response.raise_for_status()
                    lines = [line async for line in response.aiter_lines()]
                terminal_type, finish_reason, content, usage = parse_turn(lines)
            scored = evaluate_case_structure(
                case, terminal_type, finish_reason, content, mode=mode
            )
            scored["input_tokens"] = usage.get("input_tokens")
            scored["output_tokens"] = usage.get("output_tokens")
            results.append(scored)
    report = {
        "set_version": load_set()["version"],
        "mode": mode,
        "results": results,
        "passed": all(item["passed"] for item in results),
    }
    return attach_baseline(report)


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
    if report.get("baseline_regressions"):
        return 1
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
