---
name: "paf:create-issue"
description: Turn a discussed feature idea into a structured issue and post it after developer approval. Invoke with /paf:create-issue when you are ready to capture a feature as an issue.
disable-model-invocation: true
argument-hint: "[optional short idea]"
allowed-tools: Read, Bash(${CLAUDE_SKILL_DIR}/../paf-shared/paf-vcs *), Bash(python3 *)
---

# create-issue

Turn a feature idea — usually one you have just been discussing — into a structured issue, reviewed by the developer, and post it. This is the first skill in the factory: its output is an approved issue that `/paf:implement-issue` later builds.

You are the orchestrator running in the main thread. You invoke the `issue-writer` agent for the drafting and the `issue-validator` agent to check the drafted approach against authoritative docs **and this repository** *before* posting (cognitive work), and own all VCS I/O yourself. Follow the steps in order; do not skip the human gate.

## Input

This skill runs inline in the current conversation, so **the prior discussion of the idea is already in your context** — use it as the primary input. `$ARGUMENTS` may carry a short seed if the developer invoked the skill with one, but it is optional and does not replace the conversation. Heavy exploration of the idea (e.g. via `/grill-me`) happens in the conversation *before* this skill; this skill concludes that discussion into an issue.

Project context — the repo and provider are auto-detected from the git `origin` remote (via `paf-vcs`; no CLAUDE.md field needed); any standard labels come from `CLAUDE.md`. Do not hardcode either.

**Strict project-context sourcing.** Every project-specific value (repo, labels) comes **only** from *this* project's `CLAUDE.md` and repository. Never substitute one — especially a filename or command — from your memory, another project, or a prior session; recalled memories are unrelated background and may name things that do not exist here. If a value a step needs is not defined in this project, **STOP and ask the developer** — do not invent or borrow one.

## Steps

**1. Clarity gate (skill + human).**
First, mark this invocation's start so the cost step (step 8) prices only this run, not the whole session:

```
python3 "${CLAUDE_SKILL_DIR}/../paf-shared/paf-report-cost.py" mark --session "${CLAUDE_SESSION_ID}" --skill create-issue
```

Then assess whether the idea (from the conversation and/or `$ARGUMENTS`) is specified enough to write a good issue: a clear problem, an intended outcome, and at least rough acceptance criteria. If it is thin or ambiguous, ask the developer a few **targeted** clarifying questions and wait for answers — do **not** draft yet. This is a lightweight gate, not a full elicitation; deep discussion belongs in the conversation beforehand. Proceed only once the idea is clear.

**2. Draft the issue (agent).**
Invoke the `issue-writer` agent explicitly by name. Pass it the clarified idea and the relevant discussion. It has no tools beyond Read and does not post anything — it returns a draft only.

**3. Parse the agent output (skill).**
Apply the shared parsing rules in `${CLAUDE_SKILL_DIR}/../paf-shared/output-contract.md` to the agent's final message: extract the **last** fenced ` ```yaml ` block, validate its keys and enum values, and **STOP + escalate** (quoting the raw output) on any failure — never proceed on a guessed parse. The drafted issue (title, body, acceptance criteria, suggested labels) is in `summary`.

**4. Validate the drafted approach (agent).**
Invoke the `issue-validator` agent explicitly, passing it the **entire drafted issue**. It validates the draft against both authoritative external documentation (it has web access; `issue-writer` does not) and the actual repository, and returns findings — each `severity: error` = blocker, `severity: warning` = minor. Parse its output with the same shared rules as step 3. This catches approach defects **before** the issue is posted, rather than deferring them to `/paf:implement-issue`.

- **Never narrow its scope, and never skip this step.** Pass the whole draft — not just the parts that look externally verifiable — and let the validator decide what is worth checking; do not tell it to take any part "as given." A draft with no external claims is not a reason to skip: its claims about *this repository* are always checkable, and are exactly the class of defect that otherwise reaches `/paf:implement-issue`.

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
The step-6 approval **is** the authorization to post — do not ask again or introduce any further confirmation.

**Append the PAF-validated marker.** Every issue posted here has passed `issue-validator` (step 4) *and* the developer's review gate (step 6), so append a marker as the **final line** of the approved body — a lone line reading exactly:

```
PAF
```

It is a **visible** footer (deliberately not a hidden HTML comment — that would force reading the raw body to survive rendering; a plain line survives any rendering, so `paf-vcs view-issue` stays simple). It is `/paf:implement-issue`'s signal that this issue was already validated by PAF and approved by the developer, so it can skip its own validation pass. Detection anchors on the issue's **final line being exactly `PAF`** — never on the word appearing elsewhere — because "PAF" occurs throughout ordinary issue prose. Append it on **every** post — including one where the developer approved despite a residual blocker at the gate (step 5): that blocker was surfaced and adjudicated by the developer here, so re-validating it at implementation time would only re-raise a decision already made.

Post in a single `paf-vcs` call, feeding the approved body (with the `PAF` marker as its last line) straight to it on stdin so no local file is written (writing a file would trigger a needless extra permission prompt):

```
${CLAUDE_SKILL_DIR}/../paf-shared/paf-vcs create-issue --title "<title>" --label "<label>" [--label "<label>" ...] <<'EOF'
<approved body, ending with a lone `PAF` line>
EOF
```

Use only labels that exist in the repo (check with `${CLAUDE_SKILL_DIR}/../paf-shared/paf-vcs list-labels` if unsure). Capture the new **issue number** and **URL** from `paf-vcs`'s `NUMBER=`/`URL=` output lines (not by re-parsing raw CLI text), and print the URL to the developer.

**8. Report cost (skill).**
Run the shared cost helper:

```
python3 "${CLAUDE_SKILL_DIR}/../paf-shared/paf-report-cost.py" record \
  --session "${CLAUDE_SESSION_ID}" --skill create-issue --issue "<issue-number>"
```

It prices only this invocation's slice of the session transcript (from the step-1 mark onward), appends an entry to the per-feature cost ledger keyed by the issue number (under `~/.claude/paf/costs/`, never in the project), and prints the cost. Finally, reprint the issue URL for the developer.

## Escalation

Any failure — malformed agent output (step 3 or 4), or `paf-vcs` failing to post (step 7) — **stops the run** with a clear message to the developer. This skill never retries silently and never posts a partially-formed issue. A validator **blocker** does not stop the run: it is auto-corrected and re-validated (step 5), and any residual blocker is surfaced at the human gate for the developer to resolve. Because every posted issue carries the trailing `PAF` marker (step 7), `/paf:implement-issue` skips its own validation of it; it re-validates only issues **without** the marker (hand-written, or created outside PAF), and there a blocker prompts an informed developer-approval gate rather than an unconditional stop.
