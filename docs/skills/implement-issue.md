# implement-issue

Human-facing documentation for the `implement-issue` skill. The operational definition is [`skills/paf-implement-issue/SKILL.md`](../../skills/paf-implement-issue/SKILL.md); this file explains how the skill works and is not loaded by Claude at run time.

## Purpose

Take an approved issue from *validated approach* to *implemented, verified, reviewed code on a feature branch*. `implement-issue` is the **second** skill — it runs after `/paf:create-issue` and before `/paf:check-out`. Its output is verified, deep-reviewed, **uncommitted** work on a feature branch that the developer reviews, then finishes with `/paf:check-out`.

The deep review lives here, before the hand-off, rather than in `/paf:check-out`: reviewed *after* the developer's manual review, its fixes changed code the developer had already signed off and forced them to re-review it. See [`architecture.md` §2](../architecture.md#2-skill-to-agent-orchestration).

## When and how to invoke

Once an issue exists and its approach is sound enough to build:

```
/paf:implement-issue <issue-number>
```

## How it works

`implement-issue` is an orchestrator running in the main thread. It validates the approach with an agent, then **plans and implements in one shared context using native plan mode**, verifies with an agent, and finally deep-reviews the change with the review agents and has the findings triaged and applied. It owns all VCS and git I/O (via the `paf-vcs` adapter — `gh` on GitHub projects, `glab` on GitLab projects), enforces the plan-review gate, and applies the loop caps and escalation policy.

