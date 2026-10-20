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
never silently dropped. Each message is priced on its own, because a model
priced by prompt length (`prompt_tiers` in pricing.json) bills each request at
the tier its prompt length — input + cache reads + cache writes — selects. The
ledger lives under the user's ~/.claude namespace, never in the project.

Stopped runs are recovered, not lost. A skill that STOPs never reaches its
`record` step, so its marker stays open. The marker therefore carries its own
attribution (session, skill, project, issue, start), and every `mark` and
`record` appends its timestamp to a per-session boundary log. An open marker is
closed into a `<skill>-stopped` ledger row (a `_SAFE` name — `aggregate`
re-validates every row) by the next `mark` of the same skill in the same session,
and by `aggregate` for every open marker of that project + issue in any session.
The stopped slice runs from the marker's start to the first later boundary in
its session — the next PAF skill's mark or record — so it never overlaps a run
recorded after it; with no later boundary it ends at the close time, which is
then appended as a boundary so a still-running run of that session that records
later starts there. A marker with no feature key (create-issue before posting,
or a legacy bare-timestamp marker) cannot be attributed to a ledger and is
discarded.

The feature key. A feature is keyed by its issue number when it has one, and by
its branch name otherwise — not every feature has an issue, and a missing or
malformed issue number never stops a command: it falls back to the branch, and
with neither the run is reported but not added to any ledger.

Usage:
  paf-report-cost.py mark      --session <id> --skill <name> [--issue <n>] [--branch <name>] [--project <slug>]
  paf-report-cost.py record    --session <id> --skill <name> [--issue <n>] [--branch <name>] [--project <slug>] [--since <iso>]
  paf-report-cost.py aggregate [--issue <n>] [--branch <name>] [--project <slug>] [--cleanup]

`mark` records this invocation's start (closing the same skill's open marker of
this session first) so `record` can slice to it.
`record` prices this run's slice and appends a ledger entry.
`aggregate` closes the feature's open markers, prints the feature total
(per-skill breakdown) for the PR body and, with --cleanup, deletes the ledger
file afterwards.
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


def _is_number(value) -> bool:
    """An ASCII-digit string (str.isdigit alone also accepts non-ASCII digits)."""
    return isinstance(value, str) and value.isascii() and value.isdigit()


def _is_safe(value) -> bool:
    """A `_SAFE` name that is not '.' or '..', which would escape the ledger directory."""
    return isinstance(value, str) and bool(_SAFE.match(value)) and value not in (".", "..")


def _validate(name: str, value: str, digits_only: bool = False) -> None:
    if value is None:
        return
    ok = _is_number(value) if digits_only else _is_safe(value)
    if not ok:
        sys.exit(f"ERROR: invalid --{name} value {value!r}")


# A branch name usable as a feature key: the characters a PR heading code span
# and a ledger filename can carry safely, with no '.'/'..' path segment.
_BRANCH = re.compile(r"^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$")


def _is_branch(value) -> bool:
    return (isinstance(value, str) and bool(_BRANCH.match(value))
            and not any(seg in (".", "..") for seg in value.split("/")))


def feature_key(issue, branch):
    """The ledger key of a feature: its issue number when it has a valid one,
    else `branch-<name>` (with '/' encoded, so the key stays one filename), else
    None. Pure — callers decide whether to warn."""
    if _is_number(issue):
        return issue
    if _is_branch(branch):
        return "branch-" + branch.replace("/", "%2F")
    return None


def feature_label(key: str) -> str:
    """How a feature key reads in the PR cost heading: `#87` or a code-spanned branch."""
    if _is_number(key):
        return f"#{key}"
    return f"`{key[len('branch-'):].replace('%2F', '/')}`"


