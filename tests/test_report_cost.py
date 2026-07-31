"""Tests for skills/paf-shared/paf-report-cost.py.

Covers the module's pure functions — timestamp parsing, model-id family/version
handling, snapshot-date canonicalisation, the same-family price fallback, the
token-display helpers — plus `cost_from_transcripts`, which decides what a
`/paf:` run actually costs, and the two CLI commands that report it. Transcript
fixtures are written to a temporary directory, and the module's `LEDGER_ROOT` /
`MARK_ROOT` / `PRICING_PATH` are redirected there for the CLI tests: no real
session data is read and the real ~/.claude ledger is never touched.
"""

import argparse
import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from tests.support import REPO_ROOT, REPORT_COST, load_module

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


class CanonicalModelTests(unittest.TestCase):
    def test_strips_a_snapshot_date(self):
        self.assertEqual(cost.canonical_model("claude-haiku-4-5-20251001"), "claude-haiku-4-5")

    def test_leaves_a_dateless_id_alone(self):
        self.assertEqual(cost.canonical_model("claude-haiku-4-5"), "claude-haiku-4-5")

    def test_leaves_a_two_segment_version_alone(self):
        # The minor version must not be mistaken for a truncated date.
        self.assertEqual(cost.canonical_model("claude-sonnet-5-1"), "claude-sonnet-5-1")

    def test_leaves_a_seven_digit_tail_alone(self):
        self.assertEqual(cost.canonical_model("claude-sonnet-5-2025100"), "claude-sonnet-5-2025100")

    def test_leaves_a_nine_digit_tail_alone(self):
        self.assertEqual(
            cost.canonical_model("claude-sonnet-5-202510012"), "claude-sonnet-5-202510012"
        )

    def test_strips_only_the_trailing_segment(self):
        # An 8-digit segment that is not at the end is not a snapshot date.
        self.assertEqual(cost.canonical_model("claude-20251001-sonnet-5"), "claude-20251001-sonnet-5")


class TokenBreakdownTests(unittest.TestCase):
    TOKENS = {
        "input": 100, "output": 20,
        "cache_read": 5, "cache_write_5m": 3, "cache_write_1h": 2,
    }

    def test_cached_sums_the_three_cache_fields(self):
        self.assertEqual(cost.token_breakdown(self.TOKENS)["cached"], 10)

    def test_total_is_in_plus_out_plus_cached(self):
        b = cost.token_breakdown(self.TOKENS)
        self.assertEqual(b["total"], b["in"] + b["out"] + b["cached"])
        self.assertEqual(b["total"], 130)

    def test_in_and_out_pass_through(self):
        b = cost.token_breakdown(self.TOKENS)
        self.assertEqual((b["in"], b["out"]), (100, 20))


