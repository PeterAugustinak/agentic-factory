---
name: "paf:implement-issue"
description: Validate an approved issue, then plan and implement it on a feature branch via plan mode, verify it, then deep-review and fix it — leaving reviewed code for /paf:check-out. Invoke with /paf:implement-issue <issue-number>.
disable-model-invocation: true
argument-hint: "[issue-number]"
allowed-tools: Read, Edit, Write, Bash(${CLAUDE_SKILL_DIR}/../paf-shared/paf-vcs *), Bash(git *), Bash(python3 *)
---

# implement-issue

Take an approved issue from validated approach to implemented, tested, **reviewed** code on a feature branch. This is the second skill in the factory: it runs after `/paf:create-issue` and before `/paf:check-out`. Its output is verified, deep-reviewed, **uncommitted** work on a feature branch that the developer reviews and then finishes with `/paf:check-out`.

You are the orchestrator running in the main thread. You validate the approach with an agent, then **plan and implement in one shared context using native plan mode** (`EnterPlanMode` → approval gate via `ExitPlanMode` → execute in the same context), then verify with an agent, then **deep-review the change with the review agents and have the findings triaged and applied** before handing off. You own all VCS and git I/O, enforce the human gate, and apply the loop cap and escalation policy. Follow the steps in order.

The deep review lands **here**, before the hand-off, and not in `/paf:check-out`: the developer's manual review must land on already-reviewed-and-fixed code rather than trigger a round of fixes that forces them to re-review work they had already signed off.

## Why plan mode (not a planner agent + a builder agent)

Planning and building run **in the main thread via native plan mode**, not as two separate subagents. This is a deliberate exception to "cognitive work is delegated to agents" (`docs/architecture.md` §2): a separate planner agent and a separate builder agent do not share context, so the builder starts **cold** and re-derives everything the planner already worked out — exploration happens twice and the "plan" carries intent rather than concrete edits. Plan mode keeps exploration, the concrete plan, and execution in **one context**, so applying an approved plan is fast: the edits are already decided at approval time. `EnterPlanMode` and `ExitPlanMode` are main-thread-only tools — which is why this must run in the skill's main thread, not a subagent.

This skill's **verify-fix loop** (step 8) is fixed in the main thread, and its **review-fix loop** (steps 10–11) is delegated to `full-stack-dev` — deliberately, not a contradiction. See `docs/architecture.md` §2 for why.

## Input

- The issue number is in `$ARGUMENTS`. Read the issue with `paf-vcs` — its description and proposed approach are the starting point.
- Project context comes from `CLAUDE.md`: the branch convention (`feature/<issue-number>-<short-description>`), the base branch that feature branches and MRs/PRs target (e.g. `develop`), and the exact test/lint commands. The repo and provider are auto-detected from the git `origin` remote. Do not hardcode any of it.

**Strict project-context sourcing.** Every project-specific value (repo, labels, branch convention, test/lint/validation commands) comes **only** from *this* project's `CLAUDE.md` and repository. Never substitute one — especially a filename or command — from your memory, another project, or a prior session; recalled memories are unrelated background and may name files that do not exist here. If a value a step needs is not defined in this project, **STOP and ask the developer** — do not invent or borrow one.

## Parsing agent output

After **every** agent step, parse that agent's final message with the shared rules in `${CLAUDE_SKILL_DIR}/../paf-shared/output-contract.md`: extract the **last** fenced ` ```yaml ` block, validate its keys and enum values, and **STOP + escalate** (quoting the raw output) on any failure. Never proceed on a guessed parse.

## Steps

**1. Read the issue (skill).**
First, mark this invocation's start so the cost step (step 13) prices only this run, not the whole session:

```
python3 "${CLAUDE_SKILL_DIR}/../paf-shared/paf-report-cost.py" mark --session "${CLAUDE_SESSION_ID}" --skill implement-issue
```

Then fetch the issue: `${CLAUDE_SKILL_DIR}/../paf-shared/paf-vcs view-issue $ARGUMENTS` on the repo auto-detected from the git `origin` remote. Keep its title, body, and proposed approach — they feed the validator and the plan.

