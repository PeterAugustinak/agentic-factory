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
3. **Validate the approach.** The `issue-validator` agent (web access + read-only repo search) receives the **whole** draft and checks its load-bearing claims against **both** authoritative docs — CLI flags, API signatures, library behaviour, including the cited spec's caveats and scope limits — **and** the actual repository: do the named paths exist, does the described current behaviour match the code, is the approach feasible against the existing implementation. Findings are bounded to factual/feasibility defects — implementation guidance (how to build it well) is out of scope. It returns findings, and a single response can mix an error with warnings. Blockers are folded back into a re-draft, and only the changed claims are re-validated (capped at two rounds) — never the whole draft again; every warning seen along the way in that correction pass (even one raised alongside a blocker in the same round) joins a pending list that is folded once the pass concludes. Because `issue-writer` regenerates the body from scratch each call, it never carries an earlier fold's notes forward on its own — so every re-invocation re-appends whatever was already folded onto the fresh draft before anything else, distinct from the pending list, so nothing is folded twice. This is **shift-left**: an approach defect is caught before the issue is posted, not left for `/paf:implement-issue` to discover. The skill never narrows the validator's scope and never skips this step — a draft with no external claims still makes claims about the repository.
4. **Review gate.** The developer reviews the **already-validated** draft — its warnings already folded into the draft's References section, each tagged `Validator note:` — plus any unresolved blocker still standing after the correction cap. Changes loop back to a re-draft (carrying forward the already-folded notes, and a delta-only re-validation with the same pending-list-then-fold handling); approval moves forward. Nothing is posted before approval.
5. **Post.** The skill creates the issue via `paf-vcs` (auto-detecting the provider from the repo's `origin` remote), using labels that exist in the repo, and prints the issue URL. Every posted issue has passed both the validator and the review gate, so the skill appends a visible marker — a lone final line reading `PAF` — to the body. It is `/paf:implement-issue`'s signal that PAF already validated and the developer already approved this issue, so it can skip its own validation pass (a plain footer keeps `paf-vcs view-issue` simple — no raw-body retrieval needed). (It's appended even when the developer approved despite a residual blocker at the gate: that blocker was adjudicated here.)
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
|   draft structured issue (read-only); on a   |   |
|   redraft, first re-append whatever the      |   |
|   skill already folded into References,      |   |
|   since regeneration does not preserve it    |   |
+----------------------------------------------+   |
     |                                             |
     v                                             |
+----------------------------------------------+   |
| [agent] issue-validator                      |   |
|   check approach vs docs + repository;       |   |
|   this round's warnings join the pending     |   |
|   list for the current correction pass       |   |
+----------------------------------------------+   |
     |--- error --> re-draft + re-validate --------+  (cap 2 rounds;
     |              (delta only, scoped to the     |   delta only;
     |               changed claims)               |   residual blocker
     v  (no error, or the 2-round cap is exhausted)   surfaced at gate)
+----------------------------------------------+
| [skill] fold this pass's pending list of     |
|   warnings into the draft's References,      |
|   each line tagged `Validator note:` — no    |
|   developer adjudication                     |
+----------------------------------------------+
     |
     v
+----------------------------------------------+   |
| [human gate] developer reviews the drafted   |   |
|   issue + any unresolved blocker             |   |
+----------------------------------------------+   |
     +--- changes requested: re-draft + -----------+
          re-validate delta only (same
          re-append-then-fold handling)
     |
     v  (approved)
+----------------------------------------------+
| [skill] post issue via paf-vcs; print URL    |
+----------------------------------------------+
     |
     v
+----------------------------------------------+
| [skill] report per-invocation cost + tokens; |
|         append to per-feature cost ledger    |
+----------------------------------------------+
```

## Agents used

- **`issue-writer`** (Sonnet, read-only) — synthesises the discussed idea into the structured issue draft and returns it via the [output contract](../../skills/paf-shared/output-contract.md); the skill parses that, gates it on the developer, and posts it.
- **`issue-validator`** (Opus, web access + read-only repo search) — independently checks the drafted approach's load-bearing claims against authoritative docs **and** the actual repository *before* posting, bounded to factual/feasibility defects, and returns findings via the same output contract; a single response can carry an error alongside warnings. The skill folds blockers back into a re-draft and delta-re-validates only the changed claims (capped); every warning across the current correction pass's rounds is kept in a pending list and, once that pass's loop concludes, folded directly into the draft's References section (tagged `Validator note:`) — never surfaced at the review gate. Because `issue-writer` regenerates the body from scratch, every re-invocation re-appends whatever was already folded onto the fresh draft first, so a note already committed is never lost to regeneration nor folded twice.

Planning and implementation belong to `/paf:implement-issue`. `issue-validator` runs here at authoring time to catch defects before posting; `/paf:implement-issue` re-runs it **only for issues PAF did not already validate** (hand-written, or created outside PAF), detected via the trailing `PAF` marker this skill adds. A PAF-authored issue is not re-validated — its `create-issue` pass plus the developer's approval already covered it. See [`architecture.md` → issue-validator escalation](../architecture.md#issue-validator-escalation).

## Human interception points

- **Clarity gate** (step 1) — an in-skill pause when the idea is underspecified.
- **Draft review** (step 4) — the mandatory gate before anything is posted; the developer approves or requests changes, reviewing an already validated draft (docs + repository) whose warnings are already folded into its References section, plus any unresolved blocker still standing after the correction cap.
- **Skill boundary** — after the issue is posted, the developer decides when to run `/paf:implement-issue`. The gap between skills is itself a review point (`architecture.md` §2).

## Cost reporting

The skill marks its invocation start at step 1, and the final step runs [`skills/paf-shared/paf-report-cost.py`](../../skills/paf-shared/paf-report-cost.py) in `record` mode. It:

- prices only this invocation's slice of the session transcript — from the step-1 mark onward, main-thread + any agent usage — using [`pricing.json`](../../skills/paf-shared/pricing.json), converts the total to **EUR**, and prints the token breakdown (in / out / cached / total) alongside it. Model ids are canonicalised first — a trailing `-YYYYMMDD` snapshot date is stripped, since pricing is per model and not per snapshot, which is why the price table's keys must be dateless. A model still missing from the table after that is priced at the latest known same-family rate, with a note to add it, rather than dropped;
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