def resolve_key(args):
    """The feature key from a command's --issue/--branch, warning (never
    exiting) about a value that cannot be used."""
    if args.issue is not None and not _is_number(args.issue):
        print(f"WARNING: ignoring invalid --issue value {args.issue!r} (not an issue number).")
    if args.branch is not None and not _is_branch(args.branch) and not _is_number(args.issue):
        print(f"WARNING: ignoring unusable --branch value {args.branch!r}.")
    return feature_key(args.issue, args.branch)


def utc_now() -> datetime:
    """The current time, timezone-aware UTC — the single clock every command reads."""
    return datetime.now(timezone.utc)


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


def transcript_paths(session_id: str) -> list[Path]:
    """Return the session's transcripts: the main one PLUS every subagent
    transcript — or an empty list when the session has none. Claude Code stores a
    spawned subagent's messages in a SEPARATE file under
    <project>/<session-id>/subagents/... — not in the main transcript — so pricing
    only the main file would miss all subagent (reviewer, builder, verifier, ...)
    token usage, which typically dominates a skill run."""
    mains = glob.glob(str(Path.home() / ".claude" / "projects" / "*" / f"{session_id}.jsonl"))
    if not mains:
        return []
    # If the same session id somehow appears twice, the largest file is the real run.
    main = max(mains, key=lambda p: os.path.getsize(p))
    project = os.path.dirname(main)
    # Subagent transcripts (recursively, in case of nested subagents).
    subs = glob.glob(os.path.join(project, session_id, "**", "*.jsonl"), recursive=True)
    return [Path(main)] + [Path(s) for s in subs]


def find_transcripts(session_id: str) -> list[Path]:
    """`transcript_paths`, exiting when the session has no transcript."""
    paths = transcript_paths(session_id)
    if not paths:
        sys.exit(f"ERROR: no transcript found for session {session_id}")
    return paths


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


def tier_rates(entry: dict, prompt_tokens: int) -> dict:
    """The rates that apply to one request of `prompt_tokens` prompt length.

    A flat entry applies at every length. A `prompt_tiers` entry is an ordered
    list: the first tier whose `max_prompt_tokens` is at least the prompt length
    applies, and the last tier carries no cap. Claude Haiku 5.5 is priced this
    way — "up to 100,000" and "over 100,000" prompt tokens, where a request's
    prompt length counts all of its input tokens, including cache reads and
    cache writes, and each request is priced on its own. Source:
    https://platform.claude.com/docs/en/about-claude/pricing#long-context-pricing"""
    tiers = entry.get("prompt_tiers")
    if not tiers:
        return entry
    for tier in tiers:
        cap = tier.get("max_prompt_tokens")
        if cap is None or prompt_tokens <= cap:
            return tier
    return tiers[-1]


