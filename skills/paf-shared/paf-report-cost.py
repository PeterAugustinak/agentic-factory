#!/usr/bin/env python3
"""PAF per-invocation cost reporting helper.

Prices a single skill run from the slice of the Claude Code session transcript
that belongs to that `/paf:` invocation — from the moment the skill marked its
start (`mark`) up to when it finishes (`record`) — across the main-thread
transcript AND every subagent transcript, then appends the cost to the
per-feature cost ledger. At check-out, `aggregate` sums the whole feature's
per-skill costs for the PR.

Why per-invocation and not the whole session: multiple skills (e.g.
implement-issue then check-out) can run in ONE CLI session, so pricing the whole
transcript would re-price an earlier skill's tokens and inflate the feature
total; and a create-issue run inside a large multi-day session would price the
entire session. Each skill calls `mark` at its first step and `record` at its
last, so each run is costed only from its own invocation onward — a disjoint
slice. Slicing is by the per-line ISO 8601 `timestamp` every transcript record
carries (main and subagent alike).

Pricing comes from pricing.json alongside this script (factory-maintained).
Model ids are canonicalised before lookup — a trailing snapshot date
(`-YYYYMMDD`) is stripped, because pricing is per model, not per snapshot — so
**pricing.json keys must be dateless** (`claude-haiku-4-5`, never
`claude-haiku-4-5-20251001`) or they can never match — `load_config` rejects a
dated key outright rather than silently mismatching it. A model still absent from
pricing.json after that is priced at the latest known rate of the same family
(opus/sonnet/haiku) and flagged so pricing.json can be updated — its tokens are
never silently dropped. The ledger lives under the user's ~/.claude namespace,
never in the project.

Usage:
  paf-report-cost.py mark      --session <id> --skill <name>
  paf-report-cost.py record    --session <id> --skill <name> --issue <n> [--project <slug>] [--since <iso>]
  paf-report-cost.py aggregate --issue <n> [--project <slug>] [--cleanup]

`mark` records this invocation's start time so `record` can slice to it.
`record` prices this run's slice and appends a ledger entry.
`aggregate` prints the feature total (per-skill breakdown) for the PR body and,
with --cleanup, deletes the ledger file afterwards.
"""

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PRICING_PATH = Path(__file__).resolve().parent / "pricing.json"
LEDGER_ROOT = Path.home() / ".claude" / "paf" / "costs"
MARK_ROOT = LEDGER_ROOT / ".marks"

# Model-id family segment (claude-<family>-<version...>), used for the
# unpriced-model fallback.
FAMILIES = ("opus", "sonnet", "haiku")

# Token usage fields tracked per model, in the order they're summed and priced.
TOKEN_FIELDS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")

# The subset of TOKEN_FIELDS reported as a single "cached" column.
CACHE_FIELDS = ("cache_read", "cache_write_5m", "cache_write_1h")

# The four fields shown to the user (CLI output and the PR table), in display
# order. One constant so the aggregate table's row cells and its totals row
# can never drift out of sync with each other.
DISPLAY_FIELDS = ("in", "out", "cached", "total")

_SAFE = re.compile(r"^[A-Za-z0-9._-]+$")

# A trailing snapshot date on a model id (claude-haiku-4-5-20251001).
_SNAPSHOT_SUFFIX = re.compile(r"-\d{8}$")


def _validate(name: str, value: str, digits_only: bool = False) -> None:
    if value is None:
        return
    ok = value.isdigit() if digits_only else bool(_SAFE.match(value))
    if not ok:
        sys.exit(f"ERROR: invalid --{name} value {value!r}")


def project_slug() -> str:
    """Claude Code derives the project dir from the cwd by replacing '/' with '-'."""
    return os.getcwd().replace("/", "-")


def load_config() -> dict:
    with open(PRICING_PATH) as fh:
        cfg = json.load(fh)
    models = cfg["models"]
    # Enforce the dateless-keys invariant `canonical_model` relies on: a dated
    # key can never match after canonicalisation, silently reintroducing the
    # false "not in pricing.json" fallback this change fixed.
    dated = [m for m in models if _SNAPSHOT_SUFFIX.search(m)]
    if dated:
        sys.exit(
            f"ERROR: {PRICING_PATH} has dated model key(s) {dated} — pricing.json keys must be "
            f"dateless (e.g. 'claude-haiku-4-5', never 'claude-haiku-4-5-20251001'); a dated key "
            f"can never match a canonicalised model id."
        )
    return {"models": models, "usd_to_eur": cfg["usd_to_eur"]}


