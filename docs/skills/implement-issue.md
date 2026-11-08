# implement-issue

Human-facing documentation for the `implement-issue` skill. The operational definition is [`skills/paf-implement-issue/SKILL.md`](../../skills/paf-implement-issue/SKILL.md); this file is not loaded by Claude at run time.

## Purpose

Turn an issue into implemented, verified, deep-reviewed code on a feature branch, left **uncommitted** for you to review. It is the **second** skill in the factory: it runs after `/paf:create-issue`, and `/paf:check-out` ships what it leaves.

## How to invoke

Run `/paf:implement-issue <issue-number>`.

## How it works

1. **Read.** The skill fetches the issue via `paf-vcs`.
2. **Validate.** Only for an issue without the `## For implementation agent` line: `issue-validator` checks it, and the skill posts its findings and asks you whether a factual blocker is folded into the plan or stops the run. An uncovered behaviour case always stops it.
3. **Plan.** In plan mode the skill starts from the agent section's Context and Scope of changes as a hint (the real code wins where they differ, unreported), and sweeps every place a changed fact is stated. It never decides an open point: one stops the run with `Result: failure`.
4. **Approve.** The plan opens with a short summary (what changes and where), with the exact edits below it. You approve it or ask for changes.
5. **Branch.** The skill creates `feature/<issue>-<short-description>` from the base branch.
6. **Build.** The skill applies the approved edits in the same context, with no re-exploration.
7. **Verify.** `implementation-verifier` runs the scoped tests, plus the UI check command for a UI change. A failure is fixed in the main thread, at most twice.
8. **Review.** Five reviewers run in parallel. Each gets the issue verbatim and a change manifest whose removed lines are passed exactly as printed, never summarized. What the issue decides or puts out of scope (its Decisions and Constraints) is not a finding.
9. **Triage.** `full-stack-dev` decides which findings to apply and applies them. It fixes defects only; a warning that would add behaviour beyond the plan is skipped.
10. **Re-verify.** `implementation-verifier` runs again; `full-stack-dev` fixes a failure, at most twice. The reviewers are never re-run.
11. **Acceptance check.** `quality-assurer` checks every acceptance criterion. An unmet one is fixed in the main thread and re-verified, at most twice; then the run stops with `Result: failure`.
12. **Hand off.** The changes stay uncommitted. The skill prints Result, How to test (at most three steps), one line each only when they apply (UI not verified, behaviour changes beyond the plan, each skipped error), and Next last, with a blank line between fields. Nothing else. It records a fingerprint so `/paf:check-out` can skip its safety-net review when nothing changed.
13. **Cost.** The run's cost goes into the feature's cost ledger.

```text
/paf:implement-issue <n>
        |
        v
  [skill] read issue --- no agent section --> [agent] issue-validator --> factual blocker? ask you
        |                                                                uncovered case? STOP
        v
  [skill + human] plan mode (open point? STOP) --> ExitPlanMode (summary first) --> branch --> build
        |
        v
  [agent] implementation-verifier ---- fail --> main-thread fix (max 2) --> STOP
        |
        v
  [agents] 5 reviewers in parallel --> [agent] full-stack-dev triage --> re-verify (max 2)
        |
        v
  [agent] quality-assurer ---- unmet --> main-thread fix + re-verify (max 2) --> STOP
        |
        v
  [skill] short hand-off (uncommitted) --> fingerprint --> cost
```

## Human interception points

- **Factual validator blocker** (`AskUserQuestion`): only for an issue without the agent section; an uncovered case stops without asking.
- **Plan approval** (`ExitPlanMode`): nothing is written before you approve.
- **Skill boundary**: you review the uncommitted diff, which is the record of every applied fix, and then run `/paf:check-out`.

When verification, or the acceptance check, still fails after its cap, the run stops and prints the same hand-off with `Result: failure` and the blocker under Next. An open point found while planning stops the same way. Design rationale (why plan mode, the two fix owners, the loop caps): [`architecture.md` §2](../architecture.md#2-skill-to-agent-orchestration) and [§5](../architecture.md#5-loop-cap-escalation-and-cost-reporting).

## Cost reporting

The run is priced from its start mark onward and appended to the per-feature ledger that `/paf:check-out` totals. A run that stops early is still recovered into the ledger as an `implement-issue-stopped` row. Details: [`architecture.md` §5](../architecture.md#5-loop-cap-escalation-and-cost-reporting).

## Related files

- [`agents/`](../../agents/): `issue-validator`, `implementation-verifier`, the five reviewers, `full-stack-dev`, and `quality-assurer`.
- [`skills/paf-shared/output-contract.md`](../../skills/paf-shared/output-contract.md): how agent output is parsed.
- [`skills/paf-shared/paf-fingerprint.py`](../../skills/paf-shared/paf-fingerprint.py): the hand-off fingerprint.
- [`skills/paf-shared/paf-report-cost.py`](../../skills/paf-shared/paf-report-cost.py): cost reporting.
