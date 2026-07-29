---
name: "paf:check-out"
description: Confirm, validate, and open an MR/PR for developer-validated work on the current feature branch — with the whole feature's cost in the MR/PR. Invoke with /paf:check-out after reviewing /paf:implement-issue's output.
disable-model-invocation: true
argument-hint: "[optional issue-number]"
allowed-tools: Read, Bash(${CLAUDE_SKILL_DIR}/../paf-shared/paf-vcs *), Bash(git *), Bash(python3 *)
---

# check-out

Finish a feature: run one high-level safety-net review, do the final spec and pre-merge checks, then commit, push, and open the MR/PR — with the **whole feature's** cost in the MR/PR description. This is the third and final skill, run after the developer has reviewed `/paf:implement-issue`'s output on the branch.

This is a **confirmation-and-ship gate, not a deep-review-and-fix stage**. The deep review already ran in `/paf:implement-issue`, before the developer's manual review, so nothing here re-opens the code: `check-out` confirms and ships it.

You are the orchestrator running in the main thread. You chain the safety-net and finalisation agents, own all git/VCS I/O, and apply the STOP-and-escalate policy (this skill has **no auto-retry** and **no fix loop** — any failure or blocker halts and returns control to the developer).

## Input

- Operates on the **current feature branch**. Derive the issue number from the branch name (`feature/<issue-number>-<...>`); `$ARGUMENTS` overrides it. Read the issue with `paf-vcs` — its acceptance criteria are the spec `quality-assurer` checks against.
- Project context from `CLAUDE.md`: the MR/PR base branch (e.g. `develop`), the full pre-merge validation command, and the merge strategy. The repo and provider are auto-detected from the git `origin` remote.

**Strict project-context sourcing.** Every project-specific value (repo, base branch, pre-merge validation command, merge strategy) comes **only** from *this* project's `CLAUDE.md` and repository. Never substitute one — especially a filename or command — from your memory, another project, or a prior session; recalled memories are unrelated background and may name files that do not exist here. If a value a step needs is not defined in this project, **STOP and ask the developer** — do not invent or borrow one.
- **Robust to either state.** `/paf:implement-issue` leaves the work uncommitted, but the developer may have committed it during review. Compute the change to review as the branch's full diff against the base (`git diff <base>`), which covers committed **and** uncommitted changes, so this skill works either way.

## Parsing agent output

After **every** agent step, parse the agent's final message with the shared rules in `${CLAUDE_SKILL_DIR}/../paf-shared/output-contract.md`: extract the **last** fenced ` ```yaml ` block, validate keys and enums, and **STOP + escalate** (quoting the raw output) on any failure.

## Steps

**1. Confirm and gather (skill).**
First, mark this invocation's start so the cost step (step 6) prices only this run, not the whole session:

```
python3 "${CLAUDE_SKILL_DIR}/../paf-shared/paf-report-cost.py" mark --session "${CLAUDE_SESSION_ID}" --skill check-out
```

Then confirm with the developer that they have reviewed `/paf:implement-issue`'s implementation and are ready to finalise. Determine the issue number (branch name or `$ARGUMENTS`), read the issue for its acceptance criteria, and compute the change to review (`git diff <base>` per above).

**2. Safety-net review (agent).**
Invoke `senior-engineer-reviewer` — and **only** it — passing the change and the issue's requirement, framed **in the invocation** as a high-level confirmation pass: *this diff was already deep-reviewed in `/paf:implement-issue`; the developer's hand-edits since then cannot be isolated from that reviewed implementation, so you are being handed the whole branch diff — look for critical regressions, especially in the hand-edits, and do not re-litigate the already-reviewed implementation.* The depth and focus come from **your framing**, not from the agent's definition — do not modify `senior-engineer-reviewer`, whose deep review is exactly what `/paf:implement-issue` needs from it.

Parse its output and compute the gate **yourself, from the parsed `issues[].severity`** — not from the agent's `status`, which is `success` on completion regardless of what it found (`docs/architecture.md` §4):
- **Any `severity: error`** → **STOP**: print the findings and hand back to the developer, who fixes them on the branch or re-runs `/paf:implement-issue`. Never fix-and-continue — `check-out` has no fix loop.
- **Only `warning` findings (or none)** → print them for the developer's information and continue. They do not block.

This is the safety net for the one slice of code no agent has seen: the developer's manual hand-edits since `/paf:implement-issue` finished. **Accepted gap:** only the functional lens is applied here, not the complexity/security lenses, and the reviewer may re-see the already-reviewed implementation rather than only the hand-edits.

**3. Final spec check (agent).**
Invoke `quality-assurer` with the final change and the issue's acceptance criteria. It confirms every criterion is met.
- **Any criterion unmet (`status: failure` / `error` findings)** → **STOP** and escalate.
- **All met** → continue.

**4. Pre-merge validation (skill).**
Run the project's **full** pre-merge validation command **exactly as defined in `CLAUDE.md`** (the whole test + lint suite — the safety net a scoped run cannot see). If `CLAUDE.md` defines no such command, **STOP** and ask the developer — never guess one or reach for a script remembered from another project.
- **Fails** → **STOP** and escalate.
- **Passes** → continue.

**5. Commit and push (skill).**
Commit any **uncommitted** changes on the branch (the implementation and its review fixes) with a message referencing the issue (e.g. `#<issue-number>`). If the working tree is already clean — the developer committed during review — there is nothing to commit; proceed. Push the branch.

**6. Record this run's cost (skill).**
Append `check-out`'s own cost to the per-feature ledger so the total below includes it:

```
python3 "${CLAUDE_SKILL_DIR}/../paf-shared/paf-report-cost.py" record \
  --session "${CLAUDE_SESSION_ID}" --skill check-out --issue "<issue-number>"
```

**7. Total the feature and open the MR/PR (skill).**
Aggregate the whole feature's cost across all three main skills and clean up the ledger:

```
python3 "${CLAUDE_SKILL_DIR}/../paf-shared/paf-report-cost.py" aggregate \
  --issue "<issue-number>" --cleanup
```

Then open the MR/PR against the base branch from `CLAUDE.md`, **embedding the aggregate cost table in the description** so the reviewer — who has no access to this CLI session — sees the whole feature's cost (source branch is inferred by the adapter):

```
${CLAUDE_SKILL_DIR}/../paf-shared/paf-vcs create-change-request --base <base-branch> --title "<title>" <<'EOF'
<aggregate cost table>
EOF
```

Capture the MR/PR **URL** from `paf-vcs`'s `URL=` output line and print it.

## Escalation

`check-out` is the final, human-controlled finalisation stage, so it has **no auto-retry and no fix loop** — it never fixes-and-continues. Each of these **stops the run** and returns control to the developer, who fixes the cause and re-runs `/paf:check-out`:
- the safety-net review returns an `error` finding (step 2);
- `quality-assurer` finds unmet criteria (step 3);
- pre-merge validation fails (step 4);
- malformed or missing agent output (any agent step).

Nothing is pushed and no MR/PR is opened until every check passes.
