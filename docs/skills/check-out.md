# check-out

Human-facing documentation for the `check-out` skill. The operational definition is [`skills/paf-check-out/SKILL.md`](../../skills/paf-check-out/SKILL.md); this file explains how the skill works and is not loaded by Claude at run time.

## Purpose

Finish a feature: deep-review the implemented change, apply the fixes the developer approves, run the final spec and full pre-merge checks, then commit, push, and open the PR — with the **whole feature's** cost in the PR description. `check-out` is the **third and final** skill, run after the developer has reviewed `/paf:implement-issue`'s output on the branch.

## When and how to invoke

On the feature branch, once you've reviewed the implemented change:

```
/paf:check-out [optional issue-number]
```

The issue number is normally derived from the branch name (`feature/<issue>-<…>`); pass it only to override.

## How it works

`check-out` is an orchestrator in the main thread. It runs three reviewers in parallel, gates fix-selection through the developer, applies fixes, does the two final checks, and finalises git/GitHub — with **no auto-retry**: any failure halts and hands control back to the developer.

1. **Confirm & gather** (skill) — confirm the developer validated the implementation; read the issue's acceptance criteria; compute the change as the branch's diff vs base (committed **or** uncommitted).
2. **Review in parallel** — `senior-engineer-reviewer`, `code-simplifier`, `security-engineer` run concurrently; the skill aggregates their findings.
3. **Fix-selection gate** (skill, `AskUserQuestion`) — the developer picks which findings to fix. Nothing selected (or no findings) takes the **skip path** straight to the final check.
4. **Apply fixes** — `full-stack-dev` applies only the selected findings.
5. **Verify fixes** — `implementation-verifier` (scoped); failure **STOPs** (no retry).
6. **Final spec check** — `quality-assurer` confirms every acceptance criterion; unmet **STOPs**.
7. **Pre-merge validation** (skill) — the project's **full** test + lint suite; failure **STOPs**.
8. **Commit & push** (skill) — commit whatever is still uncommitted (implementation + fixes); push.
9. **Total & PR** (skill) — record this run's cost, total the whole feature across all three skills, and open the PR with that cost table in its description.

## Orchestration

```text
/paf:check-out
     |
     v
+----------------------------------------------+
| [skill] confirm dev validated impl; read the |
|   issue; compute change = git diff <base>    |
+----------------------------------------------+
     |
     v
+----------------------------------------------+
| [agent] review — run in parallel:            |
|   - senior-engineer-reviewer (functional)    |
|   - code-simplifier (complexity)             |
|   - security-engineer (security)             |
+----------------------------------------------+
     |
     v
+----------------------------------------------+
| [human gate] developer selects findings to   |
|   fix (AskUserQuestion)                       |
+----------------------------------------------+
     +--- no findings / none selected -------------+
     |                                             |
     v  (fixes selected)                           |
+----------------------------------------------+   |
| [agent] full-stack-dev — apply approved fixes|   |
+----------------------------------------------+   |
     |                                             |
     v                                             |
+----------------------------------------------+   |
| [agent] implementation-verifier (scoped)     |   |
+----------------------------------------------+   |
     |--- fail -> STOP (no retry)                  |
     |                                             |
     v  (pass)                                     |
+----------------------------------------------+   |
| [agent] quality-assurer — final spec check   | <-+
+----------------------------------------------+
     |--- criteria unmet -> STOP
     |
     v  (met)
+----------------------------------------------+
| [skill] full pre-merge validation (CLAUDE.md)|
+----------------------------------------------+
     |--- fail -> STOP
     |
     v  (pass)
+----------------------------------------------+
| [skill] commit uncommitted changes; push     |
+----------------------------------------------+
     |
     v
+----------------------------------------------+
| [skill] record check-out cost; aggregate the |
|   whole feature (EUR); open PR with the cost  |
|   table in the description                    |
+----------------------------------------------+
```

## Agents used

| Agent | Role in this skill |
|---|---|
| `senior-engineer-reviewer` | Functional-correctness review (parallel). |
| `code-simplifier` | Complexity / DRY / readability review (parallel). |
| `security-engineer` | Security review (parallel). |
| `full-stack-dev` | Applies the developer-approved fixes (skipped if none). |
| `implementation-verifier` | Confirms tests + lint still pass after fixes (skipped if no fixes). |
| `quality-assurer` | Final gate — confirms every acceptance criterion is met. |

The three reviewers run **concurrently**; the rest run in sequence. Agents never touch git/`gh` — the skill owns all of it.

## Human interception points

- **Fix-selection gate** — the developer chooses which review findings to fix (`AskUserQuestion`); a genuine decision point, including the option to fix none.
- **Skill boundary** — after the PR is opened, the developer reviews and merges it (the final interception in `architecture.md` §2).

## Loop caps and escalation

Per `architecture.md` §5, `check-out` has **no auto-retry** — it is the final human-controlled stage, so the developer (not the factory) decides how to resolve a failure. Each of these **STOPs and escalates**:
- verification fails after fixes;
- `quality-assurer` finds unmet criteria;
- pre-merge validation fails;
- malformed/missing agent output.

**Two-tier verification.** The scoped `implementation-verifier` runs in-loop; the **full** suite runs here as pre-merge validation — the safety net that catches cross-module regressions a scoped run cannot see.

## Git handling and clean-tree robustness

The skill owns git/GitHub state. It computes the change to review as `git diff <base>`, so it works whether `/paf:implement-issue` left the work uncommitted **or** the developer committed it during review. At the end it commits whatever is still uncommitted (implementation + approved fixes) — nothing if the tree is already clean — pushes the branch, and opens the PR against the base branch from `CLAUDE.md`. With squash merge, the number of commits on the branch does not matter.

## Cost in the PR

`check-out` marks its invocation start at step 1 and records its own run (that invocation's slice only) to the per-feature ledger, then runs [`skills/paf-shared/paf-report-cost.py`](../../skills/paf-shared/paf-report-cost.py) in `aggregate` mode (keyed by issue number) to total **all three skills** — `create-issue`, `implement-issue`, `check-out` — and embeds that **EUR cost** table in the **PR description**. Because `check-out` prices only its own slice, running it in the same CLI session as `implement-issue` does not re-count `implement-issue`'s tokens. This gives the PR reviewer, who never sees the CLI session, the whole feature's cost. The ledger is cleaned up as part of aggregation. See [`docs/skills/create-issue.md`](create-issue.md) for the ledger mechanics.

## Related files

- [`skills/paf-check-out/SKILL.md`](../../skills/paf-check-out/SKILL.md) — the operational definition.
- [`skills/paf-shared/output-contract.md`](../../skills/paf-shared/output-contract.md) — agent output parsing rules.
- [`skills/paf-shared/paf-report-cost.py`](../../skills/paf-shared/paf-report-cost.py) / [`pricing.json`](../../skills/paf-shared/pricing.json) — cost reporting.
- [`agents/senior-engineer-reviewer.md`](../../agents/senior-engineer-reviewer.md), [`agents/code-simplifier.md`](../../agents/code-simplifier.md), [`agents/security-engineer.md`](../../agents/security-engineer.md), [`agents/full-stack-dev.md`](../../agents/full-stack-dev.md), [`agents/implementation-verifier.md`](../../agents/implementation-verifier.md), [`agents/quality-assurer.md`](../../agents/quality-assurer.md) — the agent definitions.
- [`docs/architecture.md`](../architecture.md) — the factory-wide design this skill follows.
```
