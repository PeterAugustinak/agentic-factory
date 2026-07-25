"""Tests for skills/paf-shared/paf-report-cost.py.

Covers the module's pure functions — timestamp parsing, model-id family/version
handling, the same-family price fallback, and `cost_from_transcripts` itself,
which is the piece that decides what a `/paf:` run actually costs. Transcript
fixtures are written to a temporary directory; no real session data is read and
no ledger is touched.
"""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tests.support import REPORT_COST, load_module

cost = load_module(REPORT_COST, "paf_report_cost")

# A minimal stand-in for pricing.json's "models" block. Rates are round numbers so
# expected costs stay checkable by hand.
PRICING = {
    "claude-haiku-4-5": {
        "input": 1.0, "output": 5.0,
        "cache_write_5m": 1.25, "cache_write_1h": 2.0, "cache_read": 0.1,
    },
    "claude-sonnet-5": {
        "input": 3.0, "output": 15.0,
        "cache_write_5m": 3.75, "cache_write_1h": 6.0, "cache_read": 0.3,
    },
    "claude-sonnet-5-1": {
        "input": 4.0, "output": 20.0,
        "cache_write_5m": 5.0, "cache_write_1h": 8.0, "cache_read": 0.4,
    },
    "claude-opus-4-8": {
        "input": 5.0, "output": 25.0,
        "cache_write_5m": 6.25, "cache_write_1h": 10.0, "cache_read": 0.5,
    },
}


def record(timestamp, model, mid=None, **usage):
    """One transcript line, in the shape Claude Code writes."""
    return {
        "timestamp": timestamp,
        "message": {"id": mid, "model": model, "usage": usage},
    }


class ParseTsTests(unittest.TestCase):
    def test_parses_offset_form(self):
        self.assertEqual(
            cost.parse_ts("2026-07-25T10:00:00+00:00"),
            datetime(2026, 7, 25, 10, 0, tzinfo=timezone.utc),
        )

    def test_parses_z_suffix(self):
        self.assertEqual(
            cost.parse_ts("2026-07-25T10:00:00Z"),
            datetime(2026, 7, 25, 10, 0, tzinfo=timezone.utc),
        )

    def test_none_input(self):
        self.assertIsNone(cost.parse_ts(None))

    def test_empty_string(self):
        self.assertIsNone(cost.parse_ts(""))

    def test_garbage_string(self):
        self.assertIsNone(cost.parse_ts("not-a-timestamp"))

    def test_non_string(self):
        self.assertIsNone(cost.parse_ts(12345))


class ModelFamilyTests(unittest.TestCase):
    def test_opus(self):
        self.assertEqual(cost.model_family("claude-opus-4-8"), "opus")

    def test_sonnet(self):
        self.assertEqual(cost.model_family("claude-sonnet-5"), "sonnet")

    def test_haiku_with_date_suffix(self):
        self.assertEqual(cost.model_family("claude-haiku-4-5-20251001"), "haiku")

    def test_unknown_family(self):
        self.assertIsNone(cost.model_family("claude-fable-5"))


class ModelVersionTests(unittest.TestCase):
    def test_single_segment(self):
        self.assertEqual(cost.model_version("claude-sonnet-5"), (5,))

    def test_two_segments(self):
        self.assertEqual(cost.model_version("claude-sonnet-5-1"), (5, 1))

    def test_haiku_four_five(self):
        self.assertEqual(cost.model_version("claude-haiku-4-5"), (4, 5))

    def test_unknown_family_yields_empty_tuple(self):
        self.assertEqual(cost.model_version("claude-fable-5"), ())

    def test_ordering_across_id_shapes(self):
        self.assertLess(cost.model_version("claude-sonnet-5"), cost.model_version("claude-sonnet-5-1"))
        self.assertGreater(cost.model_version("claude-opus-4-8"), cost.model_version("claude-haiku-4-5"))


class LatestPricedInFamilyTests(unittest.TestCase):
    def test_picks_the_highest_version(self):
        self.assertEqual(cost.latest_priced_in_family("sonnet", PRICING), "claude-sonnet-5-1")

    def test_single_candidate(self):
        self.assertEqual(cost.latest_priced_in_family("opus", PRICING), "claude-opus-4-8")

    def test_no_candidate(self):
        self.assertIsNone(cost.latest_priced_in_family("fable", PRICING))


class CostFromTranscriptsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write(self, name, records):
        path = self.dir / name
        with open(path, "w") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")
        return path

    def test_prices_a_single_message(self):
        path = self.write("main.jsonl", [
            record("2026-07-25T10:00:00Z", "claude-sonnet-5", mid="m1",
                   input_tokens=1_000_000, output_tokens=1_000_000),
        ])
        result = cost.cost_from_transcripts([path], PRICING)
        self.assertEqual(result["total_cost_usd"], 18.0)  # 1M * 3 + 1M * 15
        self.assertEqual(result["tokens"]["input"], 1_000_000)
        self.assertEqual(result["tokens"]["output"], 1_000_000)

    def test_deduplicates_by_message_id(self):
        # One assistant turn is written across several lines (thinking, tool_use,
        # ...) with the SAME usage copied onto each — it must be counted once.
        path = self.write("main.jsonl", [
            record("2026-07-25T10:00:00Z", "claude-sonnet-5", mid="m1", input_tokens=1_000_000),
            record("2026-07-25T10:00:01Z", "claude-sonnet-5", mid="m1", input_tokens=1_000_000),
            record("2026-07-25T10:00:02Z", "claude-sonnet-5", mid="m1", input_tokens=1_000_000),
        ])
        result = cost.cost_from_transcripts([path], PRICING)
        self.assertEqual(result["tokens"]["input"], 1_000_000)
        self.assertEqual(result["total_cost_usd"], 3.0)

    def test_sums_across_multiple_transcripts(self):
        # Subagent transcripts live in separate files and typically dominate a run.
        main = self.write("main.jsonl", [
            record("2026-07-25T10:00:00Z", "claude-sonnet-5", mid="m1", input_tokens=1_000_000),
        ])
        sub = self.write("sub.jsonl", [
            record("2026-07-25T10:00:05Z", "claude-haiku-4-5", mid="s1", input_tokens=1_000_000),
        ])
        result = cost.cost_from_transcripts([main, sub], PRICING)
        self.assertEqual(result["tokens"]["input"], 2_000_000)
        self.assertEqual(result["total_cost_usd"], 4.0)  # 3.0 + 1.0

    def test_since_slices_to_the_invocation(self):
        path = self.write("main.jsonl", [
            record("2026-07-25T09:00:00Z", "claude-sonnet-5", mid="before", input_tokens=1_000_000),
            record("2026-07-25T11:00:00Z", "claude-sonnet-5", mid="after", input_tokens=1_000_000),
        ])
        since = cost.parse_ts("2026-07-25T10:00:00Z")
        result = cost.cost_from_transcripts([path], PRICING, since=since)
        self.assertEqual(result["tokens"]["input"], 1_000_000)
        self.assertEqual(result["total_cost_usd"], 3.0)

    def test_since_drops_untimestamped_lines(self):
        # A line that cannot be placed on the timeline is not attributable to this
        # invocation, so slicing excludes it.
        path = self.write("main.jsonl", [
            {"message": {"id": "no-ts", "model": "claude-sonnet-5", "usage": {"input_tokens": 1_000_000}}},
        ])
        since = cost.parse_ts("2026-07-25T10:00:00Z")
        result = cost.cost_from_transcripts([path], PRICING, since=since)
        self.assertEqual(result["tokens"]["input"], 0)

    def test_skips_synthetic_models(self):
        path = self.write("main.jsonl", [
            record("2026-07-25T10:00:00Z", "<synthetic>", mid="x", input_tokens=1_000_000),
        ])
        result = cost.cost_from_transcripts([path], PRICING)
        self.assertEqual(result["total_cost_usd"], 0.0)
        self.assertEqual(result["unknown_models"], [])

    def test_skips_lines_without_usage_or_model(self):
        path = self.write("main.jsonl", [
            {"timestamp": "2026-07-25T10:00:00Z", "message": {"id": "a", "model": "claude-sonnet-5"}},
            {"timestamp": "2026-07-25T10:00:00Z", "message": {"id": "b", "usage": {"input_tokens": 99}}},
            {"timestamp": "2026-07-25T10:00:00Z"},
        ])
        result = cost.cost_from_transcripts([path], PRICING)
        self.assertEqual(result["total_cost_usd"], 0.0)
        self.assertEqual(result["tokens"]["input"], 0)

    def test_tolerates_blank_and_malformed_lines(self):
        path = self.dir / "main.jsonl"
        with open(path, "w") as fh:
            fh.write("\n")
            fh.write("{not json\n")
            fh.write(json.dumps(
                record("2026-07-25T10:00:00Z", "claude-sonnet-5", mid="m1", input_tokens=1_000_000)
            ) + "\n")
        result = cost.cost_from_transcripts([path], PRICING)
        self.assertEqual(result["total_cost_usd"], 3.0)

    def test_cache_creation_ttl_breakdown(self):
        path = self.write("main.jsonl", [
            record("2026-07-25T10:00:00Z", "claude-sonnet-5", mid="m1",
                   cache_creation={"ephemeral_5m_input_tokens": 1_000_000,
                                   "ephemeral_1h_input_tokens": 1_000_000}),
        ])
        result = cost.cost_from_transcripts([path], PRICING)
        self.assertEqual(result["tokens"]["cache_write_5m"], 1_000_000)
        self.assertEqual(result["tokens"]["cache_write_1h"], 1_000_000)
        self.assertEqual(result["total_cost_usd"], 9.75)  # 3.75 + 6.00

    def test_cache_creation_without_breakdown_prices_at_the_5m_rate(self):
        path = self.write("main.jsonl", [
            record("2026-07-25T10:00:00Z", "claude-sonnet-5", mid="m1",
                   cache_creation_input_tokens=1_000_000),
        ])
        result = cost.cost_from_transcripts([path], PRICING)
        self.assertEqual(result["tokens"]["cache_write_5m"], 1_000_000)
        self.assertEqual(result["tokens"]["cache_write_1h"], 0)
        self.assertEqual(result["total_cost_usd"], 3.75)

    def test_cache_read_is_priced(self):
        path = self.write("main.jsonl", [
            record("2026-07-25T10:00:00Z", "claude-haiku-4-5", mid="m1",
                   cache_read_input_tokens=1_000_000),
        ])
        result = cost.cost_from_transcripts([path], PRICING)
        self.assertEqual(result["total_cost_usd"], 0.1)

    def test_unpriced_model_falls_back_to_the_latest_in_its_family(self):
        # An unpriced model's tokens are never silently dropped.
        path = self.write("main.jsonl", [
            record("2026-07-25T10:00:00Z", "claude-opus-5", mid="m1", input_tokens=1_000_000),
        ])
        result = cost.cost_from_transcripts([path], PRICING)
        self.assertEqual(result["total_cost_usd"], 5.0)  # priced as claude-opus-4-8
        self.assertEqual(result["unknown_models"], [])
        self.assertEqual(
            result["fallback_models"],
            [{"model": "claude-opus-5", "priced_as": "claude-opus-4-8", "family": "opus"}],
        )

    def test_model_with_no_family_match_is_reported_as_unknown(self):
        path = self.write("main.jsonl", [
            record("2026-07-25T10:00:00Z", "claude-fable-5", mid="m1", input_tokens=1_000_000),
        ])
        result = cost.cost_from_transcripts([path], PRICING)
        self.assertEqual(result["total_cost_usd"], 0.0)
        self.assertEqual(result["unknown_models"], ["claude-fable-5"])
        # Its tokens are still surfaced in the totals, so the omission is visible.
        self.assertEqual(result["tokens"]["input"], 1_000_000)

    def test_messages_without_an_id_are_all_counted(self):
        # No id means no de-duplication key; each line is counted on its own.
        path = self.write("main.jsonl", [
            record("2026-07-25T10:00:00Z", "claude-sonnet-5", input_tokens=1_000_000),
            record("2026-07-25T10:00:01Z", "claude-sonnet-5", input_tokens=1_000_000),
        ])
        result = cost.cost_from_transcripts([path], PRICING)
        self.assertEqual(result["tokens"]["input"], 2_000_000)


if __name__ == "__main__":
    unittest.main()