def cost_from_transcripts(paths: list[Path], pricing: dict, since=None, until=None) -> dict:
    """Sum tokens across the main transcript AND every subagent transcript,
    and price them. When `since` is set, only messages timestamped at or after
    it are counted — the slice belonging to a single skill invocation; when
    `until` is set, only messages timestamped before it — the end of a stopped
    run's slice, so the slice is the half-open `[since, until)`. Model ids
    are canonicalised first (see `canonical_model`), so a dated snapshot and its
    alias price identically. A model still absent from `pricing` is priced at
    the latest known rate of its own family (recorded in `fallback_models`);
    only a model with no family match at all is dropped (recorded in
    `unknown_models`). Each message is priced on its own, at the tier its prompt
    length selects (see `tier_rates`). Returns totals + fallbacks + unknowns."""
    total_cost = 0.0
    unknown_models = []
    fallback_models = []
    tokens_total = dict.fromkeys(TOKEN_FIELDS, 0)
    # The rate entry each canonical model id resolved to (None = unpriceable),
    # resolved once per model so fallbacks/unknowns are recorded once.
    resolved: dict = {}
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
                # Slice to this invocation: skip anything before the mark or at/after
                # the slice end (and any line we cannot place on the timeline).
                if since is not None and (ts is None or ts < since):
                    continue
                if until is not None and (ts is None or ts >= until):
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
                t = dict.fromkeys(TOKEN_FIELDS, 0)
                t["input"] = usage.get("input_tokens", 0)
                t["output"] = usage.get("output_tokens", 0)
                t["cache_read"] = usage.get("cache_read_input_tokens", 0)
                cc = usage.get("cache_creation") or {}
                if cc:
                    t["cache_write_5m"] = cc.get("ephemeral_5m_input_tokens", 0)
                    t["cache_write_1h"] = cc.get("ephemeral_1h_input_tokens", 0)
                else:
                    # No TTL breakdown available — price all cache writes at the 5m rate.
                    t["cache_write_5m"] = usage.get("cache_creation_input_tokens", 0)
                for k in TOKEN_FIELDS:
                    tokens_total[k] += t[k]

                if model not in resolved:
                    rates = pricing.get(model)
                    if not rates:
                        # Unpriced model: fall back to the latest known price of
                        # the same family rather than dropping its tokens.
                        family = model_family(model)
                        alt = latest_priced_in_family(family, pricing) if family else None
                        if alt:
                            rates = pricing[alt]
                            fallback_models.append({"model": model, "priced_as": alt, "family": family})
                        else:
                            unknown_models.append(model)
                    resolved[model] = rates
                entry = resolved[model]
                if not entry:
                    continue
                # Prompt length counts every input token, cache reads and writes included.
                prompt = t["input"] + sum(t[f] for f in CACHE_FIELDS)
                rates = tier_rates(entry, prompt)
                for k in TOKEN_FIELDS:
                    total_cost += t[k] / 1_000_000 * rates[k]

    return {
        "total_cost_usd": round(total_cost, 4),
        "tokens": tokens_total,
        "fallback_models": fallback_models,
        "unknown_models": unknown_models,
    }


def ledger_path(project: str, key: str) -> Path:
    return LEDGER_ROOT / project / f"{key}.jsonl"


def mark_path(session: str, skill: str) -> Path:
    return MARK_ROOT / f"{session}-{skill}.start"


def boundary_path(session: str) -> Path:
    """The session's boundary log — one ISO timestamp per `mark`/`record` (and
    per close of a marker with no later boundary). Not a `*.start` file, so the
    marker sweeps never pick it up."""
    return MARK_ROOT / f"{session}.boundaries"


def append_boundary(session: str, ts: datetime) -> None:
    path = boundary_path(session)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as fh:
        fh.write(ts.isoformat() + "\n")


def read_boundaries(session: str) -> list[datetime]:
    """The session's boundary timestamps, sorted; unparseable lines are skipped."""
    path = boundary_path(session)
    if not path.exists():
        return []
    stamps = (parse_ts(line.strip()) for line in path.read_text().splitlines())
    # A tz-less stamp cannot be ordered against the aware ones: drop it.
    return sorted(ts for ts in stamps if ts is not None and ts.tzinfo is not None)


def read_marker(path: Path) -> dict:
    """A marker's fields. A legacy marker holds only a bare ISO timestamp — it
    yields `start` alone, with no attribution."""
    text = path.read_text().strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict):
        data = {"start": text}
    return {
        "session": data.get("session"),
        "skill": data.get("skill"),
        "project": data.get("project"),
        "issue": data.get("issue"),
        "branch": data.get("branch"),
        "start": parse_ts(data.get("start")),
    }


