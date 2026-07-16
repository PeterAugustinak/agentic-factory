# implement-issue

Human-facing documentation for the `implement-issue` skill. The operational definition is [`skills/paf-implement-issue/SKILL.md`](../../skills/paf-implement-issue/SKILL.md); this file explains how the skill works and is not loaded by Claude at run time.

## Purpose

Take an approved GitHub issue from *validated approach* to *implemented, verified code on a feature branch*. `implement-issue` is the **second** skill — it runs after `/paf:create-issue` and before `/paf:check-out`. Its output is verified, **uncommitted** work on a feature branch that the developer reviews, then finishes with `/paf:check-out`.

## When and how to invoke

Once an issue exists and its approach is sound enough to build:

```
/paf:implement-issue <issue-number>
```

## How it works

`implement-issue` is an orchestrator running in the main thread. It chains five specialist agents, owns all GitHub and git I/O, enforces the plan-review gate, and applies the loop caps and escalation policy.

1. **Read the issue** (skill) via `gh`.
2. **Validate the approach** — `issue-validator` checks technical validity against authoritative docs. The skill posts the findings as an issue comment; a **blocker** (`severity: error`) stops the run and sends the developer back to the issue. Minor findings (`warning`) are carried into the plan.
3. **Explore** — `code-explorer` summarises the relevant code.
4. **Plan** — `implementation-planner` produces a full plan (files, changes, test strategy), folding in any minor findings.
5. **Plan-review gate** — the developer approves the plan or requests changes (loops back to re-plan). Nothing is built before approval.
6. **Branch** (skill) — create `feature/<issue>-<short-description>` from the base branch.
7. **Implement** — `full-stack-dev` executes the approved plan on the branch.
8. **Verify** — `implementation-verifier` runs the project's tests + linter scoped to the changed area. On failure the builder is re-invoked with the failure output, up to a cap; if it still fails, the run stops and escalates.
9. **Hand off** (skill) — leave the verified changes **uncommitted** on the branch so the developer reviews them as working-tree changes (no commit, no push, no PR — that's `/paf:check-out`).
10. **Cost + time** (skill) — append the run to the per-feature cost ledger.

## Orchestration

```text
/paf:implement-issue <issue-number>
     |
     v
+----------------------------------------------+
| [skill] read the issue via gh                |
+----------------------------------------------+
     |
     v
+----------------------------------------------+
| [agent] issue-validator                      |
|   verify approach vs docs -> findings        |
+----------------------------------------------+
     |
     v
+----------------------------------------------+
| [skill] post findings comment on the issue   |
+----------------------------------------------+
     |
     |--- severity: error (blocker) --> STOP: developer updates issue & re-runs
     |
     v  (warning / none -> carried to the planner)
+----------------------------------------------+
| [agent] code-explorer                        |
|   summarise the relevant code                |
+----------------------------------------------+
     |
     v
+----------------------------------------------+
| [agent] implementation-planner               | <-+
|   produce plan (incl. minor findings)        |   |
+----------------------------------------------+   |
     |                                             |
     v                                             |
+----------------------------------------------+   |
| [human gate] developer reviews + confirms    |   |
+----------------------------------------------+   |
     +--- changes requested -----------------------+
     |
     v  (approved)
+----------------------------------------------+
| [skill] create feature/<issue>-<desc> branch |
+----------------------------------------------+
     |
     v
+----------------------------------------------+
| [agent] full-stack-dev                       | <-+
|   implement the plan on the branch           |   |
+----------------------------------------------+   |
     |                                             |
     v                                             |
+----------------------------------------------+   |
| [agent] implementation-verifier              |   |
|   run scoped tests + linter                  |   |
+----------------------------------------------+   |
     +--- fail, retries < 2 (with failure output)--+
     |--- fail, retries exhausted -> STOP: escalate failure report
     |
     v  (pass)
+----------------------------------------------+
| [skill] leave changes UNCOMMITTED on branch  |
|   for review (no commit / push / PR)         |
+----------------------------------------------+
     |
     v
+----------------------------------------------+
| [skill] report cost + wall-clock (EUR);      |
|         append to per-feature cost ledger    |
+----------------------------------------------+
```

## Agents used

| Agent | Role in this skill |
|---|---|
| `issue-validator` | Verifies the issue's approach against authoritative docs; findings gate the run. |
| `code-explorer` | Summarises the relevant code for the planner. |
| `implementation-planner` | Produces the implementation plan (incl. carried-forward minor findings). |
| `full-stack-dev` | Implements the approved plan on the branch; re-invoked on verification failure. |
| `implementation-verifier` | Runs scoped tests + linter and reports pass/fail. |

Agents never call `gh`, change git state, or orchestrate each other — the skill owns all of that.

## Human interception points

- **Plan-review gate** — the mandatory in-skill gate; the developer approves the plan (or loops it back) before any code is written.
- **Validator blocker** — an `error` finding halts the run and returns control to the developer at the issue.
- **Skill boundary** — after the skill finishes, the developer reviews the branch's uncommitted changes (interception 2 in `architecture.md` §2) and then runs `/paf:check-out`.

## Loop caps and escalation

Per `architecture.md` §5:
- **Retry cap.** On verification failure, `full-stack-dev` is re-invoked with the failure output, at most **twice** (3 runs total). The builder never validates its own fix — `implementation-verifier` re-runs each time.
- **STOP conditions** (each halts and escalates to the developer, who fixes the cause and re-runs): a validator blocker; verification still failing after the retry cap; malformed/missing agent output.
- **Scoped verification.** `implementation-verifier` runs a **targeted subset** of the suite (the changed area), keeping the retry loop fast; the **full** suite runs later at `/paf:check-out`.

## Git handling

The skill owns git state (`architecture.md` §2). It creates the `feature/<issue>-<short-description>` branch from the base branch (`CLAUDE.md`) and implements on it, but **leaves the changes uncommitted**. This is deliberate: uncommitted working-tree changes are the clearest review surface — the developer sees every added/modified file highlighted in the IDE, with per-file diffs, instead of having to diff `HEAD` against the base. Because the project uses **squash merge**, deferring the commit costs nothing in history.

`/paf:check-out` then commits the implementation plus any approved review fixes, pushes the branch, and opens the PR. The intended flow is tight — implement → review → check-out — so the uncommitted window is short.

## Cost and time reporting

The final step runs [`skills/paf-shared/paf-report-cost.py`](../../skills/paf-shared/paf-report-cost.py) in `record` mode, keyed by the **issue number** — the same per-feature ledger `/paf:create-issue` wrote to and `/paf:check-out` will total for the PR. Cost is converted to **EUR**; wall-clock is derived from the transcript. See [`docs/skills/create-issue.md`](create-issue.md) for the ledger details.

## Related files

- [`skills/paf-implement-issue/SKILL.md`](../../skills/paf-implement-issue/SKILL.md) — the operational definition.
- [`skills/paf-shared/output-contract.md`](../../skills/paf-shared/output-contract.md) — agent output parsing rules.
- [`skills/paf-shared/paf-report-cost.py`](../../skills/paf-shared/paf-report-cost.py) / [`pricing.json`](../../skills/paf-shared/pricing.json) — cost + time reporting.
- [`agents/issue-validator.md`](../../agents/issue-validator.md), [`agents/code-explorer.md`](../../agents/code-explorer.md), [`agents/implementation-planner.md`](../../agents/implementation-planner.md), [`agents/full-stack-dev.md`](../../agents/full-stack-dev.md), [`agents/implementation-verifier.md`](../../agents/implementation-verifier.md) — the agent definitions.
- [`docs/architecture.md`](../architecture.md) — the factory-wide design this skill follows.
```