def find_transcripts(session_id: str) -> list[Path]:
    """Return the session's transcripts: the main one PLUS every subagent
    transcript. Claude Code stores a spawned subagent's messages in a SEPARATE
    file under <project>/<session-id>/subagents/... — not in the main transcript
    — so pricing only the main file would miss all subagent (reviewer, builder,
    verifier, ...) token usage, which typically dominates a skill run."""
    mains = glob.glob(str(Path.home() / ".claude" / "projects" / "*" / f"{session_id}.jsonl"))
    if not mains:
        sys.exit(f"ERROR: no transcript found for session {session_id}")
    # If the same session id somehow appears twice, the largest file is the real run.
    main = max(mains, key=lambda p: os.path.getsize(p))
    project = os.path.dirname(main)
    # Subagent transcripts (recursively, in case of nested subagents).
    subs = glob.glob(os.path.join(project, session_id, "**", "*.jsonl"), recursive=True)
    return [Path(main)] + [Path(s) for s in subs]


def parse_ts(value):
    """Parse an ISO 8601 timestamp; return a datetime or None."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def canonical_model(model_id: str) -> str:
    """Strip a trailing snapshot date (`-YYYYMMDD`) from a model id.

    `claude-haiku-4-5-20251001` is a dated snapshot of `claude-haiku-4-5`, and
    pricing is per model, not per snapshot — so the two must price identically
    and share one bucket. The documented id grammar makes the trailing 8-digit
    segment unambiguous: `claude-{name}-{major}[-{minor}]` for 4.6 and later,
    `claude-{name}-{major}-{minor}-{YYYYMMDD}` before it — a version segment is
    never 8 digits. Source:
    https://platform.claude.com/docs/en/about-claude/models/model-ids-and-versions"""
    return _SNAPSHOT_SUFFIX.sub("", model_id)


def token_breakdown(tokens: dict) -> dict:
    """Collapse the five tracked token fields into the four reported ones.

    `cached` merges the three cache fields (read + both write TTLs); `total` is
    in + out + cached. The five fields are disjoint — the API counts
    `input_tokens` as those neither read from nor used to create a cache — so
    summing them does not double-count."""
    cached = sum(tokens[f] for f in CACHE_FIELDS)
    return {
        "in": tokens["input"],
        "out": tokens["output"],
        "cached": cached,
        "total": tokens["input"] + tokens["output"] + cached,
    }


def abbrev_tokens(n: int) -> str:
    """Compact a token count for display: 812, 48.2k, 1.4M.

    Raw integers are unreadable and make the PR table too wide. The 1M threshold
    is the value that *rounds* to 1.0M at one decimal, so no cell ever reads
    "1000.0k"."""
    if n >= 999_950:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def model_family(model_id: str):
    """The family segment (opus/sonnet/haiku) of a model id, or None."""
    for seg in model_id.split("-"):
        if seg in FAMILIES:
            return seg
    return None


def model_version(model_id: str) -> tuple:
    """Numeric version tuple from the digit segments after the family token.

    claude-sonnet-5 -> (5,); claude-sonnet-5-1 -> (5, 1); claude-haiku-4-5 ->
    (4, 5). Tuple comparison then orders correctly across the differing id
    shapes ((5,) < (5, 1); (4, 8) > (4, 5))."""
    segs = model_id.split("-")
    family = model_family(model_id)
    if family is None:
        return ()
    idx = segs.index(family)
    return tuple(int(s) for s in segs[idx + 1:] if s.isdigit())


def latest_priced_in_family(family: str, pricing: dict):
    """Highest-versioned priced model id in the given family, or None."""
    candidates = [m for m in pricing if model_family(m) == family]
    if not candidates:
        return None
    return max(candidates, key=model_version)


