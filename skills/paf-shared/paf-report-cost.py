#!/usr/bin/env python3
"""PAF cost + wall-clock reporting helper.

Computes the token cost of a skill run from the Claude Code session transcript
(main-thread and subagent messages alike), appends it to the per-feature cost
ledger, and — at check-out — aggregates the whole feature's cost for the PR.

Pricing comes from pricing.json alongside this script (factory-maintained).
The ledger lives under the user's ~/.claude namespace, never in the project.

Both cost and wall-clock are derived from the whole session transcript (all
usage lines; first→last timestamp), so a create-issue-phase session captures
the idea discussion / grilling that preceded the /create-issue invocation.

Usage:
  paf-report-cost.py record    --session <id> --skill <name> --issue <n> [--project <slug>]
  paf-report-cost.py aggregate --issue <n> [--project <slug>] [--cleanup]

`record` prints this run's cost report and appends a ledger entry.
`aggregate` prints the feature total (per-skill breakdown) for the PR body and,
with --cleanup, deletes the ledger file afterwards.
"""

import argparse
import glob
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PRICING_PATH = Path(__file__).resolve().parent / "pricing.json"
LEDGER_ROOT = Path.home() / ".claude" / "paf" / "costs"


def project_slug() -> str:
    """Claude Code derives the project dir from the cwd by replacing '/' with '-'."""
    return os.getcwd().replace("/", "-")


def load_config() -> dict:
    with open(PRICING_PATH) as fh:
        cfg = json.load(fh)
    return {"models": cfg["models"], "usd_to_eur": cfg["usd_to_eur"]}


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


def cost_from_transcripts(paths: list[Path], pricing: dict) -> dict:
    """Sum tokens per model across the main transcript AND every subagent
    transcript, and price them; also derive wall-clock from the earliest and
    latest message timestamps across all of them. Returns totals + wall-clock
    + unknowns."""
    per_model_tokens: dict[str, dict[str, int]] = {}
    first_ts = None
    last_ts = None
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
                if ts:
                    if first_ts is None or ts < first_ts:
                        first_ts = ts
                    if last_ts is None or ts > last_ts:
                        last_ts = ts
                msg = rec.get("message") or {}
                usage = msg.get("usage")
                model = msg.get("model")
                if not usage or not model:
                    continue
                # Skip Claude Code internal placeholders like "<synthetic>" — not billable.
                if model.startswith("<"):
                    continue
                # Count each assistant message's usage once (see seen_ids note above).
                mid = msg.get("id")
                if mid is not None:
                    if mid in seen_ids:
                        continue
                    seen_ids.add(mid)
                t = per_model_tokens.setdefault(
                    model,
                    {"input": 0, "output": 0, "cache_read": 0, "cache_write_5m": 0, "cache_write_1h": 0},
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
    tokens_total = {"input": 0, "output": 0, "cache_read": 0, "cache_write_5m": 0, "cache_write_1h": 0}
    for model, tok in per_model_tokens.items():
        for k in tokens_total:
            tokens_total[k] += tok[k]
        rates = pricing.get(model)
        if not rates:
            unknown_models.append(model)
            continue
        for k in ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h"):
            total_cost += tok[k] / 1_000_000 * rates[k]

    wall_clock_seconds = 0.0
    if first_ts and last_ts:
        wall_clock_seconds = max(0.0, (last_ts - first_ts).total_seconds())

    return {
        "total_cost_usd": round(total_cost, 4),
        "tokens": tokens_total,
        "wall_clock_seconds": wall_clock_seconds,
        "unknown_models": unknown_models,
    }


def ledger_path(project: str, issue: str) -> Path:
    return LEDGER_ROOT / project / f"{issue}.jsonl"


def fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def cmd_record(args) -> None:
    project = args.project or project_slug()
    config = load_config()
    result = cost_from_transcripts(find_transcripts(args.session), config["models"])
    wall_clock = result["wall_clock_seconds"]
    cost_eur = round(result["total_cost_usd"] * config["usd_to_eur"], 4)

    entry = {
        "skill": args.skill,
        "issue": args.issue,
        "total_cost_eur": cost_eur,
        "total_cost_usd": result["total_cost_usd"],
        "tokens": result["tokens"],
        "wall_clock_seconds": round(wall_clock),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    path = ledger_path(project, args.issue)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as fh:
        fh.write(json.dumps(entry) + "\n")

    print(f"--- {args.skill} — cost + time ---")
    print(f"Cost:       €{cost_eur:.4f}")
    print(f"Wall-clock: {fmt_duration(wall_clock)}")
    if result["unknown_models"]:
        print(f"WARNING: no pricing for {result['unknown_models']} — update skills/_shared/pricing.json")


def cmd_aggregate(args) -> None:
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
    total_wall = sum(e.get("wall_clock_seconds", 0) for e in entries)

    lines = [f"## Factory run cost — feature #{args.issue}", ""]
    lines.append("| Skill | Cost (EUR) | Wall-clock |")
    lines.append("|---|---|---|")
    for e in entries:
        lines.append(f"| {e['skill']} | €{e['total_cost_eur']:.4f} | {fmt_duration(e.get('wall_clock_seconds', 0))} |")
    lines.append(f"| **Total** | **€{total_cost:.4f}** | **{fmt_duration(total_wall)}** |")
    print("\n".join(lines))

    if args.cleanup:
        path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description="PAF cost + wall-clock reporting.")
    sub = parser.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("record", help="price this run and append to the ledger")
    rec.add_argument("--session", required=True)
    rec.add_argument("--skill", required=True)
    rec.add_argument("--issue", required=True)
    rec.add_argument("--project")
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