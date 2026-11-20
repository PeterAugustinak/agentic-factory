# implement-issue

Human-facing documentation for the `implement-issue` skill. The operational definition is [`skills/paf-implement-issue/SKILL.md`](../../skills/paf-implement-issue/SKILL.md); this file is not loaded by Claude at run time.

## Purpose

Turn an issue into implemented, verified, deep-reviewed code on a feature branch, left **uncommitted** for you to review. It is the **second** skill in the factory: it runs after `/paf:create-issue`, and `/paf:check-out` ships what it leaves.

## How to invoke

Run `/paf:implement-issue <issue-number>`.

## How it works

1. **Read.** The skill fetches the issue via `paf-vcs`. An issue with no acceptance criteria (a missing or empty section) stops the run at once with `Result: failure`. It also checks whether `claude` is on `PATH`, and reads the Bash timeout limit for the agent steps.
2. **Validate.** Only for an issue without the `## For implementation agent` line: `issue-validator` checks it, and the skill posts its findings and asks you whether a factual blocker is folded into the plan or stops the run. An uncovered behaviour case always stops it.
3. **Plan.** In plan mode the skill starts from the agent section's Context and Scope of changes as a hint (the real code wins where they differ, unreported), and sweeps every place a changed fact is stated. It builds only what the issue states; a must-have item the issue missed is listed in its own plan part for your approval. Only something the code makes impossible stops the run with `Result: failure`.
4. **Approve.** The plan opens with a short summary (what changes and where), then any must-have items beyond the issue, with the exact edits below it. You approve it or ask for changes.
5. **Branch.** The skill creates `feature/<issue>-<short-description>` from the base branch.
6. **Build.** The skill applies the approved edits in the same context, with no re-exploration.
7. **Verify.** `implementation-verifier` runs the scoped tests, plus the UI check command for a UI change. A failure is fixed in the main thread, at most twice.
8. **Review.** Five reviewers run in parallel. All of them read the same review input file, which a helper writes under `~/.claude/paf/review-input/` (never in the project) straight from the fetched issue and git: the issue verbatim, the created files, and a change manifest whose removed lines are kept exactly as printed. Each prompt holds only the reviewer's lens and the file's path. The file is deleted once the reviewers finish, and a leftover is wiped at the start of the next run; a helper failure stops the run with `Result: failure`. What the issue decides or puts out of scope (its Decisions and Constraints) is not a finding.
9. **Triage.** `full-stack-dev` decides which findings to apply and applies them. It fixes defects only; a warning that would add behaviour beyond the plan is skipped.
10. **Re-verify.** `implementation-verifier` runs again; `full-stack-dev` fixes a failure, at most twice. The reviewers are never re-run.
11. **Acceptance check.** `quality-assurer` checks every acceptance criterion. An unmet one is fixed in the main thread and re-verified, at most twice; then the run stops with `Result: failure`. If the fix needs a must-have item beyond the issue, you are asked whether to add it; no (or no answer) stops the run.
12. **Hand off.** The changes stay uncommitted. The skill prints Result, How to test (at most three steps), one line each only when they apply (code location, UI not verified, behaviour changes beyond the plan, each skipped error), and Next last, with a blank line between fields. Nothing else. The code location line, `Code location: <worktree top-level folder> (git worktree)`, comes directly after How to test, only when the run is in a linked git worktree and something was built, on a success or a failure; if the detection fails the line is left out and the run continues. What the run set up for How to test (ignored files, local database records, running services) stays in place, and How to test names it; a set-up file git reports as untracked is removed before the review, with How to test saying how to create it. The run removes or stops only what it set up itself and testing does not need, never anything else, on a success or a failure. It records a fingerprint so `/paf:check-out` can skip its safety-net review when nothing changed, and saves a snapshot of the code under `~/.claude/paf/` (never in the project) so `/paf:check-out` can suggest conventions from what you change afterwards. A failure of either prints its error and the run continues.
13. **Cost.** The run's cost goes into the feature's cost ledger.

**How agents are started.** Every agent except `full-stack-dev` is started as a headless `claude -p --agent <name>` run by [`paf-headless.py`](../../skills/paf-shared/paf-headless.py). All agents of one step run side by side from one Bash call, and their reports come back together in the same turn, with the same prompts and input as through the Agent tool. Each run is prompt-free and limited to its agent's tools, and it is stopped before the Bash time limit and when you interrupt the call. A run that is stopped, fails, or hits a permission denial is re-run once through the Agent tool, so you get the same prompt as before. When `claude` is not on `PATH`, every agent is started through the Agent tool. `full-stack-dev` is always started through the Agent tool.

