---
name: "paf:implement-issue"
description: Validate an approved GitHub issue, plan it, implement it on a feature branch, and verify it — leaving reviewed-ready code for /paf:check-out. Invoke with /paf:implement-issue <issue-number>.
disable-model-invocation: true
argument-hint: "[issue-number]"
allowed-tools: Read, Bash(gh issue view *), Bash(gh issue comment *), Bash(git *), Bash(python3 *)
---

# implement-issue

Take an approved GitHub issue from validated approach to implemented, tested code on a feature branch. This is the second skill in the factory: it runs after `/paf:create-issue` and before `/paf:check-out`. Its output is verified, **uncommitted** work on a feature branch that the developer reviews and then finishes with `/paf:check-out`.

You are the orchestrator running in the main thread. You chain the specialist agents, own all GitHub and git I/O, enforce the human gate, and apply the loop caps and escalation policy. Follow the steps in order.

## Input

- The issue number is in `$ARGUMENTS`. Read the issue with `gh` — its description and proposed approach are the starting point.
- Project context comes from `CLAUDE.md`: the GitHub repo (`owner/repo`), the branch convention (`feature/<issue-number>-<short-description>`), the base branch that feature branches and PRs target (e.g. `develop`), and the exact test/lint commands. Do not hardcode any of it.

## Parsing agent output

After **every** agent step below, parse the agent's final message with the shared rules in `${CLAUDE_SKILL_DIR}/../paf-shared/output-contract.md`: extract the **last** fenced ` ```yaml ` block, validate its keys and enum values, and **STOP + escalate** (quoting the raw output) on any failure. Never proceed on a guessed parse.

## Steps

**1. Read the issue (skill).**
Fetch the issue: `gh issue view $ARGUMENTS` on the repo from `CLAUDE.md`. Keep its title, body, and proposed approach — they feed the validator and planner.

**2. Validate the approach (agent).**
Invoke `issue-validator` explicitly, passing the issue and its proposed approach. It verifies technical validity against authoritative docs and returns findings (each `severity: error` = blocker, `warning` = minor). It does not post anything.

**3. Handle validator findings (skill).**
Post the validator's findings as a comment on the issue (`gh issue comment`). Then branch on severity:
- **Any `severity: error`** → **STOP**: tell the developer to update the issue and re-run `/paf:implement-issue`. Do not continue.
- **Only `warning` findings (or none)** → carry the warnings forward; they must be accounted for in the plan (step 5).

**4. Explore the codebase (agent).**
Invoke `code-explorer`, telling it what the issue will touch. It returns a structured summary of the relevant files, symbols, and dependencies (in `summary`).

**5. Produce the plan (agent).**
Invoke `implementation-planner`, passing: the issue, the `code-explorer` summary, and any `warning` findings from step 3. It returns a full implementation plan (files to touch, change per file, test strategy) in `summary`.

**6. Plan review — human gate (skill).**
Present the plan to the developer. Then wait:
- **Changes requested** → re-invoke `implementation-planner` (back to step 5) with the developer's feedback. Repeat until approved.
- **Approved** → continue.

**7. Create the feature branch (skill).**
From the base branch defined in `CLAUDE.md`, create and switch to `feature/<issue-number>-<short-description>`, deriving the short description from the issue title. All implementation happens on this branch.

**8. Implement the plan (agent).**
Invoke `full-stack-dev`, passing the approved plan. It edits files, writes tests, and runs any project commands the plan requires. It returns the files it changed in `artifacts`. It does not commit or push — you own git state.

**9. Verify (agent).**
Invoke `implementation-verifier`, telling it the area the change affects. It runs the project's test and lint commands (from `CLAUDE.md`), scoped to that area, and returns `status`.
- **`status: success`** → continue to step 10.
- **`status: failure`, retries remaining (< 2 done)** → re-invoke `full-stack-dev` (step 8) with the original plan **plus the verifier's failure output**, then verify again. `full-stack-dev` runs at most **3 times total** (initial + 2 retries). The builder never verifies its own fix — `implementation-verifier` always re-runs.
- **`status: failure`, retries exhausted** → **STOP**: print a structured escalation report (what failed, the last `implementation-verifier` output, a suggested next action). The developer adjusts the plan or issue and re-runs `/paf:implement-issue`.

**10. Hand off for review (skill).**
Do **not** commit, push, or open a PR. Leave the verified changes **uncommitted** on the feature branch so the developer can review them as working-tree changes in their IDE (the clearest review surface). `/paf:check-out` commits the implementation plus any approved fixes, pushes, and opens the PR.

**11. Report cost and time (skill).**
Run the shared cost helper:

```
python3 "${CLAUDE_SKILL_DIR}/../paf-shared/paf-report-cost.py" record \
  --session "${CLAUDE_SESSION_ID}" --skill implement-issue --issue <issue-number>
```

It prices this run from the session transcript, derives wall-clock, and appends an entry to the per-feature cost ledger keyed by the issue number (the same ledger `/paf:create-issue` wrote to and `/paf:check-out` will total). Print a short summary and remind the developer to review the branch, then run `/paf:check-out`.

## Escalation

Any of these **stops the run** with a clear message to the developer, who fixes the cause and re-runs `/paf:implement-issue`:
- a validator blocker (`severity: error`, step 3);
- verification still failing after the retry cap (step 9);
- malformed or missing agent output (any agent step).

This skill never proceeds past a blocker, never retries beyond the cap, and never commits, pushes, or opens a PR.