def cost_from_transcripts(paths: list[Path], pricing: dict, since=None) -> dict:
    """Sum tokens per model across the main transcript AND every subagent
    transcript, and price them. When `since` is set, only messages timestamped
    at or after it are counted — the slice belonging to a single skill
    invocation. Model ids are canonicalised first (see `canonical_model`), so a
    dated snapshot and its alias share one bucket. A model still absent from
    `pricing` is priced at the latest known rate of its own family (recorded in
    `fallback_models`); only a model with no family match at all is dropped
    (recorded in `unknown_models`). Returns totals + fallbacks + unknowns."""
    per_model_tokens: dict[str, dict[str, int]] = {}
    # A single assistant turn is written across several transcript lines (one per
    # content block: thinking, tool_use, ...), and the SAME `usage` is copied onto
    # each. Count each message's usage exactly once, keyed by message id, or the
    # totals are multi-counted.
    seen_ids: set = set()
    for transcript in paths:
        with open(transcript) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = parse_ts(rec.get("timestamp"))
                # Slice to this invocation: skip anything before the mark (and any
                # line we cannot place on the timeline).
                if since is not None and (ts is None or ts < since):
                    continue
                msg = rec.get("message") or {}
                usage = msg.get("usage")
                model = msg.get("model")
                if not usage or not model:
                    continue
                # Skip Claude Code internal placeholders like "<synthetic>" — not billable.
                if model.startswith("<"):
                    continue
                # Bucket by the dateless id: pricing is per model, not per snapshot,
                # so a dated snapshot and its alias are one rate-identical bucket.
                model = canonical_model(model)
                # Count each assistant message's usage once (see seen_ids note above).
                mid = msg.get("id")
                if mid is not None:
                    if mid in seen_ids:
                        continue
                    seen_ids.add(mid)
                t = per_model_tokens.setdefault(
                    model,
                    dict.fromkeys(TOKEN_FIELDS, 0),
                )
                t["input"] += usage.get("input_tokens", 0)
                t["output"] += usage.get("output_tokens", 0)
                t["cache_read"] += usage.get("cache_read_input_tokens", 0)
                cc = usage.get("cache_creation") or {}
                if cc:
                    t["cache_write_5m"] += cc.get("ephemeral_5m_input_tokens", 0)
                    t["cache_write_1h"] += cc.get("ephemeral_1h_input_tokens", 0)
                else:
                    # No TTL breakdown available — price all cache writes at the 5m rate.
                    t["cache_write_5m"] += usage.get("cache_creation_input_tokens", 0)

    total_cost = 0.0
    unknown_models = []
    fallback_models = []
    tokens_total = dict.fromkeys(TOKEN_FIELDS, 0)
    for model, tok in per_model_tokens.items():
        for k in tokens_total:
            tokens_total[k] += tok[k]
        rates = pricing.get(model)
        if not rates:
            # Unpriced model: fall back to the latest known price of the same
            # family rather than dropping its tokens from the total.
            family = model_family(model)
            alt = latest_priced_in_family(family, pricing) if family else None
            if alt:
                rates = pricing[alt]
                fallback_models.append({"model": model, "priced_as": alt, "family": family})
            else:
                unknown_models.append(model)
                continue
        for k in TOKEN_FIELDS:
            total_cost += tok[k] / 1_000_000 * rates[k]

    return {
        "total_cost_usd": round(total_cost, 4),
        "tokens": tokens_total,
        "fallback_models": fallback_models,
        "unknown_models": unknown_models,
    }


def ledger_path(project: str, issue: str) -> Path:
    return LEDGER_ROOT / project / f"{issue}.jsonl"


def mark_path(session: str, skill: str) -> Path:
    return MARK_ROOT / f"{session}-{skill}.start"


def cmd_mark(args) -> None:
    _validate("session", args.session)
    _validate("skill", args.skill)
    now = datetime.now(timezone.utc).isoformat()
    path = mark_path(args.session, args.skill)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(now)
    print(f"Marked {args.skill} invocation start at {now}")


