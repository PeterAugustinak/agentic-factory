# check-out

Human-facing documentation for the `check-out` skill. The operational definition is [`skills/paf-check-out/SKILL.md`](../../skills/paf-check-out/SKILL.md); this file explains how the skill works and is not loaded by Claude at run time.

## Purpose

Finish a feature: run one high-level safety-net review, run the final spec and full pre-merge checks, then commit, push, and open the PR — with the **whole feature's** cost in the PR description. `check-out` is the **third and final** skill, run after the developer has reviewed `/paf:implement-issue`'s output on the branch.

This is a **confirmation-and-ship gate, not a deep-review-and-fix stage.** The deep review runs in `/paf:implement-issue`, *before* the developer's manual review — so `check-out` never re-opens the code. See [`architecture.md` §5](../architecture.md#5-loop-cap-escalation-and-cost-reporting).

## When and how to invoke

On the feature branch, once you've reviewed the implemented change:

```
/paf:check-out [optional issue-number]
```

The issue number is normally derived from the branch name (`feature/<issue>-<…>`); pass it only to override.

## How it works

`check-out` is an orchestrator in the main thread. It runs one safety-net review, does the two final checks, and finalises git/GitHub — with **no auto-retry and no fix loop**: any blocker halts and hands control back to the developer.

1. **Confirm & gather** (skill) — confirm the developer validated the implementation; read the issue's acceptance criteria; compute the change as the branch's diff vs base (committed **or** uncommitted).
2. **Safety-net review** — `senior-engineer-reviewer`, invoked as a **high-level confirmation pass** (framed at the call site: already deep-reviewed in `implement-issue`; the hand-edits can't be isolated from that reviewed implementation, so it's handed the whole branch diff — look for critical regressions, especially the developer's hand-edits, and don't re-litigate the already-reviewed implementation). The skill computes the gate itself from the findings' severity: `error` **STOPs**, `warning` is surfaced but does not block.
3. **Final spec check** — `quality-assurer` confirms every acceptance criterion; unmet **STOPs**.
4. **Pre-merge validation** (skill) — the project's **full** test + lint suite; failure **STOPs**.
5. **Commit & push** (skill) — commit whatever is still uncommitted; push.
6. **Record cost** (skill) — append this run's cost to the per-feature ledger.
7. **Total & PR** (skill) — total the whole feature across all three skills and open the PR with that cost table in its description.

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
| [agent] senior-engineer-reviewer — SAFETY    |
|   NET: high-level confirmation pass (framed  |
|   at invocation) over the whole branch diff; |
|   focus on the developer's hand-edits, don't |
|   re-litigate the reviewed implementation    |
+----------------------------------------------+
     |--- error finding -> STOP (no fix loop): developer fixes
     |
     v  (warning surfaced, non-blocking / none)
+----------------------------------------------+
| [agent] quality-assurer — final spec check   |
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
| `senior-engineer-reviewer` | Safety-net review — a high-level confirmation pass over the diff, framed at invocation; `error` findings STOP the run. |
| `quality-assurer` | Final gate — confirms every acceptance criterion is met. |

Two agents, run in sequence. The deep review (`code-simplifier`, `security-engineer`, `test-coverage-reviewer`, and this same `senior-engineer-reviewer` at full depth) runs in `/paf:implement-issue`, not here. `senior-engineer-reviewer`'s **definition is unchanged** — the shallower framing comes from how `check-out` invokes it, since agents are caller-agnostic and a permanent "be shallow" instruction would damage its deep use in the deep review. **Accepted gap:** only the functional lens is applied here, not the complexity/security lenses, and the reviewer may re-see the already-reviewed implementation rather than only the hand-edits, since the hand-edits cannot be isolated from the rest of the diff. Agents never touch git/`gh` — the skill owns all of it.

## Human interception points

- **Readiness confirmation** — at step 1 the skill confirms the developer has reviewed `/paf:implement-issue`'s output and is ready to finalise; nothing runs before they say so.
- **Blocker hand-back** — an `error` finding from the safety-net review (or any other STOP) returns control to the developer rather than being fixed automatically. `check-out` has no fix loop, so every blocker is a decision point.
- **Skill boundary** — after the PR is opened, the developer reviews and merges it (the final interception in `architecture.md` §2).

## Loop caps and escalation

Per `architecture.md` §5, `check-out` has **no auto-retry and no fix loop** — it is the final human-controlled stage, so the developer (not the factory) decides how to resolve a failure. Each of these **STOPs and escalates**:
- the safety-net review returns an `error` finding;
- `quality-assurer` finds unmet criteria;
- pre-merge validation fails;
- malformed/missing agent output.

**Two-tier verification.** The scoped `implementation-verifier` runs in `/paf:implement-issue`'s fix loops; the **full** suite runs here as pre-merge validation — the safety net that catches cross-module regressions a scoped run cannot see. `check-out` runs no scoped verification of its own, because it applies no fixes.

## Git handling and clean-tree robustness

The skill owns git/GitHub state. It computes the change to review as `git diff <base>`, so it works whether `/paf:implement-issue` left the work uncommitted **or** the developer committed it during review. At the end it commits whatever is still uncommitted (the implementation and its review fixes) — nothing if the tree is already clean — pushes the branch, and opens the PR against the base branch from `CLAUDE.md`. With squash merge, the number of commits on the branch does not matter.

## Cost in the PR

`check-out` marks its invocation start at step 1 and records its own run (that invocation's slice only) to the per-feature ledger, then runs [`skills/paf-shared/paf-report-cost.py`](../../skills/paf-shared/paf-report-cost.py) in `aggregate` mode (keyed by issue number) to total **all three skills** — `create-issue`, `implement-issue`, `check-out` — and embeds that **EUR cost** table in the **PR description**. Because `check-out` prices only its own slice, running it in the same CLI session as `implement-issue` does not re-count `implement-issue`'s tokens. This gives the PR reviewer, who never sees the CLI session, the whole feature's cost. The ledger is cleaned up as part of aggregation. See [`docs/skills/create-issue.md`](create-issue.md) for the ledger mechanics.

## Related files

- [`skills/paf-check-out/SKILL.md`](../../skills/paf-check-out/SKILL.md) — the operational definition.
- [`skills/paf-shared/output-contract.md`](../../skills/paf-shared/output-contract.md) — agent output parsing rules.
- [`skills/paf-shared/paf-report-cost.py`](../../skills/paf-shared/paf-report-cost.py) / [`pricing.json`](../../skills/paf-shared/pricing.json) — cost reporting.
- [`agents/senior-engineer-reviewer.md`](../../agents/senior-engineer-reviewer.md), [`agents/quality-assurer.md`](../../agents/quality-assurer.md) — the agent definitions this skill uses.
- [`docs/architecture.md`](../architecture.md) — the factory-wide design this skill follows.
```
