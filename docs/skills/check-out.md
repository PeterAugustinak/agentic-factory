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

`check-out` is an orchestrator in the main thread. It runs one safety-net review, does the final checks, and finalises git/GitHub — with **no auto-retry and no fix loop**: any blocker halts and hands control back to the developer. Its one bounded mutation is the project's own optional auto-fix command at the pre-merge gate (step 4).

1. **Confirm & gather** (skill) — confirm the developer validated the implementation; read the issue's acceptance criteria; compute the change as the branch's diff vs base (committed **or** uncommitted).
2. **Safety-net review** — `senior-engineer-reviewer`, invoked as a **high-level confirmation pass** (framed at the call site: already deep-reviewed in `implement-issue`; the hand-edits can't be isolated from that reviewed implementation, so it's handed the whole branch diff — look for critical regressions, especially the developer's hand-edits, and don't re-litigate the already-reviewed implementation). The skill computes the gate itself from the findings' severity: `error` **STOPs**, `warning` is surfaced but does not block.
3. **Final spec check** — `quality-assurer` confirms every acceptance criterion; unmet **STOPs**.
4. **Pre-merge validation** (skill) — the project's **full** test + lint suite. On failure, if `CLAUDE.md` defines an **optional auto-fix command**, the skill runs that command exactly as defined and re-validates **once**: passing means the failures were mechanically resolvable and the run continues (reporting what changed); anything still failing needs judgement and **STOPs**. With no auto-fix command defined, failure **STOPs** as before.
5. **Commit & push** (skill) — commit whatever is still uncommitted; push.
6. **Record cost** (skill) — append this run's cost to the per-feature ledger.
7. **Total & PR** (skill) — total the whole feature across all three main skills and open the PR using the **fixed description template** (Closes line, What this implements, Validation, Deviations, cost table) under a title pinned to the issue title with a conventional-commit type prefix.

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
     |--- fail + auto-fix cmd defined -> run it once,
     |    re-validate: pass -> continue (report what
     |    it changed); residual -> STOP (needs judgment)
     |--- fail, no auto-fix cmd defined -> STOP
     |
     v  (pass)
+----------------------------------------------+
| [skill] commit uncommitted changes; push     |
+----------------------------------------------+
     |
     v
+----------------------------------------------+
| [skill] record check-out cost; aggregate the |
|   whole feature (tokens + EUR); open PR —    |
|   fixed body template, "<type>: <issue>"     |
+----------------------------------------------+
```

## Agents used

| Agent | Role in this skill |
|---|---|
| `senior-engineer-reviewer` | Safety-net review — a high-level confirmation pass over the diff, framed at invocation; `error` findings STOP the run. |
| `quality-assurer` | Final gate — confirms every acceptance criterion is met. |

The agents above run in sequence. The deep review (`code-simplifier`, `security-engineer`, `test-coverage-reviewer`, and this same `senior-engineer-reviewer` at full depth) runs in `/paf:implement-issue`, not here. `senior-engineer-reviewer`'s **definition is unchanged** — the shallower framing comes from how `check-out` invokes it, since agents are caller-agnostic and a permanent "be shallow" instruction would damage its deep use in the deep review. **Accepted gap:** only the functional lens is applied here, not the complexity/security lenses, and the reviewer may re-see the already-reviewed implementation rather than only the hand-edits, since the hand-edits cannot be isolated from the rest of the diff. Agents never touch git/`gh` — the skill owns all of it.

## Human interception points

- **Readiness confirmation** — at step 1 the skill confirms the developer has reviewed `/paf:implement-issue`'s output and is ready to finalise; nothing runs before they say so.
- **Blocker hand-back** — an `error` finding from the safety-net review (or any other STOP) returns control to the developer rather than being fixed automatically. `check-out` applies no judgement-requiring fix, so every blocker is a decision point.
- **Skill boundary** — after the PR is opened, the developer reviews and merges it (the final interception in `architecture.md` §2).

## Loop caps and escalation

Per `architecture.md` §5, `check-out` has **no auto-retry and no fix loop** — it is the final human-controlled stage, so the developer (not the factory) decides how to resolve anything requiring judgement. The single exception is step 4's optional auto-fix: one tool-driven, behaviour-preserving mechanical pass, which is bounded to a single attempt and is not a fix loop. Each of these **STOPs and escalates**:
- the safety-net review returns an `error` finding;
- `quality-assurer` finds unmet criteria;
- pre-merge validation fails — after the auto-fix and its single re-validation, where the project defines one;
- the MR/PR title's `<type>` cannot be resolved by any rule;
- malformed/missing agent output.

**Two-tier verification.** The scoped `implementation-verifier` runs **tests only** in `/paf:implement-issue`'s fix loops; the **full** test + lint suite runs here as pre-merge validation — the safety net that catches cross-module regressions a scoped run cannot see, and the tier the lint command belongs to. `check-out` runs no scoped verification of its own, because it authors no fixes of its own: its only mutation is the optional mechanical auto-fix at the gate, which the full re-validation already covers.

## Git handling and clean-tree robustness

The skill owns git/GitHub state. It computes the change to review as `git diff <base>`, so it works whether `/paf:implement-issue` left the work uncommitted **or** the developer committed it during review. At the end it commits whatever is still uncommitted (the implementation, its review fixes, and any pre-merge auto-fix changes) — nothing if the tree is already clean — pushes the branch, and opens the PR against the base branch from `CLAUDE.md`. With squash merge, the number of commits on the branch does not matter.

## MR/PR description and title

The MR/PR body is **not** freeform — it is a fixed skeleton the skill fills in, and nothing else:

```
Closes #<issue-number>.