**Source-aware validation.** Check whether the fetched issue's **final line is exactly `PAF`** — the marker `create-issue` appends to every issue it posts. Anchor on the last line only, never on the word appearing elsewhere (issue prose is full of "PAF"). Its presence means this issue was already validated by PAF and approved by the developer.
- **Marker present** → **skip steps 2–3 entirely** and go straight to plan mode (step 4). Re-validating a PAF-authored issue is redundant and — because same-definition agents are non-deterministic — risks "blocking" an issue `create-issue` already approved.
- **Marker absent** (a hand-written issue, or one created outside PAF) → run steps 2–3 as below; the validator is the only validation such an issue gets.

**2. Validate the approach (agent).** *(Only when the issue is unmarked — a marked issue skipped to step 4.)*
Invoke `issue-validator` explicitly, passing the issue and its proposed approach. It verifies technical validity against authoritative docs and the repository, and returns findings (each `severity: error` = blocker, `warning` = minor). It does not post anything.

**3. Handle validator findings (skill).**
Post **only** the validator's `error`/`warning` findings, one line each — never the `summary`/verdict or a recap of confirmed claims (remediation belongs in the plan, step 4). Feed the findings to `paf-vcs` on stdin (a heredoc is the clearest form):

```
${CLAUDE_SKILL_DIR}/../paf-shared/paf-vcs comment-issue $ARGUMENTS <<'EOF'
<one line per error/warning finding>
EOF
```

**When the validator returns zero findings, post no comment at all** — skip the `comment-issue` call entirely.

Then branch on severity:
- **Only `warning` findings (or none)** → carry the warnings forward; they must be accounted for in the plan (step 4).
- **Any `severity: error`** → do **not** stop unconditionally. The scope an issue names is only a hint — the real files are decided in plan mode (step 4) — so a blocker here is the developer's call, not an automatic halt. Inform the developer that a validator blocker was raised and ask via `AskUserQuestion` whether to fold it into the plan and continue, or stop. Use a **single** `AskUserQuestion` covering **all** blocker findings at once — quote each finding in the question text (summarise a very long message to its essence) — not one prompt per finding. Approve folds **all** of them into the plan; decline stops.
  - **Approve** → carry the blocker finding(s) forward alongside any warnings; they must be accounted for in the plan (step 4). Continue.
  - **Decline** → **STOP**: tell the developer to update the issue and re-run `/paf:implement-issue`. Do not continue.
  - **No answer** (the developer dismisses the prompt, it times out, or the tool returns without a selection) → treat as **Decline** and STOP. Never auto-approve on a missing answer.

**4. Plan in plan mode (skill, main thread).**
Enter plan mode with `EnterPlanMode`. In plan mode — one continuous, **read-only** context — explore the codebase and produce a **concrete** implementation plan for the issue: the exact files to change, the exact edits to make, and the test strategy, folding in any `warning` findings from step 3 **and any `error` findings the developer approved** at the step-3 gate. Nothing is written to the codebase during this step. Do the exploration **here**, in the same context that will implement — do not delegate it to a separate agent (see "Why plan mode" above).

**5. Plan approval — human gate (`ExitPlanMode`).**
Call `ExitPlanMode` to present the completed plan for the developer's approval. This is the mandatory plan-review gate — nothing is written to the codebase before it.
- **Changes requested** → revise the plan (still in plan mode) and present again with `ExitPlanMode`. Repeat until approved.
- **Approved** → the session leaves plan mode into edit mode; continue in the **same context** (the concrete edits are already worked out).

**6. Create the feature branch (skill).**
After approval, from the base branch defined in `CLAUDE.md`, create and switch to `feature/<issue-number>-<short-description>`, deriving the short description from the issue title. All implementation lands on this branch.

**7. Implement the approved plan (skill, same context).**
Apply the approved plan's exact edits (`Edit`/`Write`) and run any project commands it requires, on the feature branch — the concrete edits are already decided, so this is applying, not re-exploring. Do **not** commit or push — you own git state.

**8. Verify (agent).**
Invoke `implementation-verifier`, telling it the area the change affects. It runs the project's test and lint commands **exactly as defined in `CLAUDE.md`**, scoped to that area, and returns `status`. If `CLAUDE.md` defines no such commands, **STOP** and ask the developer — never guess a command or reach for one remembered from another project.
- **`status: success`** → continue to step 9 (review).
- **`status: failure`, retries remaining (< 2 done)** → apply the fix yourself **in the same main-thread context that built the code** (still in edit mode) — you already hold the plan and the edits, so there is no re-exploration — informed by the verifier's failure output; then re-invoke `implementation-verifier`. Do **not** delegate the fix to a separate builder agent (see "Why plan mode" above). Do this at most **twice** (initial run + 2 fix-and-reverify cycles). The implementer never verifies its own fix — `implementation-verifier` always re-runs as a separate agent.
- **`status: failure`, retries exhausted** → **STOP**: print a structured escalation report (what failed, the last `implementation-verifier` output, a suggested next action). The developer adjusts the plan or issue and re-runs `/paf:implement-issue`.

