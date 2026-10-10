---
name: "paf:check-out"
description: Confirm, validate, and open an MR/PR for developer-validated work on the current feature branch — with the whole feature's cost in the MR/PR. Invoke with /paf:check-out after reviewing /paf:implement-issue's output.
disable-model-invocation: true
argument-hint: "[optional issue-number]"
allowed-tools: Read, Bash(${CLAUDE_SKILL_DIR}/../paf-shared/paf-vcs *), Bash(git *), Bash(python3 *)
---

# check-out

Finish a feature: run one high-level safety-net review when the branch changed since `/paf:implement-issue`'s hand-off, do the final spec and pre-merge checks, then commit, push, and open the MR/PR — with the **whole feature's** cost in the MR/PR description. This is the third and final skill, run after the developer has reviewed `/paf:implement-issue`'s output on the branch.

This is a **confirmation-and-ship gate, not a deep-review-and-fix stage**. The deep review already ran in `/paf:implement-issue`, before the developer's manual review, so nothing here re-opens the code: `check-out` confirms and ships it.

You are the orchestrator running in the main thread. You chain the safety-net and finalisation agents, own all git/VCS I/O, and apply the STOP-and-escalate policy (this skill has **no auto-retry** and **no fix loop** — every failure or blocker that needs judgement to resolve halts the run and returns control to the developer). It has exactly one, bounded mutation: the project's own auto-fix command at the pre-merge gate (step 4), when the project defines one.

## Input

- Operates on the **current feature branch**. Derive the issue number from the branch name (`feature/<issue-number>-<...>`); `$ARGUMENTS` overrides it. Read the issue with `paf-vcs` — its acceptance criteria are the spec `quality-assurer` checks against.
- Project context from the project instructions (`CLAUDE.md` or `AGENTS.md`, whichever Claude Code loaded): the MR/PR base branch (e.g. `develop`), the full pre-merge validation command, the **optional** auto-fix command (step 4; many projects define none, which is not an error). The repo and provider are auto-detected from the git `origin` remote.

**Strict project-context sourcing.** Every project-specific value (repo, base branch, pre-merge validation command, auto-fix command) comes **only** from *this* project's instructions and repository. Never substitute one — especially a filename or command — from your memory, another project, or a prior session; recalled memories are unrelated background and may name files that do not exist here. If a value a step needs is not defined in this project, **STOP and ask the developer** — do not invent or borrow one.
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

Then — only after that confirmation, so the developer's editing is finished — compare the branch against `/paf:implement-issue`'s hand-off fingerprint:

```
python3 "${CLAUDE_SKILL_DIR}/../paf-shared/paf-fingerprint.py" check --issue "<issue-number>"
```

It recomputes the content fingerprint against the base commit pinned at the hand-off and prints a `VERDICT=` line and a `REASON=` line. **Only output with exactly one `VERDICT=` line, and that line exactly `VERDICT=skip`, skips step 2.** Anything else — `VERDICT=review` (content changed, committed or not; no fingerprint recorded; an unreadable record), a missing or repeated verdict line, or a failed command — means step 2 runs exactly as below. Never decide the skip by judgement.

**2. Safety-net review (agent).**
**On `VERDICT=skip`** — the branch content is identical to the deep-reviewed hand-off, so there are no hand-edits to review: do **not** invoke the reviewer. Print the skip loudly, with the helper's `REASON=` text — e.g. *"Safety-net review skipped: branch content is identical to `/paf:implement-issue`'s reviewed hand-off (fingerprint match) — no hand-edits to review."* — and continue to step 3. A commit made during review that changes no content lands here: committing is not editing.

**Otherwise**, invoke `senior-engineer-reviewer` — and **only** it — passing the change and the issue's requirement, framed **in the invocation** as a high-level confirmation pass: *this diff was already deep-reviewed in `/paf:implement-issue`; the developer's hand-edits since then cannot be isolated from that reviewed implementation, so you are being handed the whole branch diff — look for critical regressions, especially in the hand-edits, and do not re-litigate the already-reviewed implementation.* The depth and focus come from **your framing**, not from the agent's definition — do not modify `senior-engineer-reviewer`, whose deep review is exactly what `/paf:implement-issue` needs from it.

Parse its output and compute the gate **yourself, from the parsed `issues[].severity`** — not from the agent's `status`, which is `success` on completion regardless of what it found (`docs/architecture.md` §4):
- **Any `severity: error`** → **STOP**: print the findings and hand back to the developer, who fixes them on the branch or re-runs `/paf:implement-issue`. Never fix-and-continue — `check-out` has no fix loop for review findings, which require judgement by their nature.
- **Only `warning` findings (or none)** → print them for the developer's information and continue. They do not block.

This is the safety net for the one slice of code no agent has seen: the developer's manual hand-edits since `/paf:implement-issue` finished — which is why it runs only when the fingerprint shows the content changed (or cannot confirm it did not). **Accepted gap:** only the functional lens is applied here, not the complexity/security lenses; when it runs, the reviewer may re-see the already-reviewed implementation rather than only the hand-edits; and a hand-edit to a path marked `--assume-unchanged` or `--skip-worktree` is invisible to the fingerprint.

**3. Final spec check (agent).**
Invoke `quality-assurer` with the final change and the issue's acceptance criteria. It confirms every criterion is met.
- **Any criterion unmet (`status: failure` / `error` findings)** → **STOP** and escalate.
- **All met** → continue.