## What this implements

<2-4 sentences, or up to 5 bullets — what was built, not why>

## Validation

`<pre-merge command>` — passed (<result summary from its actual output>).

## Deviations from the issue

<one line per deviation>

## Factory run cost — feature #<issue-number>

| Skill | In | Out | Cached | Total | Cost (EUR) |
|---|---:|---:|---:|---:|---:|
| ... | ... | ... | ... | ... | ... |
```

- The **cost section** is appended **verbatim** from `paf-report-cost.py aggregate` — heading and table as printed, never authored or reformatted by the model.
- **Validation** carries the pre-merge command exactly as `CLAUDE.md` defines it (the same command step 4 ran, never hardcoded) plus the result summary from its actual output. It says nothing about the factory's internal agent gates.
- **Deviations** is anchored strictly: only what the issue *explicitly states* — in its Approach, Scope of changes, or acceptance criteria — and the implementation does differently, phrased "what the issue said → what was built", with no hedging or speculation. When nothing anchors, the section is **omitted entirely** — there is no "None." placeholder.
- The body must **not** contain rationale or a "why" section, a changed-files list or per-file narration, trade-off discussion, agent-review findings or statistics, or version-bump notes — a reviewer who wants that intent detail finds it in the linked issue, which is what the `Closes` line points at. There is no `🤖 Generated with [Claude Code]` trailer.
- `Closes #<issue-number>` is **always** written, regardless of the base branch. (On both GitHub and GitLab, auto-closing the issue on merge only fires when the MR/PR targets the repository's default branch — but that is a platform behaviour, not something to conditionally implement: the line itself is unconditional.)
- The issue title is attacker-influenceable text, so the skill never splices it raw into a double-quoted shell argument when calling `paf-vcs` — it binds the resolved title to a shell variable via a safely-quoted assignment first. See `skills/paf-check-out/SKILL.md` step 7 for the exact construction.

The **title** is `<type>: <issue title>`, with `<type>` resolved in a fixed order:

1. the issue title already begins with one of the **exact, lowercase** prefixes `feat:`, `fix:`, `docs:`, `refactor:`, `chore:`, `test:`, `perf:`, `build:`, `ci:` → the type is already present: the issue title is used as the whole title, exactly as written, never with `<type>:` re-prepended. The vocabulary is closed and case-sensitive on purpose: a generic `<word>:` match would also catch `Bug: ` and preempt rule 2.
2. the title begins with `Bug: ` → that prefix is stripped and `fix:` used.
3. otherwise derived from the issue's labels — `bug`→`fix`, `enhancement`→`feat`, `documentation`→`docs` — with precedence `bug` > `enhancement` > `documentation` when an issue carries more than one.
4. nothing resolves → the skill **STOPs and asks the developer**, per its strict-sourcing rule; it never invents a type.

This makes every PAF-opened MR/PR self-describing and consistent.

## Cost in the PR

`check-out` marks its invocation start at step 1 and records its own run (that invocation's slice only) to the per-feature ledger, then runs [`skills/paf-shared/paf-report-cost.py`](../../skills/paf-shared/paf-report-cost.py) in `aggregate` mode (keyed by issue number) to total **all three main skills** — `create-issue`, `implement-issue`, `check-out` — and appends that **token-and-EUR cost** table **verbatim** as the **last section of the PR description** (see [MR/PR description and title](#mrpr-description-and-title) above). Because `check-out` prices only its own slice, running it in the same CLI session as `implement-issue` does not re-count `implement-issue`'s tokens. This gives the PR reviewer, who never sees the CLI session, the whole feature's cost. The ledger is cleaned up as part of aggregation. See [`docs/skills/create-issue.md`](create-issue.md) for the ledger mechanics.

## Related files

- [`skills/paf-check-out/SKILL.md`](../../skills/paf-check-out/SKILL.md) — the operational definition.
- [`skills/paf-shared/output-contract.md`](../../skills/paf-shared/output-contract.md) — agent output parsing rules.
- [`skills/paf-shared/paf-report-cost.py`](../../skills/paf-shared/paf-report-cost.py) / [`pricing.json`](../../skills/paf-shared/pricing.json) — cost reporting.
- [`agents/senior-engineer-reviewer.md`](../../agents/senior-engineer-reviewer.md), [`agents/quality-assurer.md`](../../agents/quality-assurer.md) — the agent definitions this skill uses.
- [`docs/architecture.md`](../architecture.md) — the factory-wide design this skill follows.
```