**9. Deep review — in parallel (agents).**
Invoke **all** review agents concurrently — a single message carrying one explicit agent invocation each — each passed the issue's requirement and the implemented change:
- `senior-engineer-reviewer` (functional correctness),
- `code-simplifier` (unnecessary complexity),
- `security-engineer` (security),
- `test-coverage-reviewer` (meaningful test coverage).

**How to supply the change.** Pass both the branch's diff against the base branch (`git diff <base>`) **and** the explicit list of files you created and modified in step 7. Both are needed: the work is uncommitted, so files you *created* are still untracked and do not appear in `git diff` at all. You hold that file list from step 7, and the reviewers have `Read` — so name the files and they can read what the diff omits.

Wait for all of them, parse each output, and aggregate their `issues` into one findings list, each finding tagged with the reviewer that raised it and its severity.

- **Zero findings across all of them** → skip steps 10–11 and go to step 12.
- **One or more findings** → continue to step 10.

**10. Triage and apply the findings (agent).**
Invoke `full-stack-dev` **once** with **all** aggregated findings, instructing it to decide which are worth applying and to apply them — this is a triage-and-apply step, not the application of a pre-approved list. Restate the guardrail in the invocation: `severity: error` findings (bugs, security) default to **applied** — skipping one requires saying so loudly, with justification, in its `summary`; `severity: warning` findings are where it exercises discretion.

The developer does **not** pre-select fixes here; their manual review after this skill is the curation and revert point. So **surface `full-stack-dev`'s applied-vs-skipped report verbatim** to the developer — it tells them what changed beyond the plan they approved, and is what they curate against.

**11. Re-verify (agent).**
Re-invoke `implementation-verifier` (same scoping rules as step 8): step 10 may have changed the code, and tests are the gate.
- **`status: success`** → continue to step 12.
- **`status: failure`, retries remaining (< 2 done)** → re-invoke `full-stack-dev` with the verifier's failure output to fix it, then re-invoke `implementation-verifier`. At most **twice** (initial run + 2 fix-and-reverify cycles) — the same policy as step 8.
- **`status: failure`, retries exhausted** → **STOP**: print a structured escalation report (what failed, the last `implementation-verifier` output, a suggested next action).

Do **not** re-run the review agents in this loop, or anywhere else in this invocation: the deep review runs **exactly once** per `/paf:implement-issue` run. The second look at the code is the developer's manual review, backed by `/paf:check-out`'s safety-net review.

**12. Hand off for review (skill).**
Do **not** commit, push, or open an MR/PR. Leave the verified, reviewed changes **uncommitted** on the feature branch so the developer can review them as working-tree changes in their IDE (the clearest review surface). `/paf:check-out` commits the implementation plus the review fixes, pushes, and opens the MR/PR.

**13. Report cost (skill).**
Run the shared cost helper:

```
python3 "${CLAUDE_SKILL_DIR}/../paf-shared/paf-report-cost.py" record \
  --session "${CLAUDE_SESSION_ID}" --skill implement-issue --issue "<issue-number>"
```

It prices only this invocation's slice of the session transcript (from the step-1 mark onward), and appends an entry to the per-feature cost ledger keyed by the issue number (the same ledger `/paf:create-issue` wrote to and `/paf:check-out` will total). Print a short summary and remind the developer to review the branch, then run `/paf:check-out`.

## Escalation

Any of these **stops the run** with a clear message to the developer, who fixes the cause and re-runs `/paf:implement-issue`:
- a validator blocker the developer **declines** to carry forward at the step-3 gate (a PAF-validated issue skips validation entirely; an approved blocker is folded into the plan instead of stopping);
- verification still failing after the retry cap (step 8);
- re-verification after the review fixes still failing after the retry cap (step 11);
- malformed or missing agent output (any agent step).

This skill never proceeds past a blocker, never retries beyond the cap, and never commits, pushes, or opens an MR/PR.
