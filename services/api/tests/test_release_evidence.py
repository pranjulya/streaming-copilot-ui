"""Honesty guards for the Phase 08 release evidence.

These read the evidence documents as text, so they need no database.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DASHBOARDS = REPO_ROOT / "docs" / "operations" / "dashboards.md"
OBSERVABILITY = REPO_ROOT / "docs" / "observability.md"
CHECKLIST = REPO_ROOT / "docs" / "operations" / "release-checklist.md"

# Prometheus generates `up` for every configured scrape target; it is not a
# series this project declares or exports.
PROMETHEUS_BUILTINS = {"up"}

# A series name sits immediately before a selector or a range, e.g.
# `copilot_http_requests_total{...}` or `copilot_cancel_ack_seconds[5m]`.
SERIES = re.compile(r"\b([a-z][a-z0-9_]*?)(?:_bucket)?(?=[\{\[])")
TABLE_ROW = re.compile(r"^\| `(copilot_[a-z0-9_]+)` \|")


def declared_series() -> set[str]:
    return {
        match.group(1)
        for match in (TABLE_ROW.match(line) for line in OBSERVABILITY.read_text().splitlines())
        if match
    }


def queried_series() -> set[str]:
    blocks = re.findall(r"```promql\n(.*?)```", DASHBOARDS.read_text(), flags=re.DOTALL)
    return {name for block in blocks for name in SERIES.findall(block)}


def test_dashboards_only_query_declared_or_builtin_series() -> None:
    declared = declared_series()
    assert declared, "docs/observability.md must list the canonical metric names"
    invented = queried_series() - declared - PROMETHEUS_BUILTINS
    assert not invented, f"dashboards query series that are not declared: {sorted(invented)}"


def test_release_checklist_leaves_unproven_and_human_gates_unticked() -> None:
    text = CHECKLIST.read_text()
    for gate in (
        "- [ ] **Named owner approval**",
        "- [ ] Load report",
        "- [ ] Calibrated values",
        "- [ ] Schema drift",
    ):
        assert gate in text, f"release gate must stay open until recorded: {gate}"
