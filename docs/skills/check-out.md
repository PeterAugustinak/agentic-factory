# check-out

Human-facing documentation for the `check-out` skill. The operational definition is [`skills/paf-check-out/SKILL.md`](../../skills/paf-check-out/SKILL.md); this file is not loaded by Claude at run time.

## Purpose

Ship a reviewed feature: run the final checks, then commit, push, and open the MR/PR with the **whole feature's** cost in its description. It is the **third and final** skill: it runs after you have reviewed what `/paf:implement-issue` left on the branch. It is a confirmation-and-ship gate, not a review-and-fix stage, so it never re-opens the code.

## How to invoke

Run `/paf:check-out [optional issue-number]` on the feature branch once you have reviewed the change. Invoking it is the go-ahead; it asks no confirmation. The issue number comes from the branch name (`feature/<issue>-<…>`); pass it only to override.

## How it works

1. **Gather.** The skill reads the issue, computes the change as the branch's diff against the base (committed or not), and compares the branch with `/paf:implement-issue`'s hand-off fingerprint.
2. **Safety net.** Only when the content changed since the hand-off (or the fingerprint cannot confirm it did not): `senior-engineer-reviewer` runs as a high-level pass over the whole diff, looking for regressions in your hand-edits. It is asked to report only critical regressions, as errors, and no warnings. It reads the issue verbatim and the change manifest from the review input file, which a helper writes under `~/.claude/paf/review-input/` (never in the project) and deletes once the review is done; a helper failure stops the run. What its Decisions and Constraints, with the binding Approach and Acceptance criteria, decide or put out of scope is not a finding (for an issue without the agent section, whatever its body states). An `error` stops the run. On a fingerprint match it is skipped, silently.
3. **Spec check.** `quality-assurer` confirms every acceptance criterion; an unmet one stops the run. For an issue with no acceptance criteria (a missing or empty section), it checks against the issue body instead, silently.
4. **Pre-merge.** The project's full pre-merge command runs. On failure, the project's optional auto-fix command runs once and the check re-runs once; anything still failing stops the run.
5. **Commit & push.** Whatever is still uncommitted is committed; the branch is pushed.
6. **Cost.** The run's cost goes into the feature's cost ledger.
7. **MR/PR.** The skill totals the feature's cost and opens the MR/PR from a fixed description template, written to a temporary file so the cost table stays verbatim. Its Deviations section names only what the issue's Approach, Decisions, Constraints, or acceptance criteria state and the code does differently.
8. **Output.** On success: `Result: success`, the MR/PR link, and one line per deviation from the standard run, only when it applies (the safety-net review ran, the pre-merge auto-fix ran and what it changed), then this run's cost. On any stop: `Result: failure`, `Blocker:`, `Next:`, then the failing findings verbatim, one per line. A blank line separates every field. Nothing else.

```text
/paf:check-out
      |
      v
  [skill] read issue, diff vs base, fingerprint check
      |--- changed --> [agent] senior-engineer-reviewer --- error --> STOP
      v
  [agent] quality-assurer --- unmet --> STOP
      |
      v
  [skill] pre-merge --- fail --> auto-fix once, re-check --> still failing: STOP
      |
      v
  [skill] commit, push --> cost --> open MR/PR --> short output
```

## Human interception points

- **Skill boundary before it**: you review `/paf:implement-issue`'s output; running `/paf:check-out` is the go-ahead.
- **Blocker hand-back**: every stop returns control to you. `check-out` has no fix loop; you fix the cause and re-run it.
- **Skill boundary after it**: you review and merge the MR/PR.

Design rationale (the safety net, the fingerprint skip, the auto-fix posture): [`architecture.md` §5](../architecture.md#5-loop-cap-escalation-and-cost-reporting).

## Cost reporting

The run is priced from its start mark onward, then the whole feature (`create-issue`, `implement-issue`, `check-out`, plus any stopped runs) is totalled into the MR/PR description and the ledger is cleared. A successful run ends with this run's cost in the terminal, like the other skills; a stopped run shows none. Details: [`architecture.md` §5](../architecture.md#5-loop-cap-escalation-and-cost-reporting).

## Related files

- [`agents/senior-engineer-reviewer.md`](../../agents/senior-engineer-reviewer.md) and [`agents/quality-assurer.md`](../../agents/quality-assurer.md): the two agents.
- [`skills/paf-shared/output-contract.md`](../../skills/paf-shared/output-contract.md): how agent output is parsed.
- [`skills/paf-shared/paf-review-input.py`](../../skills/paf-shared/paf-review-input.py): the reviewer's input file.
- [`skills/paf-shared/paf-fingerprint.py`](../../skills/paf-shared/paf-fingerprint.py): the hand-off fingerprint.
- [`skills/paf-shared/paf-report-cost.py`](../../skills/paf-shared/paf-report-cost.py): cost reporting.