```text
/paf:implement-issue <n>
        |
        v
  [skill] read issue --- no acceptance criteria --> STOP
        |
        |--- no agent section --> [agent] issue-validator --> factual blocker? ask you
        |                                                      uncovered case? STOP
        v
  [skill + human] plan mode (impossible? STOP) --> ExitPlanMode (summary first) --> branch --> build
        |
        v
  [agent] implementation-verifier ---- fail --> main-thread fix (max 2) --> STOP
        |
        v
  [agents] 5 reviewers in parallel --> [agent] full-stack-dev triage --> re-verify (max 2)
        |
        v
  [agent] quality-assurer ---- unmet --> main-thread fix + re-verify (max 2; must-have beyond issue? ask you) --> STOP
        |
        v
  [skill] short hand-off (uncommitted) --> fingerprint --> snapshot --> cost
```

Legend: `[skill]` = orchestration and external I/O done by the skill itself in the main thread; `[agent]` = work delegated to a specialist agent; `[agents]` = several agents; `[skill + human]` = a skill step that pauses for your input; `STOP` = the run halts and hands back to you, to fix the cause and re-run the skill. The diagram reads top to bottom.

## Agents used

| Agent | Step(s) | What it does here |
| --- | --- | --- |
| [`issue-validator`](../../agents/issue-validator.md) | 2 | Only for an issue without the `## For implementation agent` line: checks the approach's technical validity against official docs and the repository, and its completeness. |
| [`implementation-verifier`](../../agents/implementation-verifier.md) | 7, 10, 11 | Runs the project's test command scoped to the changed area, plus the UI check command for a UI change; re-runs after each fix. |
| [`senior-engineer-reviewer`](../../agents/senior-engineer-reviewer.md) | 8 | Reviews functional correctness. |
| [`code-simplifier`](../../agents/code-simplifier.md) | 8 | Reviews for unnecessary complexity. |
| [`security-engineer`](../../agents/security-engineer.md) | 8 | Reviews security. |
| [`test-coverage-reviewer`](../../agents/test-coverage-reviewer.md) | 8 | Reviews for meaningful test coverage. |
| [`conformance-reviewer`](../../agents/conformance-reviewer.md) | 8 | Reviews conformance to project rules, framework features and repository patterns. |
| [`full-stack-dev`](../../agents/full-stack-dev.md) | 9, 10 | Triages the review findings and applies the worthwhile ones (9); fixes a re-verify failure (10). |
| [`quality-assurer`](../../agents/quality-assurer.md) | 11 | Checks every acceptance criterion against the changed files. |

## Human interception points

- **Factual validator blocker** (`AskUserQuestion`): only for an issue without the agent section; an uncovered case stops without asking.
- **Plan approval** (`ExitPlanMode`): you approve the plan, including any must-have items beyond the issue; nothing is written before.
- **Must-have item beyond the issue** (`AskUserQuestion`): only when the acceptance check's fix needs one; no or no answer stops the run.
- **Skill boundary**: you review the uncommitted diff, which is the record of every applied fix, and then run `/paf:check-out`.

When verification, or the acceptance check, still fails after its cap, the run stops and prints the same hand-off with `Result: failure` and the blocker under Next. An issue with no acceptance criteria, something the issue requires that the code makes impossible, or a declined must-have item stops the same way. Design rationale (why plan mode, the two fix owners, the loop caps): [`architecture.md` §2](../architecture.md#2-skill-to-agent-orchestration) and [§5](../architecture.md#5-loop-cap-escalation-and-cost-reporting).

## Cost reporting

The run is priced from its start mark onward, its headless agent runs included, and appended to the per-feature ledger that `/paf:check-out` totals. A run that stops early is still recovered into the ledger as an `implement-issue-stopped` row. How it is priced: [`paf-report-cost.py`](../../skills/paf-shared/paf-report-cost.py); design rationale: [`architecture.md` §5, Cost reporting](../architecture.md#cost-reporting).

## Related files

- [`agents/`](../../agents/): `issue-validator`, `implementation-verifier`, the five reviewers, `full-stack-dev`, and `quality-assurer`.
- [`skills/paf-shared/output-contract.md`](../../skills/paf-shared/output-contract.md): how agent output is parsed.
- [`skills/paf-shared/paf-headless.py`](../../skills/paf-shared/paf-headless.py): starts agents as headless runs.
- [`skills/paf-shared/paf-review-input.py`](../../skills/paf-shared/paf-review-input.py): the reviewers' shared input file.
- [`skills/paf-shared/paf-fingerprint.py`](../../skills/paf-shared/paf-fingerprint.py): the hand-off fingerprint.
- [`skills/paf-shared/paf-snapshot.py`](../../skills/paf-shared/paf-snapshot.py): the hand-off snapshot.
- [`skills/paf-shared/paf-report-cost.py`](../../skills/paf-shared/paf-report-cost.py): cost reporting.