class AbbrevTokensTests(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(cost.abbrev_tokens(0), "0")

    def test_below_one_thousand_is_exact(self):
        self.assertEqual(cost.abbrev_tokens(999), "999")

    def test_one_thousand_boundary(self):
        self.assertEqual(cost.abbrev_tokens(1_000), "1.0k")

    def test_thousands(self):
        self.assertEqual(cost.abbrev_tokens(48_231), "48.2k")

    def test_just_below_the_rounded_million_boundary(self):
        self.assertEqual(cost.abbrev_tokens(999_949), "999.9k")

    def test_rounds_up_to_a_million_rather_than_rendering_1000k(self):
        self.assertEqual(cost.abbrev_tokens(999_950), "1.0M")

    def test_one_million_boundary(self):
        self.assertEqual(cost.abbrev_tokens(1_000_000), "1.0M")

    def test_millions(self):
        self.assertEqual(cost.abbrev_tokens(1_400_000), "1.4M")


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


class LoadConfigTests(unittest.TestCase):
    """`load_config` enforces the dateless-keys invariant `canonical_model`
    relies on, so a dated key can never silently reintroduce the false
    "not in pricing.json" fallback this change fixes."""

    def write_pricing(self, models):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "pricing.json"
        path.write_text(json.dumps({"models": models, "usd_to_eur": 0.9}))
        return path

    def test_rejects_a_dated_model_key(self):
        path = self.write_pricing({"claude-haiku-4-5-20251001": {"input": 1, "output": 1}})
        with mock.patch.object(cost, "PRICING_PATH", path):
            with self.assertRaises(SystemExit):
                cost.load_config()

    def test_accepts_dateless_keys(self):
        path = self.write_pricing({"claude-haiku-4-5": {"input": 1, "output": 1}})
        with mock.patch.object(cost, "PRICING_PATH", path):
            config = cost.load_config()
        self.assertIn("claude-haiku-4-5", config["models"])


class ShippedPricingFileTests(unittest.TestCase):
    """The real pricing.json PAF ships (not the test PRICING stand-in above)
    must itself satisfy the dateless-keys invariant `load_config` enforces."""

    def test_shipped_pricing_json_has_only_dateless_keys(self):
        pricing_path = REPO_ROOT / "skills" / "paf-shared" / "pricing.json"
        with open(pricing_path) as fh:
            models = json.load(fh)["models"]
        dated = [m for m in models if cost._SNAPSHOT_SUFFIX.search(m)]
        self.assertEqual(dated, [], f"dated model key(s) in pricing.json: {dated}")


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

    def test_dated_snapshot_of_a_priced_model_is_an_exact_match(self):
        # claude-haiku-4-5-20251001 IS claude-haiku-4-5: pricing is per model, not
        # per snapshot, so this must not be recorded as a fallback.
        path = self.write("main.jsonl", [
            record("2026-07-25T10:00:00Z", "claude-haiku-4-5-20251001", mid="m1",
                   input_tokens=1_000_000),
        ])
        result = cost.cost_from_transcripts([path], PRICING)
        self.assertEqual(result["total_cost_usd"], 1.0)
        self.assertEqual(result["fallback_models"], [])
        self.assertEqual(result["unknown_models"], [])

    def test_dated_and_aliased_ids_share_one_bucket(self):
        path = self.write("main.jsonl", [
            record("2026-07-25T10:00:00Z", "claude-haiku-4-5-20251001", mid="m1",
                   input_tokens=1_000_000),
            record("2026-07-25T10:00:01Z", "claude-haiku-4-5", mid="m2",
                   input_tokens=1_000_000),
        ])
        result = cost.cost_from_transcripts([path], PRICING)
        self.assertEqual(result["tokens"]["input"], 2_000_000)
        self.assertEqual(result["total_cost_usd"], 2.0)
        self.assertEqual(result["fallback_models"], [])

    def test_dated_snapshot_of_an_unpriced_model_still_falls_back(self):
        # Stripping the date is a prior step, not a replacement for the fallback:
        # claude-3-5-sonnet is genuinely absent from the price table.
        path = self.write("main.jsonl", [
            record("2026-07-25T10:00:00Z", "claude-3-5-sonnet-20241022", mid="m1",
                   input_tokens=1_000_000),
        ])
        result = cost.cost_from_transcripts([path], PRICING)
        self.assertEqual(result["total_cost_usd"], 4.0)  # priced as claude-sonnet-5-1
        self.assertEqual(
            result["fallback_models"],
            [{"model": "claude-3-5-sonnet", "priced_as": "claude-sonnet-5-1", "family": "sonnet"}],
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

    def test_dated_snapshot_of_an_unknown_family_model_is_reported_dateless(self):
        # Canonicalisation composes with the unknown-family path: the dateless
        # id, not the dated one, is what lands in unknown_models.
        path = self.write("main.jsonl", [
            record("2026-07-25T10:00:00Z", "claude-fable-5-20260101", mid="m1",
                   input_tokens=1_000_000),
        ])
        result = cost.cost_from_transcripts([path], PRICING)
        self.assertEqual(result["unknown_models"], ["claude-fable-5"])
        self.assertEqual(result["fallback_models"], [])

    def test_messages_without_an_id_are_all_counted(self):
        # No id means no de-duplication key; each line is counted on its own.
        path = self.write("main.jsonl", [
            record("2026-07-25T10:00:00Z", "claude-sonnet-5", input_tokens=1_000_000),
            record("2026-07-25T10:00:01Z", "claude-sonnet-5", input_tokens=1_000_000),
        ])
        result = cost.cost_from_transcripts([path], PRICING)
        self.assertEqual(result["tokens"]["input"], 2_000_000)


def tokens(inp=0, out=0, cache_read=0, cache_write_5m=0, cache_write_1h=0):
    """A ledger entry's `tokens` dict, in the shape `cmd_record` writes."""
    return {
        "input": inp, "output": out, "cache_read": cache_read,
        "cache_write_5m": cache_write_5m, "cache_write_1h": cache_write_1h,
    }


class CliTestCase(unittest.TestCase):
    """Base for the CLI-command tests.

    `LEDGER_ROOT`, `MARK_ROOT` and `PRICING_PATH` are module-level and derived
    from `Path.home()`, so they are redirected onto a temporary directory —
    otherwise these tests would write to the developer's real ~/.claude ledger.
    """

    PROJECT = "test-project"
    ISSUE = "56"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

        pricing_file = self.dir / "pricing.json"
        pricing_file.write_text(json.dumps({"models": PRICING, "usd_to_eur": 0.5}))

        ledger_root = self.dir / "costs"
        for name, value in (
            ("LEDGER_ROOT", ledger_root),
            ("MARK_ROOT", ledger_root / ".marks"),
            ("PRICING_PATH", pricing_file),
        ):
            patcher = mock.patch.object(cost, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_command(self, func, **kwargs):
        """Call a cmd_* function and return everything it printed."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            func(argparse.Namespace(**kwargs))
        return out.getvalue()

    def write_ledger(self, entries):
        path = cost.ledger_path(self.PROJECT, self.ISSUE)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as fh:
            for entry in entries:
                fh.write(json.dumps(entry) + "\n")
        return path

    def aggregate(self, cleanup=False):
        return self.run_command(
            cost.cmd_aggregate, issue=self.ISSUE, project=self.PROJECT, cleanup=cleanup
        )


class AggregateTableTests(CliTestCase):
    def entry(self, skill, eur, tok):
        return {"skill": skill, "issue": self.ISSUE, "total_cost_eur": eur,
                "total_cost_usd": eur * 2, "tokens": tok, "timestamp": "2026-07-25T10:00:00Z"}

    def test_header_and_alignment_row(self):
        self.write_ledger([self.entry("create-issue", 0.31, tokens(inp=1))])
        out = self.aggregate()
        self.assertIn("| Skill | In | Out | Cached | Total | Cost (EUR) |", out)
        # Every numeric column is right-aligned; the Skill column is not.
        self.assertIn("|---|---:|---:|---:|---:|---:|", out)

    def test_one_row_per_invocation(self):
        self.write_ledger([
            self.entry("create-issue", 0.10, tokens(inp=1)),
            self.entry("implement-issue", 0.20, tokens(inp=2)),
            self.entry("implement-issue", 0.30, tokens(inp=3)),
        ])
        out = self.aggregate()
        # A re-run of a skill produces a second row rather than being merged.
        self.assertEqual(out.count("| implement-issue |"), 2)

    def test_cells_carry_the_breakdown_abbreviated(self):
        self.write_ledger([self.entry(
            "implement-issue", 1.87,
            tokens(inp=48_231, out=9_700, cache_read=1_000_000,
                   cache_write_5m=300_000, cache_write_1h=100_000),
        )])
        out = self.aggregate()
        # cached = 1.0M + 300k + 100k = 1.4M; total = 1.4M + 48.2k + 9.7k = 1.5M
        self.assertIn("| implement-issue | 48.2k | 9.7k | 1.4M | 1.5M | €1.87 |", out)

    def test_total_row_bolds_all_four_token_columns_and_the_cost(self):
        self.write_ledger([
            self.entry("create-issue", 0.50, tokens(inp=1_000, out=100, cache_read=2_000)),
            self.entry("check-out", 0.25, tokens(inp=1_000, out=100, cache_write_5m=2_000)),
        ])
        out = self.aggregate()
        self.assertIn("| **Total** | **2.0k** | **200** | **4.0k** | **6.2k** | **€0.75** |", out)

    def test_totals_come_from_raw_counts_not_rounded_cells(self):
        # 1_440 abbreviates to "1.4k"; two of them total 2_880 -> "2.9k", NOT the
        # "2.8k" a sum of the rounded cells would give. The drift is deliberate:
        # the total must stay the real total.
        self.write_ledger([
            self.entry("create-issue", 0.10, tokens(inp=1_440)),
            self.entry("implement-issue", 0.10, tokens(inp=1_440)),
        ])
        out = self.aggregate()
        self.assertIn("| create-issue | 1.4k | 0 | 0 | 1.4k | €0.10 |", out)
        self.assertIn("| implement-issue | 1.4k | 0 | 0 | 1.4k | €0.10 |", out)
        self.assertIn("| **Total** | **2.9k** | **0** | **0** | **2.9k** | **€0.20** |", out)

    def test_cleanup_removes_the_ledger(self):
        path = self.write_ledger([self.entry("check-out", 0.10, tokens(inp=1))])
        self.aggregate(cleanup=True)
        self.assertFalse(path.exists())

    def test_rejects_a_skill_field_that_would_break_the_markdown_table(self):
        # Defense in depth: the ledger is re-read here, not trusted from the
        # write path, and this table is pasted verbatim into a PR/MR
        # description — re-validate exactly as the write path does.
        self.write_ledger([self.entry("create-issue | ) malicious", 0.10, tokens(inp=1))])
        with self.assertRaises(SystemExit):
            self.aggregate()


class RecordOutputTests(CliTestCase):
    SINCE = "2026-07-25T00:00:00Z"

    def record_run(self, records, skill="implement-issue"):
        path = self.dir / "transcript.jsonl"
        with open(path, "w") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")
        with mock.patch.object(cost, "find_transcripts", lambda _session: [path]):
            return self.run_command(
                cost.cmd_record, session="sess1", skill=skill, issue=self.ISSUE,
                project=self.PROJECT, since=self.SINCE,
            )

    def test_prints_the_token_breakdown_beside_the_cost(self):
        out = self.record_run([
            record("2026-07-25T10:00:00Z", "claude-sonnet-5", mid="m1",
                   input_tokens=48_231, output_tokens=9_700,
                   cache_read_input_tokens=1_400_000),
        ])
        self.assertIn("Tokens: 48.2k in · 9.7k out · 1.4M cached · 1.5M total", out)
        # (48_231*3 + 9_700*15 + 1_400_000*0.3) / 1e6 (per MTok) = 0.710193 USD ->
        # €0.3551 (usd_to_eur=0.5) -> displayed €0.36.
        self.assertIn("Cost: €0.36", out)

    def test_writes_the_ledger_entry_to_the_redirected_root(self):
        self.record_run([
            record("2026-07-25T10:00:00Z", "claude-sonnet-5", mid="m1", input_tokens=1_000_000),
        ])
        path = cost.ledger_path(self.PROJECT, self.ISSUE)
        entry = json.loads(path.read_text().strip())
        self.assertEqual(entry["skill"], "implement-issue")
        self.assertEqual(entry["total_cost_usd"], 3.0)
        self.assertEqual(entry["total_cost_eur"], 1.5)
        self.assertEqual(entry["tokens"]["input"], 1_000_000)

    def test_no_note_for_a_dated_snapshot_of_a_priced_model(self):
        # The false positive this fixes: the run used to be reported as unpriced.
        out = self.record_run([
            record("2026-07-25T10:00:00Z", "claude-haiku-4-5-20251001", mid="m1",
                   input_tokens=1_000_000),
        ])
        self.assertNotIn("NOTE:", out)
        self.assertIn("Cost: €0.50", out)

    def test_fallback_note_names_the_dateless_id_and_asks_for_a_dateless_key(self):
        out = self.record_run([
            record("2026-07-25T10:00:00Z", "claude-opus-6-20260101", mid="m1",
                   input_tokens=1_000_000),
        ])
        self.assertIn("NOTE: claude-opus-6 is not in pricing.json", out)
        self.assertIn("latest known opus rate (claude-opus-4-8)", out)
        self.assertIn('Add the dateless key "claude-opus-6"', out)

    def test_unknown_model_warning_asks_for_dateless_keys(self):
        out = self.record_run([
            record("2026-07-25T10:00:00Z", "claude-fable-5", mid="m1", input_tokens=1_000_000),
        ])
        self.assertIn("WARNING: no pricing and no same-family fallback", out)
        self.assertIn("(dateless keys)", out)

    def test_fallback_note_for_the_3_5_sonnet_acceptance_criterion(self):
        # The issue's own acceptance-criterion model: a pre-4.6 dated snapshot
        # that is genuinely absent from the price table (not an alias of a
        # priced model) still gets a clear same-family-fallback NOTE at the CLI
        # level, keyed by its dateless id. `cost_from_transcripts` already
        # covers this; this confirms cmd_record's printed NOTE text too.
        out = self.record_run([
            record("2026-07-25T10:00:00Z", "claude-3-5-sonnet-20241022", mid="m1",
                   input_tokens=1_000_000),
        ])
        self.assertIn("NOTE: claude-3-5-sonnet is not in pricing.json", out)
        self.assertIn("latest known sonnet rate (claude-sonnet-5-1)", out)
        self.assertIn('Add the dateless key "claude-3-5-sonnet"', out)


if __name__ == "__main__":
    unittest.main()
