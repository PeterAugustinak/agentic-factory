# create-issue

Human-facing documentation for the `create-issue` skill. The operational definition is [`skills/paf-create-issue/SKILL.md`](../../skills/paf-create-issue/SKILL.md); this file is not loaded by Claude at run time.

## Purpose

Turn a discussed feature idea into an issue, check its facts, and post it. When the topic is too big for one issue, it splits it and posts several linked issues in one run. It is the **first** skill in the factory; `/paf:implement-issue` builds what it posts.

## How to invoke

Discuss the idea in the conversation first (freely, or with `/grill-me`), then run `/paf:create-issue [optional short idea]`. The skill runs inline, so the discussion is its input. The argument is just a seed.

## The issue it writes

- **Human part**: Problem, Goal, Approach, and Acceptance criteria. It is short, with no code and no file lists.
- **`## For implementation agent`**: the technical context (Context, Decisions, Constraints, Scope of changes, Pitfalls, References). Empty subsections are left out. It is context, not a plan; planning happens in `/paf:implement-issue`.

## How it works

1. **Split?** The skill judges, from the conversation, whether the topic should be several issues (INVEST: each part delivered and tested on its own). If not, you see nothing about it. If so, it shows a `Why split:` line and one line per part, and you choose `Split as shown`, `Keep as one issue`, or type changes (the revised split is shown again until you choose). In a split run every step below runs for each part.
2. **Ask.** If the idea is unclear, the skill asks a few questions. It then asks you about every decision it would otherwise make itself, so the issue holds only what you confirmed. In a split run, the decisions of all parts are asked in one round, grouped by part.
3. **Draft.** `issue-writer` drafts the issue once. A decision nobody made is kept for the question phase after validation.
4. **Validate.** `issue-validator` checks the factual claims against official docs and the repository, and that every behaviour case a Decision or acceptance criterion touches is covered.
5. **Ask and update.** Each finding goes to exactly one place: a wrong fact with its correct value is fixed in place, a new fact the implementer needs goes into Context, an open choice (an undecided decision, an uncovered case, a correction needing your choice) is asked, and anything else is dropped. With nothing to ask, the fixes are applied directly. Otherwise you get all the questions in one phase, one by one; then the writer redrafts once and only the changed claims are re-checked. A new open choice from that starts another phase, at most two updates; after that the run **stops and posts nothing**. In a split run, the questions of all parts are asked in the one phase, grouped by part, and a part still blocked means nothing is posted.
6. **Post.** The skill posts the issue directly, with **no review gate**, and prints its URL. In a split run, it posts only after every part has passed validation, in dependency order, adding a `Depends on #N` line (a part that depends on another) or `Related to #N` lines (an independent part, for the siblings already posted) to each part's human part, and lists every URL in order. If posting fails part-way, it stops and prints the URLs already posted and the bodies of the unposted parts.
7. **Cost.** The run's cost goes into the feature's cost ledger — in a split run, in equal shares across the posted issues.

```text
idea discussed --> /paf:create-issue
                        |
                        v
  [skill + human] split triage -- split? --> confirm / change parts
                        |                    (every step below per part)
                        v
  [skill + human] clarity + decision questions
                        |
                        v
  [agent] issue-writer (draft once)
                        |
                        v
  [agent] issue-validator
                        |
                        v
  [skill] route findings -- open choice? --> [human] one question phase
                        |                     --> redraft + delta check (max 2 updates) --> still open: STOP
                        v
  [skill] apply fixes --> post via paf-vcs (all parts, in dependency order) --> cost
```

## Human interception points

- **Split confirmation**: when the skill proposes a split, you confirm it, change it, or keep one issue.
- **Questions before drafting and after validation**: clarity questions and every open decision up front, then one phase per update for every open choice the draft and validation leave (undecided decisions, uncovered cases, corrections needing your choice).
- **Skill boundary**: you review the posted issue (or issues), then decide when to run `/paf:implement-issue`.

`/paf:implement-issue` sees the `## For implementation agent` heading and skips re-validation. Issues without it (hand-written ones) are validated there. Design rationale: [`architecture.md` → issue-validator escalation](../architecture.md#issue-validator-escalation).

## Cost reporting

The run is priced from its start mark onward (the discussion before it is not counted) and appended to the per-feature ledger that `/paf:check-out` totals. A split run's cost and token counts are shared equally across the issues it posted (the remainder goes to the first), and the terminal shows one cost block with the run total. A run that stops before posting has no issue number, so its cost is dropped; a split run whose posting fails part-way records its cost only on the issues already posted. Details: [`architecture.md` §5](../architecture.md#5-loop-cap-escalation-and-cost-reporting).

## Related files

- [`agents/issue-writer.md`](../../agents/issue-writer.md) and [`agents/issue-validator.md`](../../agents/issue-validator.md): the two agents.
- [`skills/paf-shared/output-contract.md`](../../skills/paf-shared/output-contract.md): how agent output is parsed.
- [`skills/paf-shared/paf-report-cost.py`](../../skills/paf-shared/paf-report-cost.py): cost reporting.