**4. Pre-merge validation (skill).**
Run the project's **full** pre-merge validation command **exactly as defined in the project instructions** (the whole test + lint suite — the safety net a scoped run cannot see). If the project instructions define no such command, **STOP** and ask the developer — never guess one or reach for a script remembered from another project.
- **Passes** → continue.
- **Fails, and the project instructions define no auto-fix command** → **STOP** and escalate.
- **Fails, and the project instructions define an auto-fix command** → run **that** command, **exactly as defined there** — never a tool, flag, or invocation you chose yourself, and never in place of the developer's judgement — then re-run the pre-merge validation command **once**:
  - **Now passes** → the failures were mechanically resolvable and the project's own tooling resolved them. Continue, and report what the auto-fix changed (`git diff --stat` is enough) so it shows up in the developer's picture of the branch.
  - **Still fails** → **STOP** and escalate with the residual failures. Do **not** hand-edit code to make the gate pass, and do not run the auto-fix again.

This is a bounded mechanical step, not a fix loop — see `docs/architecture.md` §5, `check-out` mutation posture, for why the single re-run is enough to tell mechanical failures from ones needing judgement.

**5. Commit and push (skill).**
Commit any **uncommitted** changes on the branch (the implementation, its review fixes, and any pre-merge auto-fix changes from step 4) with a message referencing the issue (e.g. `#<issue-number>`). If the working tree is already clean — the developer committed during review — there is nothing to commit; proceed. Push the branch.

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

and remove the feature's hand-off fingerprint on the same lifecycle:

```
python3 "${CLAUDE_SKILL_DIR}/../paf-shared/paf-fingerprint.py" clear --issue "<issue-number>"
```

Then open the MR/PR against the base branch from the project instructions, passing the description on stdin (source branch is inferred by the adapter). The issue title is attacker-influenceable text (anyone who can file an issue controls it) — never paste it directly into a double-quoted command-line argument, where a title containing `"`, a backtick, `$(...)`, `;`, or `&&` could break out and run arbitrary shell code with your git/gh/glab credentials. Instead, first bind the resolved title to a shell variable via a **single-quoted** assignment — escaping any single quote in the title as `'\''` (the standard technique for embedding arbitrary text inside a single-quoted shell string) — then pass the variable, never the raw text, as `--title`:

```
title='<type>: <issue title>'
${CLAUDE_SKILL_DIR}/../paf-shared/paf-vcs create-change-request --base <base-branch> --title "$title" <<'EOF'
<the filled-in description below>
EOF
```

**Description — fixed template.** The description is **exactly** this skeleton, filled in — nothing else, in this order:

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

Rules for filling it in:
- **Cost section** — appended **verbatim** from the `paf-report-cost.py aggregate` output above (its heading and table, as printed). Never authored or reformatted by you. It gives the reviewer — who has no access to this CLI session — the whole feature's cost.
- **Validation section** — carries the pre-merge validation command **exactly as the project instructions define it** (the same command step 4 ran; never hardcoded, never one remembered from another project) plus the result summary from its **actual** output. Says nothing about the factory's internal agent gates (the reviews, the spec check).
- **Deviations section** — inferred from the issue body and the `git diff <base>` already in context from step 1, under a strict anchoring rule: report **only** what the issue *explicitly states* — in its Approach, Scope of changes, or acceptance criteria — and the implementation does differently, phrased "what the issue said → what was built". No hedging, no speculation. When nothing anchors, **omit the whole section** — no "None." placeholder.
- **Never include** — rationale or a "why" section, a changed-files list or per-file narration, trade-off discussion, agent-review findings or statistics, or version-bump notes. A reviewer who wants that level of intent detail finds it in the linked issue.
- **No `🤖 Generated with [Claude Code]` trailer.**
- **`Closes #<issue-number>` is always written, regardless of the base branch.** (On both GitHub and GitLab, auto-closing the issue on merge only fires when the MR/PR targets the repository's default branch — but that is a platform behaviour, not something to conditionally implement here: the line itself is unconditional.)

**Title — one rule.** The title is `<type>: <issue title>`. Pick `<type>` from the change itself — the `git diff <base>` already in context from step 1 — as the one that best describes its primary purpose, from this closed vocabulary only: `feat`, `fix`, `docs`, `refactor`, `chore`, `test`, `perf`, `build`, `ci`. Never consult the issue's labels and never STOP over the type. First drop any leading prefix from the issue title so it never carries two — matched case-insensitively: one of these types with an optional `(scope)` and/or `!`, followed by `:`; or `Bug:`. If nothing remains, use `issue #<issue-number>` as the description. `check-out` adds no labels to the MR/PR.

Capture the MR/PR **URL** from `paf-vcs`'s `URL=` output line and print it.

## Escalation

`check-out` is the final, human-controlled finalisation stage, so it has **no auto-retry and no fix loop** — it never fixes-and-continues on anything requiring judgement. The **one** exception is step 4's optional, project-defined auto-fix (see step 4 for what it is and why it doesn't reopen the fix loop). Each of these **stops the run** and returns control to the developer, who fixes the cause and re-runs `/paf:check-out`:
- the safety-net review returns an `error` finding (step 2);
- `quality-assurer` finds unmet criteria (step 3);
- pre-merge validation fails — after the auto-fix and its single re-validation, when the project defines an auto-fix command (step 4);
- malformed or missing agent output (any agent step).

Nothing is pushed and no MR/PR is opened until every check passes.