1. **Read the issue** (skill) via `paf-vcs`.
2. **Validate the approach** — `issue-validator` checks technical validity against authoritative docs and the repository. The skill posts **only the actual findings** — one line each, and no comment when there are none. A **blocker** (`severity: error`) stops the run and sends the developer back to the issue. Minor findings (`warning`) are carried into the plan.
3. **Plan** (skill, main thread) — `EnterPlanMode`: in one read-only context, explore the codebase and produce a **concrete** plan (exact files and edits, test strategy), folding in any minor findings. Nothing is written yet.
4. **Plan-review gate** (`ExitPlanMode`) — the developer approves the plan or requests changes (revise in plan mode and re-present). Nothing is built before approval.
5. **Branch** (skill) — after approval, create `feature/<issue>-<short-description>` from the base branch.
6. **Implement** (skill, same context) — apply the approved plan's exact edits on the branch. Because planning and building share the context, this is applying what's already decided — no re-exploration.
7. **Verify** — `implementation-verifier` runs the project's tests + linter scoped to the changed area. On failure the **same main-thread context that built the code** (now in edit mode) applies the fix (it still holds the plan and the edits — no re-exploration, and no cold builder agent) and re-verifies, up to a cap; if it still fails, the run stops and escalates.
8. **Deep review in parallel** — `senior-engineer-reviewer`, `code-simplifier`, `security-engineer`, `test-coverage-reviewer` run concurrently over the change (the diff against base **plus** the list of files created in step 6, since new files are untracked and absent from the diff); the skill aggregates their findings. No findings takes the **skip path** straight to the hand-off.
9. **Triage & apply** — `full-stack-dev` receives **all** findings and decides which are worth applying, then applies them: `error` findings apply by default (a skip must be loud and justified), `warning` findings are its discretion. The skill surfaces its applied-vs-skipped report to the developer — the developer doesn't pre-select fixes; their manual review is the curation point.
10. **Re-verify** — `implementation-verifier` runs again, since step 9 may have changed the code and tests are the gate. On failure `full-stack-dev` fixes from its output and it re-verifies, up to a cap; the reviewers are **not** re-run.
11. **Hand off** (skill) — leave the verified, reviewed changes **uncommitted** on the branch so the developer reviews them as working-tree changes (no commit, no push, no MR/PR — that's `/paf:check-out`).
12. **Cost** (skill) — append this invocation's cost to the per-feature cost ledger.

### Why plan mode

Planning and building run in the main thread via native plan mode rather than as a separate `implementation-planner` agent handing off to a separate `full-stack-dev` agent. Two subagents don't share context, so the builder would start **cold** and re-derive what the planner already worked out — exploring the repo twice. Plan mode keeps exploration, the concrete plan, and execution in **one context**, so an approved plan applies in seconds; `EnterPlanMode`/`ExitPlanMode` are main-thread-only, so this lives in the skill's main thread. Full rationale: [`architecture.md` §2](../architecture.md#2-skill-to-agent-orchestration).

**Two fix loops, two owners — one rule.** The verify-fix loop (step 7) is fixed **in the main thread**; the review-fix loop (steps 9–10) is delegated to `full-stack-dev`. That is the same rule applied twice, not an inconsistency. Step 7 repairs the build itself, and this context still holds the plan and the exact edits — a cold builder agent would re-derive them, which is precisely what plan mode exists to avoid. Applying a *discrete list of review findings* is different: each finding names its own location and remedy, so there is nothing to re-derive and no cold-context penalty — and delegating it puts those writes back under the hook's agent-scoped path containment, which main-thread writes don't get. Keep work in-context when losing the context would cost re-derivation; delegate it when it wouldn't.

## Orchestration

```text
/paf:implement-issue <issue-number>
     |
     v
+----------------------------------------------+
| [skill] read the issue via paf-vcs            |
+----------------------------------------------+
     |
     v
+----------------------------------------------+
| [agent] issue-validator                      |
|   verify vs docs + repo -> findings          |
+----------------------------------------------+
     |
     v
+----------------------------------------------+
| [skill] post findings comment on the issue   |
+----------------------------------------------+
     |
     |--- severity: error (blocker) --> STOP: developer updates issue & re-runs
     |
     v  (warning / none -> carried into the plan)
+----------------------------------------------+
| [skill] EnterPlanMode: explore + write a     | <-+
|   CONCRETE plan (one read-only context)      |   |
+----------------------------------------------+   |
     |                                             |
     v                                             |
+----------------------------------------------+   |
| [human gate] ExitPlanMode: developer reviews |   |
|   + approves the plan                        |   |
+----------------------------------------------+   |
     +--- changes requested (revise in plan mode) -+
     |
     v  (approved -> same context, edit mode)
+----------------------------------------------+
| [skill] create feature/<issue>-<desc> branch |
+----------------------------------------------+
     |
     v
+----------------------------------------------+
| [skill] apply the approved plan's exact      |
|   edits on the branch (no re-exploration)    |
+----------------------------------------------+
     |
     v
+----------------------------------------------+
| [agent] implementation-verifier              | <-+
|   run scoped tests + linter                  |   |
+----------------------------------------------+   |
     +--- fail, retry<2: main-thread fix + reverify+
     |--- fail, retries exhausted -> STOP: escalate failure report
     |
     v  (pass)
+----------------------------------------------+
| [agent] deep review — run in parallel:       |
|   - senior-engineer-reviewer (functional)    |
|   - code-simplifier (complexity)             |
|   - security-engineer (security)             |
|   - test-coverage-reviewer (test coverage)   |
|   (diff vs base + files created in step 6)   |
+----------------------------------------------+
     +--- no findings ------------------------------------+
     |                                                    |
     v  (findings)                                        |
+----------------------------------------------+          |
| [agent] full-stack-dev — TRIAGE + apply:     |          |
|   error -> apply (loud, justified skip);     |          |
|   warning -> discretion. Report applied vs   |          |
|   skipped -> surfaced to the developer       |          |
+----------------------------------------------+          |
     |                                                    |
     v                                                    |
+----------------------------------------------+          |
| [agent] implementation-verifier (re-verify)  | <-+      |
+----------------------------------------------+   |      |
     +--- fail, retry<2: full-stack-dev fix -------+      |
     |--- fail, retries exhausted -> STOP: escalate       |
     |    (reviewers are never re-run)                    |
     |                                                    |
     v  (pass)                                            |
+----------------------------------------------+       <--+
| [skill] leave changes UNCOMMITTED on branch  |
|   for review (no commit / push / MR/PR)      |
+----------------------------------------------+
     |
     v
+----------------------------------------------+
| [skill] report per-invocation cost (EUR);    |
|         append to per-feature cost ledger    |
+----------------------------------------------+
```

## Agents used

| Agent | Role in this skill |
|---|---|
| `issue-validator` | Verifies the issue's approach against authoritative docs and the repository; findings gate the run. |
| `implementation-verifier` | Runs scoped tests + linter and reports pass/fail — after the build, and again after the review fixes. |
| `senior-engineer-reviewer` | Functional-correctness review of the implemented change (parallel). |
| `code-simplifier` | Complexity / DRY / readability review (parallel). |
| `security-engineer` | Security review (parallel). |
| `test-coverage-reviewer` | Meaningful test-coverage review of the change's tests (parallel). |
| `full-stack-dev` | Triages the aggregated review findings and applies the worthwhile ones; fixes any resulting verification failure (skipped if the review found nothing). |

The reviewers run **concurrently**; the rest run in sequence. Planning and implementation are **not** delegated to agents — they run in the main thread via native plan mode (see "Why plan mode" above). None of the delegated agents sits on the plan→build boundary, so each keeps its own isolated context without cost. Agents never call `gh`/`glab`, change git state, or orchestrate each other — the skill owns all of that.

## Human interception points

- **Plan-review gate** (`ExitPlanMode`) — the mandatory in-skill gate; the developer approves the concrete plan (or loops it back for revision in plan mode) before any code is written.
- **Validator blocker** — an `error` finding halts the run and returns control to the developer at the issue.
- **Skill boundary** — after the skill finishes, the developer reviews the branch's uncommitted changes (interception 2 in `architecture.md` §2) and then runs `/paf:check-out`.

## Loop cap and escalation

Per `architecture.md` §5 there are **two** fix loops, each capped the same way:
- **Verify-fix loop (main thread).** On verification failure, the **same main-thread context that built the code** (now in edit mode) applies the fix (informed by the failure output) and re-verifies, at most **twice** — never a cold builder agent, which would re-derive the change.
- **Review-fix loop (`full-stack-dev`).** After the review fixes are applied, `implementation-verifier` re-runs; on failure `full-stack-dev` fixes from its output and it re-verifies, at most **twice**. The reviewers run **exactly once** per invocation and are never re-run — the second look at the code is the developer's manual review plus `/paf:check-out`'s safety-net review.
- **No self-validation.** Whoever applied a fix never validates it — `implementation-verifier` re-runs as a separate agent each time.
- **STOP conditions** (each halts and escalates to the developer, who fixes the cause and re-runs): a validator blocker; verification still failing after either retry cap; malformed/missing agent output from any agent.
- **Scoped verification.** `implementation-verifier` runs a **targeted subset** of the suite (the changed area), keeping both loops fast; the **full** suite runs later at `/paf:check-out`.

## Git handling

The skill owns git state (`architecture.md` §2). After the plan is approved it creates the `feature/<issue>-<short-description>` branch from the base branch (`CLAUDE.md`) and implements on it, but **leaves the changes uncommitted**. This is deliberate: uncommitted working-tree changes are the clearest review surface — the developer sees every added/modified file highlighted in the IDE, with per-file diffs, instead of having to diff `HEAD` against the base. Because the project uses **squash merge**, deferring the commit costs nothing in history.

`/paf:check-out` then commits the implementation plus the review fixes, pushes the branch, and opens the MR/PR. The intended flow is tight — implement → review → check-out — so the uncommitted window is short.

## Cost reporting

The skill marks its invocation start at step 1, and the final step runs [`skills/paf-shared/paf-report-cost.py`](../../skills/paf-shared/paf-report-cost.py) in `record` mode, keyed by the **issue number** — the same per-feature ledger `/paf:create-issue` wrote to and `/paf:check-out` will total for the MR/PR. Only this invocation's slice of the transcript (from the step-1 mark onward) is priced, so running `implement-issue` and `check-out` in one CLI session does not double-count. Cost is converted to **EUR**. See [`docs/skills/create-issue.md`](create-issue.md) for the ledger details.

## Related files

- [`skills/paf-implement-issue/SKILL.md`](../../skills/paf-implement-issue/SKILL.md) — the operational definition.
- [`skills/paf-shared/output-contract.md`](../../skills/paf-shared/output-contract.md) — agent output parsing rules.
- [`skills/paf-shared/paf-report-cost.py`](../../skills/paf-shared/paf-report-cost.py) / [`pricing.json`](../../skills/paf-shared/pricing.json) — cost reporting.
- [`agents/issue-validator.md`](../../agents/issue-validator.md), [`agents/implementation-verifier.md`](../../agents/implementation-verifier.md), [`agents/senior-engineer-reviewer.md`](../../agents/senior-engineer-reviewer.md), [`agents/code-simplifier.md`](../../agents/code-simplifier.md), [`agents/security-engineer.md`](../../agents/security-engineer.md), [`agents/test-coverage-reviewer.md`](../../agents/test-coverage-reviewer.md), [`agents/full-stack-dev.md`](../../agents/full-stack-dev.md) — the agent definitions this skill uses.
- [`docs/architecture.md`](../architecture.md) — the factory-wide design this skill follows.
```