def cmd_record(args) -> None:
    _validate("session", args.session)
    _validate("skill", args.skill)
    _validate("issue", args.issue, digits_only=True)
    if args.project is not None:
        _validate("project", args.project)
    project = args.project or project_slug()
    config = load_config()

    # Slice to this invocation: an explicit --since wins; otherwise use the
    # marker `mark` wrote at the skill's first step. With neither, the whole
    # transcript is priced (fallback for a standalone/manual run).
    since = None
    marker = mark_path(args.session, args.skill)
    if args.since:
        since = parse_ts(args.since)
    elif marker.exists():
        since = parse_ts(marker.read_text().strip())

    if since is None:
        print(
            f"WARNING: no invocation-start marker for session/skill '{args.skill}' and no --since given — "
            f"pricing the WHOLE session transcript (may over-count if skills share a session). "
            f"Ensure step 1 ran `mark`."
        )

    result = cost_from_transcripts(find_transcripts(args.session), config["models"], since=since)
    cost_eur = round(result["total_cost_usd"] * config["usd_to_eur"], 4)

    entry = {
        "skill": args.skill,
        "issue": args.issue,
        "total_cost_eur": cost_eur,
        "total_cost_usd": result["total_cost_usd"],
        "tokens": result["tokens"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    path = ledger_path(project, args.issue)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as fh:
        fh.write(json.dumps(entry) + "\n")

    # This invocation is priced and recorded — clear its marker.
    if marker.exists():
        marker.unlink()

    tok = token_breakdown(result["tokens"])
    print(f"--- {args.skill} — cost ---")
    # Abbreviated exactly as the aggregate table does, so the terminal and the
    # PR report the same numbers in the same shape.
    print(
        f"Tokens: {abbrev_tokens(tok['in'])} in · {abbrev_tokens(tok['out'])} out · "
        f"{abbrev_tokens(tok['cached'])} cached · {abbrev_tokens(tok['total'])} total"
    )
    print(f"Cost: €{cost_eur:.2f}")
    for fb in result["fallback_models"]:
        print(
            f"NOTE: {fb['model']} is not in pricing.json — priced at the latest known "
            f"{fb['family']} rate ({fb['priced_as']}). Add the dateless key "
            f"\"{fb['model']}\" to {PRICING_PATH}."
        )
    if result["unknown_models"]:
        print(
            f"WARNING: no pricing and no same-family fallback for {result['unknown_models']} — "
            f"their tokens were excluded. Add them to {PRICING_PATH} (dateless keys)."
        )


def cmd_aggregate(args) -> None:
    _validate("issue", args.issue, digits_only=True)
    if args.project is not None:
        _validate("project", args.project)
    project = args.project or project_slug()
    path = ledger_path(project, args.issue)
    if not path.exists():
        print(f"No cost ledger found for issue {args.issue} (nothing to aggregate).")
        return

    entries = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                entries.append(json.loads(line))

    total_cost = sum(e["total_cost_eur"] for e in entries)
    # Accumulated from RAW counts and abbreviated only at print time — never
    # summed from the rounded display strings. The displayed columns therefore
    # will not always add up to the displayed total ("1.4k + 1.4k" against a
    # "2.9k" total); that is deliberate, so the total stays the real total.
    totals = dict.fromkeys(DISPLAY_FIELDS, 0)

    lines = [f"## Factory run cost — feature #{args.issue}", ""]
    lines.append("| Skill | In | Out | Cached | Total | Cost (EUR) |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for e in entries:
        # Defense in depth: the ledger is re-read here rather than trusted from
        # the write path, and this table is pasted verbatim into a PR/MR
        # description — a public collaboration surface.
        _validate("skill", e["skill"])
        tok = token_breakdown(e["tokens"])
        for k in totals:
            totals[k] += tok[k]
        cells = " | ".join(abbrev_tokens(tok[k]) for k in DISPLAY_FIELDS)
        lines.append(f"| {e['skill']} | {cells} | €{e['total_cost_eur']:.2f} |")
    bold = " | ".join(f"**{abbrev_tokens(totals[k])}**" for k in DISPLAY_FIELDS)
    lines.append(f"| **Total** | {bold} | **€{total_cost:.2f}** |")
    print("\n".join(lines))

    if args.cleanup:
        path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description="PAF per-invocation cost reporting.")
    sub = parser.add_subparsers(dest="command", required=True)

    mk = sub.add_parser("mark", help="record this invocation's start time for later slicing")
    mk.add_argument("--session", required=True)
    mk.add_argument("--skill", required=True)
    mk.set_defaults(func=cmd_mark)

    rec = sub.add_parser("record", help="price this run's slice and append to the ledger")
    rec.add_argument("--session", required=True)
    rec.add_argument("--skill", required=True)
    rec.add_argument("--issue", required=True)
    rec.add_argument("--project")
    rec.add_argument("--since", help="ISO 8601 slice start (overrides the mark marker)")
    rec.set_defaults(func=cmd_record)

    agg = sub.add_parser("aggregate", help="sum the feature's ledger for the PR body")
    agg.add_argument("--issue", required=True)
    agg.add_argument("--project")
    agg.add_argument("--cleanup", action="store_true")
    agg.set_defaults(func=cmd_aggregate)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
