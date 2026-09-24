from collections import Counter
from pathlib import Path

from tests.load.load_stream_mix import assign_kind

HARNESS = Path(__file__).resolve().parent / "load" / "load_stream_mix.py"


def test_assign_kind_uses_seventy_twenty_ten_for_fifty_streams() -> None:
    kinds = [assign_kind(index, 50, long_share=0.2, cancel_share=0.1) for index in range(50)]
    counts = Counter(kinds)
    assert counts["complete"] == 35
    assert counts["long"] == 10
    assert counts["cancel"] == 5
    assert counts["complete"] + counts["long"] + counts["cancel"] == 50


def test_assign_kind_applies_long_share_not_only_cancel() -> None:
    kinds = [assign_kind(index, 10, long_share=0.2, cancel_share=0.1) for index in range(10)]
    assert "long" in kinds
    assert kinds.count("long") == 2
    assert kinds.count("cancel") == 1


def test_load_harness_reconnects_from_observed_sequence() -> None:
    source = HARNESS.read_text()
    assert '{"after_sequence": last_sequence}' in source


def test_load_harness_records_peak_in_flight_and_labels_rss_as_harness() -> None:
    source = HARNESS.read_text()
    assert "peak_in_flight" in source
    assert '"rss_source": "harness_process"' in source
    assert 'kinds.count("complete")' in source
