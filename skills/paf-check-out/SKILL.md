---
name: "paf:check-out"
description: Review, fix, validate, and open an MR/PR for developer-validated work on the current feature branch — with the whole feature's cost in the MR/PR. Invoke with /paf:check-out after reviewing /paf:implement-issue's output.
disable-model-invocation: true
argument-hint: "[optional issue-number]"
allowed-tools: Read, Bash(${CLAUDE_SKILL_DIR}/../paf-shared/paf-vcs *), Bash(git *), Bash(python3 *)
---

# check-out

Finish a feature: run the deep reviews, apply the fixes the developer approves, do the final spec and pre-merge checks, then commit, push, and open the MR/PR — with the **whole feature's** cost and time in the MR/PR description. This is the third and final skill, run after the developer has reviewed `/paf:implement-issue`'s output on the branch.

You are the orchestrator running in the main thread. You chain the review and finalisation agents, own all git/VCS I/O, run the human fix-selection gate, and apply the STOP-and-escalate policy (this skill has **no auto-retry** — any failure halts and returns control to the developer).

## Input

- Operates on the **current feature branch**. Derive the issue number from the branch name (`feature/<issue-number>-<...>`); `$ARGUMENTS` overrides it. Read the issue with `paf-vcs` — its acceptance criteria are the spec `quality-assurer` checks against.
- Project context from `CLAUDE.md`: the MR/PR base branch (e.g. `develop`), the full pre-merge validation command, and the merge strategy. The repo and provider are auto-detected from the git `origin` remote.

**Strict project-context sourcing.** Every project-specific value (repo, base branch, pre-merge validation command, merge strategy) comes **only** from *this* project's `CLAUDE.md` and repository. Never substitute one — especially a filename or command — from your memory, another project, or a prior session; recalled memories are unrelated background and may name files that do not exist here. If a value a step needs is not defined in this project, **STOP and ask the developer** — do not invent or borrow one.
- **Robust to either state.** `/paf:implement-issue` leaves the work uncommitted, but the developer may have committed it during review. Compute the change to review as the branch's full diff against the base (`git diff <base>`), which covers committed **and** uncommitted changes, so this skill works either way.

## Parsing agent output

After **every** agent step, parse the agent's final message with the shared rules in `${CLAUDE_SKILL_DIR}/../paf-shared/output-contract.md`: extract the **last** fenced ` ```yaml ` block, validate keys and enums, and **STOP + escalate** (quoting the raw output) on any failure.

## Steps

**1. Confirm and gather (skill).**
Confirm with the developer that they have reviewed `/paf:implement-issue`'s implementation and are ready to finalise. Determine the issue number (branch name or `$ARGUMENTS`), read the issue for its acceptance criteria, and compute the change to review (`git diff <base>` per above).

**2. Review — in parallel (agents).**
Invoke **all three** review agents concurrently, each passed the change and the issue's requirement:
- `senior-engineer-reviewer` (functional correctness),
- `code-simplifier` (unnecessary complexity),
- `security-engineer` (security).

Wait for all three, parse each output, and aggregate their `issues` into one findings list (tagged by reviewer and severity).

**3. Select fixes — human gate (skill, `AskUserQuestion`).**
Present the aggregated findings to the developer and use `AskUserQuestion` to let them choose **which findings to fix** (multi-select), including a "fix none" option.
- **No findings, or none selected** → **skip** steps 4–5 and go straight to step 6. (Skip path.)
- **One or more selected** → continue to step 4 with only the selected findings.

**4. Apply approved fixes (agent).**
Invoke `full-stack-dev` with only the developer-selected findings. It edits files on the branch and returns its `artifacts`. It does not commit.

**5. Verify the fixes (agent).**
Invoke `implementation-verifier` (scoped to the affected area, per `CLAUDE.md`).
- **`status: failure`** → **STOP** and escalate (there is no retry in `check-out`). The developer fixes the cause and re-runs `/paf:check-out`.
- **`status: success`** → continue.

**6. Final spec check (agent).**
Invoke `quality-assurer` with the final change and the issue's acceptance criteria. It confirms every criterion is met.
- **Any criterion unmet (`status: failure` / `error` findings)** → **STOP** and escalate.
- **All met** → continue.

**7. Pre-merge validation (skill).**
Run the project's **full** pre-merge validation command **exactly as defined in `CLAUDE.md`** (the whole test + lint suite — the safety net a scoped run cannot see). If `CLAUDE.md` defines no such command, **STOP** and ask the developer — never guess one or reach for a script remembered from another project.
- **Fails** → **STOP** and escalate.
- **Passes** → continue.

**8. Commit and push (skill).**
Commit any **uncommitted** changes on the branch (the implementation and any approved fixes) with a message referencing the issue (e.g. `#<issue-number>`). If the working tree is already clean — the developer committed during review and no fixes were applied — there is nothing to commit; proceed. Push the branch.

**9. Record this run's cost (skill).**
Append `check-out`'s own cost to the per-feature ledger so the total below includes it:

```
python3 "${CLAUDE_SKILL_DIR}/../paf-shared/paf-report-cost.py" record \
  --session "${CLAUDE_SESSION_ID}" --skill check-out --issue <issue-number>
```

**10. Total the feature and open the MR/PR (skill).**
Aggregate the whole feature's cost across all three skills and clean up the ledger:

```
python3 "${CLAUDE_SKILL_DIR}/../paf-shared/paf-report-cost.py" aggregate \
  --issue <issue-number> --cleanup
```

Then open the MR/PR against the base branch from `CLAUDE.md`, **embedding the aggregate cost + wall-clock table in the description** so the reviewer — who has no access to this CLI session — sees the whole feature's cost and elapsed time (source branch is inferred by the adapter):

```
${CLAUDE_SKILL_DIR}/../paf-shared/paf-vcs create-change-request --base <base-branch> --title "<title>" <<'EOF'
<aggregate cost + wall-clock table>
EOF
```

Capture the MR/PR **URL** from `paf-vcs`'s `URL=` output line and print it.

## Escalation

`check-out` is the final, human-controlled finalisation stage, so it has **no auto-retry**. Each of these **stops the run** and returns control to the developer, who fixes the cause and re-runs `/paf:check-out`:
- `implementation-verifier` fails after fixes (step 5);
- `quality-assurer` finds unmet criteria (step 6);
- pre-merge validation fails (step 7);
- malformed or missing agent output (any agent step).

Nothing is pushed and no MR/PR is opened until every check passes.