def append_ledger(project: str, key: str, skill: str, result: dict, config: dict, ts: datetime) -> float:
    """Append one priced run to the ledger of feature `key`; return its EUR cost."""
    cost_eur = round(result["total_cost_usd"] * config["usd_to_eur"], 4)
    entry = {
        "skill": skill,
        "feature": key,
        "total_cost_eur": cost_eur,
        "total_cost_usd": result["total_cost_usd"],
        "tokens": result["tokens"],
        "timestamp": ts.isoformat(),
    }
    path = ledger_path(project, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as fh:
        fh.write(json.dumps(entry) + "\n")
    return cost_eur


def close_marker(path: Path, config: dict, now: datetime) -> None:
    """Record an open marker — a run that stopped without `record` — as a
    `<skill>-stopped` ledger row, then remove it. Never exits: a marker that
    cannot be priced is reported and discarded."""
    m = read_marker(path)
    # Re-validated like the write path, since the values become ledger paths and
    # PR-table rows — but discarded rather than exited on, so a bad marker never
    # aborts the command that found it.
    key = feature_key(m["issue"], m["branch"])
    attributable = (
        m["start"] is not None and m["start"].tzinfo is not None
        and key is not None
        and all(_is_safe(m[k]) for k in ("session", "skill", "project"))
    )
    if not attributable:
        print(f"NOTE: open marker {path.name} carries no valid attribution (issue or branch, session, skill, project or start missing or malformed) — its stopped run's cost cannot be attributed; discarded.")
        path.unlink()
        return

    # End the slice at the next PAF boundary in that session, so it never
    # overlaps a run recorded after it. With none, end it now and log the close
    # as a boundary: a still-running run of that session that records later
    # then starts here instead of re-pricing this slice.
    later = [ts for ts in read_boundaries(m["session"]) if ts > m["start"]]
    until = later[0] if later else now

    paths = transcript_paths(m["session"])
    if not paths:
        if not later:
            append_boundary(m["session"], now)
        print(f"WARNING: no transcript for session {m['session']} — the stopped {m['skill']} run's cost cannot be recovered; marker discarded.")
        path.unlink()
        return
    result = cost_from_transcripts(paths, config["models"], since=m["start"], until=until)
    skill = f"{m['skill']}-stopped"
    cost_eur = append_ledger(m["project"], key, skill, result, config, now)
    # Logged only once the row is written, so a failure above leaves the marker
    # and the boundary log as they were and a retry slices the same way.
    if not later:
        append_boundary(m["session"], now)
    path.unlink()
    print(f"Recovered stopped run: {skill} for feature {feature_label(key)} — €{cost_eur:.2f}")


def cmd_mark(args) -> None:
    _validate("session", args.session)
    _validate("skill", args.skill)
    key = resolve_key(args)
    if args.project is not None:
        _validate("project", args.project)
    now = utc_now()
    append_boundary(args.session, now)
    path = mark_path(args.session, args.skill)
    # An open marker here is an earlier run of this skill in this session that
    # stopped without recording: recover it before it is overwritten. Its slice
    # ends at the first boundary after it — at the latest, the one just logged.
    if path.exists():
        try:
            close_marker(path, load_config(), now)
        except (OSError, ValueError, KeyError, TypeError, SystemExit) as exc:
            # Best effort: an unreadable marker must not stop this run's mark.
            print(f"WARNING: could not recover open marker {path.name}: {exc}")
    marker = {
        "session": args.session,
        "skill": args.skill,
        "project": args.project or project_slug(),
        "issue": args.issue if _is_number(args.issue) else None,
        "branch": args.branch if _is_branch(args.branch) else None,
        "start": now.isoformat(),
    }
    path.write_text(json.dumps(marker))
    print(f"Marked {args.skill} invocation start at {now.isoformat()}")
    if key is None:
        print(f"NOTE: no issue number or branch given — if this {args.skill} run stops, its cost cannot be attributed to a feature.")


def cmd_record(args) -> None:
    _validate("session", args.session)
    _validate("skill", args.skill)
    key = resolve_key(args)
    if args.project is not None:
        _validate("project", args.project)
    project = args.project or project_slug()
    config = load_config()

    # Slice to this invocation: an explicit --since wins; otherwise use the
    # marker `mark` wrote at the skill's first step; otherwise the session's last
    # boundary (the previous PAF run's end, or the close time of this run's
    # marker by another session's `aggregate`). With none, the whole transcript
    # is priced (fallback for a standalone/manual run).
    since = None
    marker = mark_path(args.session, args.skill)
    if args.since:
        since = parse_ts(args.since)
    elif marker.exists():
        since = read_marker(marker)["start"]
    else:
        boundaries = read_boundaries(args.session)
        if boundaries:
            since = boundaries[-1]
            print(f"NOTE: no invocation-start marker for '{args.skill}' — pricing from the session's last boundary ({since.isoformat()}). Ensure step 1 ran `mark`.")

    if since is None:
        print(
            f"WARNING: no invocation-start marker for session/skill '{args.skill}' and no --since given — "
            f"pricing the WHOLE session transcript (may over-count if skills share a session). "
            f"Ensure step 1 ran `mark`."
        )

    result = cost_from_transcripts(find_transcripts(args.session), config["models"], since=since)
    now = utc_now()
    if key is None:
        # Reported below, but with no feature key there is no ledger to add it to.
        cost_eur = round(result["total_cost_usd"] * config["usd_to_eur"], 4)
    else:
        cost_eur = append_ledger(project, key, args.skill, result, config, now)
    append_boundary(args.session, now)

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
    if key is None:
        print("NOTE: no issue number or branch given — this cost was not added to any feature ledger.")


def close_feature_markers(project: str, key: str) -> None:
    """Close every open marker of this project + feature, in any session, into a
    `<skill>-stopped` row. check-out's own marker is never among them: its step-6
    `record` already removed it before `aggregate` runs (and if that record
    failed, recovering it as `check-out-stopped` is the right outcome)."""
    if not MARK_ROOT.exists():
        return
    config = None
    now = utc_now()
    for path in sorted(MARK_ROOT.glob("*.start")):
        try:
            m = read_marker(path)
            if m["project"] != project or feature_key(m["issue"], m["branch"]) != key:
                continue
            if config is None:
                config = load_config()
            close_marker(path, config, now)
        except (OSError, ValueError, KeyError, TypeError, SystemExit) as exc:
            # Best effort: one unreadable marker must not abort the PR step.
            print(f"WARNING: could not close open marker {path.name}: {exc}")


def cmd_aggregate(args) -> None:
    key = resolve_key(args)
    if args.project is not None:
        _validate("project", args.project)
    if key is None:
        print("No issue number or branch given — no feature cost ledger to aggregate.")
        return
    project = args.project or project_slug()
    close_feature_markers(project, key)
    path = ledger_path(project, key)
    if not path.exists():
        print(f"No cost ledger found for feature {feature_label(key)} (nothing to aggregate).")
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

    lines = [f"## Factory run cost — feature {feature_label(key)}", ""]
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

    mk = sub.add_parser("mark", help="record this invocation's start for later slicing (recovering a stopped run)")
    mk.add_argument("--session", required=True)
    mk.add_argument("--skill", required=True)
    mk.add_argument("--issue", help="the feature's issue number, so a stopped run can be attributed")
    mk.add_argument("--branch", help="the feature branch — the feature key when there is no issue number")
    mk.add_argument("--project")
    mk.set_defaults(func=cmd_mark)

    rec = sub.add_parser("record", help="price this run's slice and append to the ledger")
    rec.add_argument("--session", required=True)
    rec.add_argument("--skill", required=True)
    rec.add_argument("--issue")
    rec.add_argument("--branch", help="the feature key when there is no issue number")
    rec.add_argument("--project")
    rec.add_argument("--since", help="ISO 8601 slice start (overrides the mark marker)")
    rec.set_defaults(func=cmd_record)

    agg = sub.add_parser("aggregate", help="close the feature's open markers and sum its ledger for the PR body")
    agg.add_argument("--issue")
    agg.add_argument("--branch", help="the feature key when there is no issue number")
    agg.add_argument("--project")
    agg.add_argument("--cleanup", action="store_true")
    agg.set_defaults(func=cmd_aggregate)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
