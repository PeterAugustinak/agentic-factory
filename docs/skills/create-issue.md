# create-issue

Human-facing documentation for the `create-issue` skill. The operational definition is [`skills/paf-create-issue/SKILL.md`](../../skills/paf-create-issue/SKILL.md); this file is not loaded by Claude at run time.

## Purpose

Turn a discussed feature idea into an issue, check its facts, and post it. It is the **first** skill in the factory; `/paf:implement-issue` builds what it posts.

## How to invoke

Discuss the idea in the conversation first (freely, or with `/grill-me`), then run `/paf:create-issue [optional short idea]`. The skill runs inline, so the discussion is its input. The argument is just a seed.

## The issue it writes

- **Human part**: Problem, Goal, Approach, and Acceptance criteria. It is short, with no code and no file lists.
- **`## For implementation agent`**: the technical context (Context, Decisions, Constraints, Scope of changes, Pitfalls, References). Empty subsections are left out. It is context, not a plan; planning happens in `/paf:implement-issue`.

## How it works

1. **Ask.** If the idea is unclear, the skill asks a few questions. It then asks you about every decision it would otherwise make itself, so the issue holds only what you confirmed.
2. **Draft.** `issue-writer` drafts the issue. If it finds a decision nobody made, the skill asks you and redrafts.
3. **Validate.** `issue-validator` checks the factual claims against official docs and the repository, and that every behaviour case a Decision or acceptance criterion touches is covered.
4. **Fix.** An uncovered case is a blocker: the skill first asks you how to settle it. The skill fixes blockers in a redraft and re-checks only what changed, at most twice. If a blocker remains after that, the run **stops and posts nothing**. Each warning is then either corrected in place or added as a `Validator note:` under References.
5. **Post.** The skill posts the issue directly, with **no review gate**, and prints its URL.
6. **Cost.** The run's cost goes into the feature's cost ledger.

```text
idea discussed --> /paf:create-issue
                        |
                        v
  [skill + human] clarity + decision questions
                        |
                        v
  [agent] issue-writer ---- undecided? --> ask, redraft
                        |
                        v
  [agent] issue-validator
     |--- blocker --> redraft, re-check delta (max 2) --> still blocked: STOP
     v
  [skill] fold warnings --> post via paf-vcs --> cost
```

## Human interception points

- **Questions before drafting** (and between drafts): clarity questions, every open decision, and how to settle each uncovered case the validator finds.
- **Skill boundary**: you review the posted issue, then decide when to run `/paf:implement-issue`.

`/paf:implement-issue` sees the `## For implementation agent` heading and skips re-validation. Issues without it (hand-written ones) are validated there. Design rationale: [`architecture.md` → issue-validator escalation](../architecture.md#issue-validator-escalation).

## Cost reporting

The run is priced from its start mark onward (the discussion before it is not counted) and appended to the per-feature ledger that `/paf:check-out` totals. A run that stops before posting has no issue number, so its cost is dropped. Details: [`architecture.md` §5](../architecture.md#5-loop-cap-escalation-and-cost-reporting).

## Related files

- [`agents/issue-writer.md`](../../agents/issue-writer.md) and [`agents/issue-validator.md`](../../agents/issue-validator.md): the two agents.
- [`skills/paf-shared/output-contract.md`](../../skills/paf-shared/output-contract.md): how agent output is parsed.
- [`skills/paf-shared/paf-report-cost.py`](../../skills/paf-shared/paf-report-cost.py): cost reporting.
