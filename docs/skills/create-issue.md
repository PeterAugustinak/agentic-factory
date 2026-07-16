# create-issue

Human-facing documentation for the `create-issue` skill. The operational definition is [`skills/paf-create-issue/SKILL.md`](../../skills/paf-create-issue/SKILL.md); this file explains how the skill works and is not loaded by Claude at run time.

## Purpose

Turn a feature idea into a well-structured GitHub issue, reviewed by the developer, and post it. `create-issue` is the **first** skill in the factory — its output is the approved issue that `/paf:implement-issue` later builds.

## When and how to invoke

Discuss the idea first in the conversation (freely, or with `/grill-me` until it is clear), then run:

```
/paf:create-issue [optional short idea]
```

The skill runs **inline in the current conversation**, so the prior discussion is already its input — you do not pass the whole idea as an argument. The optional argument is just a seed.

## How it works

`create-issue` is an orchestrator running in the main thread. It does the GitHub I/O itself and delegates only the drafting to the `issue-writer` agent.

1. **Clarity gate.** The skill checks whether the idea (from the conversation and/or the seed argument) is specified enough to write a good issue — clear problem, intended outcome, rough acceptance criteria. If it is thin, it asks a few targeted questions and waits. Deep elicitation is expected to happen in the conversation beforehand; this gate is a lightweight safety check, not a full grill.
2. **Draft.** The `issue-writer` agent (read-only) drafts a structured issue: title, description, acceptance criteria, suggested labels. It returns the draft only — it never posts.
3. **Review gate.** The developer reviews the draft. Changes loop back to a re-draft; approval moves forward. Nothing is posted before approval.
4. **Post.** The skill creates the issue via `gh` on the repo from `CLAUDE.md`, using labels that exist in the repo, and prints the issue URL.
5. **Cost + time.** The skill runs the shared cost helper, which prices the whole session (including the idea discussion) and appends the run to the per-feature cost ledger.

## Orchestration

```text
(idea discussed in the conversation — freely or via /grill-me)
     |
     v
/paf:create-issue [optional seed]
     |
     v
+----------------------------------------------+
| [skill] clarity gate: is the idea specified  |
|         enough to write a good issue?        |
+----------------------------------------------+
     |--- no --> ask targeted questions, wait for the developer
     |
     v  (clear)
+----------------------------------------------+
| [agent] issue-writer                         | <-+
|   draft structured issue (read-only)         |   |
+----------------------------------------------+   |
     |                                             |
     v                                             |
+----------------------------------------------+   |
| [human gate] developer reviews the draft     |   |
+----------------------------------------------+   |
     +--- changes requested -----------------------+
     |
     v  (approved)
+----------------------------------------------+
| [skill] post issue via gh; print URL         |
+----------------------------------------------+
     |
     v
+----------------------------------------------+
| [skill] report cost + wall-clock (EUR);      |
|         append to per-feature cost ledger    |
+----------------------------------------------+
```

## Agents used

- **`issue-writer`** (Sonnet, read-only) — the only agent. It synthesises the discussed idea into the structured issue draft and returns it via the [output contract](../../skills/paf-shared/output-contract.md); the skill parses that, gates it on the developer, and posts it.

No other agents run in this skill: validation, planning, and implementation belong to `/paf:implement-issue`.

## Human interception points

- **Clarity gate** (step 1) — an in-skill pause when the idea is underspecified.
- **Draft review** (step 3) — the mandatory gate before anything is posted; the developer approves or requests changes.
- **Skill boundary** — after the issue is posted, the developer decides when to run `/paf:implement-issue`. The gap between skills is itself a review point (`architecture.md` §2).

## Cost and time reporting

The final step runs [`skills/paf-shared/paf-report-cost.py`](../../skills/paf-shared/paf-report-cost.py) in `record` mode. It:

- prices the run from the session transcript (main-thread + any agent usage) using [`pricing.json`](../../skills/paf-shared/pricing.json), converts the total to **EUR**, and derives wall-clock from the transcript's first→last timestamps — so the idea-discussion time and tokens are included;
- appends an entry to the per-feature ledger at `~/.claude/paf/costs/<project>/<issue>.jsonl` (user scope — no footprint in the target repository);
- keyed by the **issue number**, so `/paf:implement-issue` and `/paf:check-out` add to the same ledger and `/paf:check-out` reports the **total** feature cost in the PR.

This rests on one assumption: the create-issue-phase session is focused on that one feature (discuss it, then create the issue). Working on several unrelated features in a single session before creating an issue would blend their cost into this run.

## Related files

- [`skills/paf-create-issue/SKILL.md`](../../skills/paf-create-issue/SKILL.md) — the operational definition (what Claude executes).
- [`skills/paf-shared/output-contract.md`](../../skills/paf-shared/output-contract.md) — agent output parsing rules.
- [`skills/paf-shared/paf-report-cost.py`](../../skills/paf-shared/paf-report-cost.py) / [`pricing.json`](../../skills/paf-shared/pricing.json) — cost + time reporting.
- [`agents/issue-writer.md`](../../agents/issue-writer.md) — the agent definition.
- [`docs/architecture.md`](../architecture.md) — the factory-wide design this skill follows.
```
