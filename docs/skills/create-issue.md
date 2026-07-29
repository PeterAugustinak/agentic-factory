# create-issue

Human-facing documentation for the `create-issue` skill. The operational definition is [`skills/paf-create-issue/SKILL.md`](../../skills/paf-create-issue/SKILL.md); this file explains how the skill works and is not loaded by Claude at run time.

## Purpose

Turn a feature idea into a well-structured issue, reviewed by the developer, and post it. `create-issue` is the **first** skill in the factory — its output is the approved issue that `/paf:implement-issue` later builds.

## When and how to invoke

Discuss the idea first in the conversation (freely, or with `/grill-me` until it is clear), then run:

```
/paf:create-issue [optional short idea]
```

The skill runs **inline in the current conversation**, so the prior discussion is already its input — you do not pass the whole idea as an argument. The optional argument is just a seed.

## How it works

`create-issue` is an orchestrator running in the main thread. It does the VCS I/O itself (via the `paf-vcs` adapter — `gh` on GitHub projects, `glab` on GitLab projects) and delegates the drafting to the `issue-writer` agent and the pre-post approach validation to the `issue-validator` agent.

1. **Clarity gate.** The skill checks whether the idea (from the conversation and/or the seed argument) is specified enough to write a good issue — clear problem, intended outcome, rough acceptance criteria. If it is thin, it asks a few targeted questions and waits. Deep elicitation is expected to happen in the conversation beforehand; this gate is a lightweight safety check, not a full grill.
2. **Draft.** The `issue-writer` agent (read-only) drafts a structured issue and returns it only — it never posts. The body follows a **fixed six-section template**, always present and in that order: `## Problem` → `## Goal` → `## Approach` → `## Scope of changes` → `## Acceptance criteria` → `## References`. The title follows a type-based convention (`Bug: …` for defects, an imperative "what will be built" statement otherwise), and the agent also suggests labels.
3. **Validate the approach.** The `issue-validator` agent (web access + read-only repo search) receives the **whole** draft and checks its load-bearing claims against **both** authoritative docs — CLI flags, API signatures, library behaviour, including the cited spec's caveats and scope limits — **and** the actual repository: do the named paths exist, does the described current behaviour match the code, is the approach feasible against the existing implementation. It returns findings. Blockers are folded back into a re-draft and re-validated (capped at two rounds); any residual blocker is surfaced at the review gate. This is **shift-left**: an approach defect is caught before the issue is posted, not left for `/paf:implement-issue` to discover. The skill never narrows the validator's scope and never skips this step — a draft with no external claims still makes claims about the repository.
4. **Review gate.** The developer reviews the **already-validated** draft, plus any carried-forward findings. Changes loop back to a re-draft (and re-validate); approval moves forward. Nothing is posted before approval.
5. **Post.** The skill creates the issue via `paf-vcs` (auto-detecting the provider from the repo's `origin` remote), using labels that exist in the repo, and prints the issue URL.
6. **Cost.** The skill runs the shared cost helper, which prices only this invocation's slice of the session (from the step-1 mark onward) and appends the run to the per-feature cost ledger.

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
| [agent] issue-validator                      |   |
|   check approach vs docs + repository        |   |
+----------------------------------------------+   |
     |--- blocker --> re-draft + re-validate ------+  (cap 2 rounds;
     |                                             |   residual blocker
     v  (validated; warnings/blockers carried)    |   surfaced at gate)
+----------------------------------------------+   |
| [human gate] developer reviews the validated |   |
|   draft + carried-forward findings           |   |
+----------------------------------------------+   |
     +--- changes requested -----------------------+
     |
     v  (approved)
+----------------------------------------------+
| [skill] post issue via paf-vcs; print URL    |
+----------------------------------------------+
     |
     v
+----------------------------------------------+
| [skill] report per-invocation cost (EUR);    |
|         append to per-feature cost ledger    |
+----------------------------------------------+
```

## Agents used

- **`issue-writer`** (Sonnet, read-only) — synthesises the discussed idea into the structured issue draft and returns it via the [output contract](../../skills/paf-shared/output-contract.md); the skill parses that, gates it on the developer, and posts it.
- **`issue-validator`** (Opus, web access + read-only repo search) — independently checks the drafted approach's load-bearing claims against authoritative docs **and** the actual repository *before* posting, returning findings via the same output contract. The skill folds blockers back into a re-draft (capped) and surfaces the rest at the review gate.

Planning and implementation belong to `/paf:implement-issue`. Note that `issue-validator` runs **twice** across the pipeline by design — here at authoring time (catch defects before posting) and again inside `/paf:implement-issue` (re-check the *posted* issue, which may have been edited between skills). See [`architecture.md` → issue-validator escalation](../architecture.md#issue-validator-escalation).

## Human interception points

- **Clarity gate** (step 1) — an in-skill pause when the idea is underspecified.
- **Draft review** (step 4) — the mandatory gate before anything is posted; the developer approves or requests changes, reviewing an already validated draft (docs + repository) plus any carried-forward findings.
- **Skill boundary** — after the issue is posted, the developer decides when to run `/paf:implement-issue`. The gap between skills is itself a review point (`architecture.md` §2).

## Cost reporting

The skill marks its invocation start at step 1, and the final step runs [`skills/paf-shared/paf-report-cost.py`](../../skills/paf-shared/paf-report-cost.py) in `record` mode. It:

- prices only this invocation's slice of the session transcript — from the step-1 mark onward, main-thread + any agent usage — using [`pricing.json`](../../skills/paf-shared/pricing.json) and converts the total to **EUR** (a model missing from the price table is priced at the latest known same-family rate, with a note to update it, rather than dropped);
- appends an entry to the per-feature ledger at `~/.claude/paf/costs/<project>/<issue>.jsonl` (user scope — no footprint in the target repository);
- keyed by the **issue number**, so `/paf:implement-issue` and `/paf:check-out` add to the same ledger and `/paf:check-out` reports the **total** feature cost in the PR.

Because the run is sliced from the mark, discussion that happened *before* `/paf:create-issue` was invoked is not counted — the cost reflects the issue-drafting work itself, not the preceding idea conversation.

## Related files

- [`skills/paf-create-issue/SKILL.md`](../../skills/paf-create-issue/SKILL.md) — the operational definition (what Claude executes).
- [`skills/paf-shared/output-contract.md`](../../skills/paf-shared/output-contract.md) — agent output parsing rules.
- [`skills/paf-shared/paf-report-cost.py`](../../skills/paf-shared/paf-report-cost.py) / [`pricing.json`](../../skills/paf-shared/pricing.json) — cost reporting.
- [`agents/issue-writer.md`](../../agents/issue-writer.md) — the drafting agent definition.
- [`agents/issue-validator.md`](../../agents/issue-validator.md) — the pre-post approach-validation agent definition.
- [`docs/architecture.md`](../architecture.md) — the factory-wide design this skill follows.
```
