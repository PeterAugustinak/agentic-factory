---
name: "paf:create-issue"
description: Turn a discussed feature idea into a structured GitHub issue and post it after developer approval. Invoke with /paf:create-issue when you are ready to capture a feature as an issue.
disable-model-invocation: true
argument-hint: "[optional short idea]"
allowed-tools: Read, Bash(gh issue create *), Bash(gh issue view *), Bash(gh label list *), Bash(python3 *)
---

# create-issue

Turn a feature idea — usually one you have just been discussing — into a structured GitHub issue, reviewed by the developer, and post it. This is the first skill in the factory: its output is an approved issue that `/paf:implement-issue` later builds.

You are the orchestrator running in the main thread. You invoke the `issue-writer` agent for the drafting and the `issue-validator` agent to check the drafted approach against authoritative docs *before* posting (cognitive work), and own all GitHub I/O yourself. Follow the steps in order; do not skip the human gate.

## Input

This skill runs inline in the current conversation, so **the prior discussion of the idea is already in your context** — use it as the primary input. `$ARGUMENTS` may carry a short seed if the developer invoked the skill with one, but it is optional and does not replace the conversation. Heavy exploration of the idea (e.g. via `/grill-me`) happens in the conversation *before* this skill; this skill concludes that discussion into an issue.

Project context — the GitHub repo (`owner/repo`) and any standard labels — comes from `CLAUDE.md`. Do not hardcode it.

## Steps

**1. Clarity gate (skill + human).**
Assess whether the idea (from the conversation and/or `$ARGUMENTS`) is specified enough to write a good issue: a clear problem, an intended outcome, and at least rough acceptance criteria. If it is thin or ambiguous, ask the developer a few **targeted** clarifying questions and wait for answers — do **not** draft yet. This is a lightweight gate, not a full elicitation; deep discussion belongs in the conversation beforehand. Proceed only once the idea is clear.

**2. Draft the issue (agent).**
Invoke the `issue-writer` agent explicitly by name. Pass it the clarified idea and the relevant discussion. It has no tools beyond Read and does not post anything — it returns a draft only.

**3. Parse the agent output (skill).**
Apply the shared parsing rules in `${CLAUDE_SKILL_DIR}/../paf-shared/output-contract.md` to the agent's final message: extract the **last** fenced ` ```yaml ` block, validate its keys and enum values, and **STOP + escalate** (quoting the raw output) on any failure — never proceed on a guessed parse. The drafted issue (title, body, acceptance criteria, suggested labels) is in `summary`.

**4. Validate the drafted approach (agent).**
Invoke the `issue-validator` agent explicitly, passing the drafted issue and any concrete technical approach it contains (CLI commands, API signatures, library behaviour, config). It verifies those claims against authoritative documentation (it has web access; `issue-writer` does not) and returns findings — each `severity: error` = blocker, `severity: warning` = minor. Parse its output with the same shared rules as step 3. This catches approach defects **before** the issue is posted, rather than deferring them to `/paf:implement-issue`. If the drafted issue carries no externally-verifiable claims, the validator simply returns no findings — cheap.

**5. Resolve validator findings (skill).**
- **Any `severity: error`** → re-invoke `issue-writer` (back to step 2) with the validator's prescribed correction folded into the input, then re-validate (step 4). Do this at most **twice**; if a blocker still stands after two correction rounds, carry it to the review gate flagged **prominently** for the developer to resolve — never silently drop or post it.
- **Only `warning` findings (or none)** → carry them forward to the review gate.

Never post a draft whose blockers have not been resolved or explicitly surfaced to the developer.

**6. Developer review — human gate (skill).**
Present the **validated** drafted issue to the developer clearly (title, body, acceptance criteria, labels), together with any carried-forward findings (warnings, plus any unresolved blocker). Then wait for their decision:
- **Changes requested** → re-invoke `issue-writer` (back to step 2) with the developer's feedback added to the input; re-validate (step 4) before presenting again. Repeat until approved.
- **Approved** → continue to step 7.

Do not post anything until the developer approves.

**7. Post the issue (skill).**
The step-6 approval **is** the authorization to post — do not ask again or introduce any further confirmation. Post in a single `gh` call, feeding the approved body straight to `gh` on stdin so no local file is written (writing a file would trigger a needless extra permission prompt):

```
gh issue create --title "<title>" --label "<label>" [--label "<label>" ...] --body-file - <<'EOF'
<approved body>
EOF
```

Use only labels that exist in the repo (check with `gh label list` if unsure). Capture the new **issue number** and **URL** from the command output, and print the URL to the developer.

**8. Report cost and time (skill).**
Run the shared cost helper:

```
python3 "${CLAUDE_SKILL_DIR}/../paf-shared/paf-report-cost.py" record \
  --session "${CLAUDE_SESSION_ID}" --skill create-issue --issue <issue-number>
```

It prices this run from the session transcript — which includes the idea discussion that preceded the issue — derives wall-clock from the transcript, appends an entry to the per-feature cost ledger keyed by the issue number (under `~/.claude/paf/costs/`, never in the project), and prints the cost + wall-clock report. Finally, reprint the issue URL for the developer.

## Escalation

Any failure — malformed agent output (step 3 or 4), or `gh` failing to post (step 7) — **stops the run** with a clear message to the developer. This skill never retries silently and never posts a partially-formed issue. A validator **blocker** does not stop the run: it is auto-corrected and re-validated (step 5), and any residual blocker is surfaced at the human gate for the developer to resolve — it is `/paf:implement-issue`'s validator that hard-STOPs on a blocker in the *posted* issue.
