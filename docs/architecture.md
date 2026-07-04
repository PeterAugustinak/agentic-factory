# PAF Architecture

This document is the single source of truth for the design of the Personal Agentic Factory (PAF). All agent definitions, skills, and hooks must follow it without re-deciding what is settled here.

PAF splits responsibilities cleanly:

- **Skills own the workflow** — sequencing, human approval gates, and all external I/O (GitHub via `gh`, git state, running tests, posting results).
- **Agents own the cognitive work** — code analysis, synthesis, review — each with a defined tool scope and a model suited to its task.
- **The human owns the decisions** — the factory accelerates and structures the work; it does not replace judgement.

Every decision here has been verified against official Claude Code documentation or an established best practice — nothing is guessed. Where a decision depends on a specific Claude Code behaviour, the source is cited inline and collected under [Sources](#sources). Details described as "implementation detail" are intentionally left to the agent/skill/hook implementations; everything else is fixed.

---

## 1. Agents

A PAF agent is a specialist subagent owning one cognitive responsibility, with a tool scope (§3) and a model suited to its task. Agents are caller-agnostic (§2) and all follow the output contract (§4). This section defines *how an agent is shaped*, not which agents exist: the agents are self-describing in `agents/<name>.md`, and how to author one is in [`agent-definition-format.md`](authoring/agent-definition-format.md). The architecture keeps no roster — read `agents/` for the current set.

### Model selection

Each agent declares its `model` as an alias (`haiku`, `sonnet`, `opus`) — aliases, not pinned IDs, so model upgrades apply automatically.(1) Choose by the nature of the work:

- **Mechanical / I-O-bound, no reasoning** (e.g. reading and summarising files) → the cheapest capable model (currently `haiku`). Such agents often run at the start of every flow, so keeping them cheap matters.
- **Requires reasoning, judgement, or interpretation** (planning, building, reviewing, validating, verifying) → the mid-tier model (currently `sonnet`).
- Reserve the top model (`opus`) for work that genuinely needs the deepest reasoning; do not default to it.

### Agent categories

Agents fall into a few stable shapes. The category drives tool scope (§3) and output field usage (§4):

- **Analysis / read** — explore or reason over code and return a summary or plan. Read, plus **read-only Bash** for codebase exploration (§3).
- **Synthesis** — produce a document (e.g. an issue) as text. Read-only.
- **Builder** — edit files, write tests, run commands. Read + write, project-confined.
- **Review / validation** — inspect implemented code, or check a proposed approach against authoritative sources, and report findings. Read-only, plus web lookup when validating against external documentation (§3).
- **Verification** — run tests/linter and report pass/fail. Read + execute, no writes.

There is intentionally **no `github-*` or I/O agent** — GitHub and git interaction is mechanical, not cognitive, and is owned by the skill (see [Section 2](#external-io-and-vcs-state-are-skill-owned)).

---

## 2. Skill-to-agent orchestration

### Orchestration model

The topology is dictated by a hard Claude Code constraint: **subagents cannot spawn other subagents.** Nested delegation must be driven from the main conversation, and skills run in the main conversation context, not in an isolated subagent.(2)

Therefore:

- **The skill runs in the main thread.** The main thread is the orchestrator and is the only context that can spawn agents.
- **Agents are chained from the main thread.** Each agent completes its task and returns results to the main thread, which then passes relevant context into the next agent's delegation prompt.(2)
- **Each agent is invoked explicitly by name** (via the Agent tool / `@agent-<name>`), never by autonomous natural-language delegation. Explicit invocation guarantees the named subagent runs; natural-language naming only lets Claude *decide whether* to delegate.(3)
- **Sequencing is prompt-based, not harness-enforced.** Claude Code skills are prompt-based — there is no harness-level deterministic state machine. The fixed sequence is enforced by explicit, imperative skill instructions ("Step N: invoke the `<exact-agent>` agent with this context"), executed by the main-thread model. Skills must therefore be written imperatively, not suggestively.
- **Agents are caller-agnostic.** An agent definition must never reference a specific skill — not by name and not by behaviour. Agents are reusable specialists: any caller may invoke any agent — a skill, or a developer invoking it directly (e.g. `@code-simplifier review the current branch`). An agent's prompt describes only what it receives and what it returns, never who invokes it or where it sits in a pipeline. The same rule applies between agents — an agent does not name another agent; it operates solely on the input it is handed and the output contract it returns.

#### External I/O and VCS state are skill-owned

All GitHub API calls (`gh`), git state transitions (branch, commit, push), test-execution triggers, and result posting happen in the main thread / skill. Agents never call `gh` or change git state — `full-stack-dev` edits files, but the skill owns branching, committing, pushing, and opening issues/PRs.

Where the same `gh`/`git` sequences recur across skills, they are factored into shared helpers in `scripts/` rather than duplicated or pushed into a dedicated agent. This is deliberate: mechanical, side-effectful I/O must stay deterministic and auditable, so it lives in the orchestration layer, not inside non-deterministic LLM agents.

### Human interception model

The primary human interception points are **the skill boundaries themselves**. The factory is deliberately three separate, developer-invoked skills — not a single end-to-end skill. The developer runs one skill, reviews the result, then runs the next:

1. Run `create-issue` → finishes → **interception 1**: developer reviews the GitHub issue before any implementation.
2. Run `implement-issue` → finishes → **interception 2**: developer reviews the implemented code and tests.
3. Run `check-out` → finishes → developer reviews and merges the PR.

This three-skill split *is* the human-control architecture; the gaps between skills are the mandatory review gates.

A skill may additionally contain **in-skill interception points** where it pauses mid-run for developer input. Two general mechanisms are available:

- **Plan-approval pause** — the skill presents a plan and waits for explicit developer confirmation before implementing.
- **Structured decision** — the skill uses the `AskUserQuestion` tool to present a structured choice (e.g. selecting which review findings to fix). `AskUserQuestion` is a main-thread tool, available to the skill but not to subagents.

How many in-skill interceptions each skill has, and exactly where, is an implementation detail of each skill. The architecture defines only the available mechanisms.

### Per-skill orchestration maps

`CLAUDE.md` is loaded automatically into the main thread and into every agent (see [Section 6](#6-claudemd-as-the-single-source-of-project-context)) — it is not passed explicitly.

**Legend** — 
- `[agent]` = work delegated to a specialist agent (cognitive work)
- `[skill]` = orchestration & external I/O done by the skill itself in the main thread
- `[human gate]` = developer interception point
- `STOP` = run halts and is escalated to the developer, who fixes the problem and re-runs the skill

Each diagram reads top → bottom; a right-side channel (`<-+`) routes a branch back to an earlier step or forward past skipped steps.

Once a skill is implemented, its detailed, up-to-date flow lives in its own document under `docs/<skill>.md`; the maps below are the design intent for skills not yet built and are relocated to the per-skill doc as each is built.

#### `create-issue`

Implemented — see [`docs/skills/create-issue.md`](skills/create-issue.md) for the current orchestration diagram and explanation.

#### `implement-issue`

```text
/implement-issue <issue>
     |
     v
+----------------------------------------------+
| [skill] read linked issue via gh             |
+----------------------------------------------+
     |
     v
+----------------------------------------------+
| [agent] issue-validator                      |
|   verify approach vs docs -> findings        |
+----------------------------------------------+
     |
     v
+----------------------------------------------+
| [skill] post findings comment on issue       |
+----------------------------------------------+
     |
     |--- severity: error (blocker) --> STOP: developer updates issue & re-runs
     |
     v  (severity: warning / minor only -> passed to planner)
+----------------------------------------------+
| [agent] code-explorer                        |
|   explore relevant codebase                  |
+----------------------------------------------+
     |
     v
+----------------------------------------------+
| [agent] implementation-planner               | <-+
|   produce plan (incl. minor findings)        |   |
+----------------------------------------------+   |
     |                                             |
     v                                             |
+----------------------------------------------+   |
| [human gate]                                 |   |
|   developer reviews + confirms plan          |   |
+----------------------------------------------+   |
     +--- changes requested -----------------------+
     |
     v  (approved)
+----------------------------------------------+
| [agent] full-stack-dev                       | <-+
|   implement the plan                         |   |
+----------------------------------------------+   |
     |                                             |
     v                                             |
+----------------------------------------------+   |
| [agent] implementation-verifier              |   |
|   run tests + linter                         |   |
+----------------------------------------------+   |
     +--- fail, retries < 2 -----------------------+
     |--- fail, retries exhausted -> STOP: escalate failure report
     |
     v  (pass)
+----------------------------------------------+
| [skill] report cost + wall-clock             |
+----------------------------------------------+
```

#### `check-out`

```text
/check-out
     |
     v
+----------------------------------------------+
| [skill] confirm developer validated impl     |
+----------------------------------------------+
     |
     v
+----------------------------------------------+
| [agent] review  (run in parallel):           |
|   - senior-engineer-reviewer (functional)    |
|   - code-simplifier (DRY / complexity)       |
|   - security-engineer (security)             |
+----------------------------------------------+
     |
     v
+----------------------------------------------+
| [human gate]                                 |
|   developer selects findings to fix          |
|   (AskUserQuestion)                          |
+----------------------------------------------+
     +--- no findings to fix ----------------------+
     |                                             |
     v  (fixes approved)                           |
+----------------------------------------------+   |
| [agent] full-stack-dev                       |   |
|   apply approved fixes                       |   |
+----------------------------------------------+   |
     |                                             |
     v                                             |
+----------------------------------------------+   |
| [agent] implementation-verifier              |   |
|   run tests + linter                         |   |
+----------------------------------------------+   |
     |                                             |
     |--- fail -> STOP                             |
     |                                             |
     v  (pass)                                     |
+----------------------------------------------+   |
| [agent] quality-assurer                      | <-+
|   final spec check                           |
+----------------------------------------------+
     |
     |--- criteria unmet -> STOP
     |
     v  (criteria met)
+----------------------------------------------+
| [skill] run pre-merge validation (CLAUDE.md) |
+----------------------------------------------+
     |
     |--- fail -> STOP
     |
     v  (pass)
+----------------------------------------------+
| [skill] post PR via gh; print URL            |
+----------------------------------------------+
     |
     v
+----------------------------------------------+
| [skill] report cost + wall-clock             |
+----------------------------------------------+
```

---

## 3. Tool access scope per agent

### Enforcement model (three layers)

Tool restriction is enforced in three layers:

1. **Advisory (system prompt).** The agent's prompt describes its role and what it should not do. This is guidance only — the model may ignore it. Not an enforcement layer.
2. **Native, coarse (frontmatter).** Each agent declares `tools` (allowlist) and/or `disallowedTools` (denylist) in its definition. This is real, harness-level enforcement at the **whole-tool** granularity: a tool the agent does not have is genuinely unavailable. If both fields are set, `disallowedTools` is applied first, then `tools` resolves against the remainder.(4)
3. **Hook, granular (`PreToolUse`).** A single, centralized `PreToolUse` hook enforces the **sub-tool** restrictions that frontmatter cannot express — e.g. "Bash read-only commands only" or "writes within project paths only" — by inspecting `tool_input` before the call runs and blocking with exit code 2.(7)

**Why the hook is required and not redundant:** frontmatter can allow or deny a tool *as a whole* but cannot restrict it conditionally. `code-explorer` (read-only Bash) and `full-stack-dev` (project-path-only Bash/writes) need command- and path-level rules that only a `PreToolUse` hook inspecting `tool_input.command` can apply.

**How the hook identifies the active agent:** the `PreToolUse` hook payload (delivered as JSON on stdin) includes an `agent_type` field carrying the agent's `name`. This is the documented, native mechanism — no environment variable or prompt-header sentinel is needed. When `agent_type` is **absent**, the hook is firing in the **main thread (the orchestrating skill)**, which is intentionally unrestricted.(7) (5)

**One centralized hook, not per-agent hooks.** Claude Code supports per-agent scoped hooks via the `hooks` frontmatter field, but PAF uses a single global `PreToolUse` hook keyed on `agent_type`. This centralizes the policy in one file and avoids duplicating enforcement logic across ten agent definitions.

### Scoping an agent

An agent's tool scope is declared as a `tools` **allowlist** containing only what its job needs; every other tool — including all MCP tools — is denied by omission (default-deny).(4) Derive the allowlist from the agent's category (§1):

- **Read / analysis / synthesis / review** → `Read` only; add `WebSearch`, `WebFetch` only if the job needs external lookups.
- **Exploration / planning** → also `Bash` (the hook restricts it to read-only commands).
- **Builder** → also `Edit`, `Write`, `Bash` (the hook confines writes and Bash to the project root).
- **Verification** → also `Bash` for running tests/linters; no `Edit`/`Write`.

No agent is ever granted `gh` or git-state mutation — external I/O and VCS are skill-owned (§2). Each agent's exact allowlist lives in its file (`agents/<name>.md`); the architecture keeps no per-agent table.

### Hook enforcement policy (layer 3)

The architecture fixes the *policy patterns*; the exact command patterns are an implementation detail of the hook. Which pattern applies to an agent follows from its scope (above), so adding an agent needs no change here.

- **Read-only Bash** (any agent granted Bash for exploration only): the hook uses an **allowlist (default-deny)** — only an explicit set of read-only commands (e.g. `grep`, `find`, `git log`, `git diff`, `cat`, `ls`) is permitted; every other Bash command is blocked. Default-deny is required because a denylist of mutating commands inevitably leaks.
- **Project-path containment** (any agent with write access): the hook blocks any `Edit`, `Write`, or path-targeting Bash command whose target resolves **outside the project root**. The project root is read from the `CLAUDE_PROJECT_DIR` environment variable available to hooks.(7)
- **No external I/O** (all agents): `gh` and other external I/O is blocked at the hook even where `Bash` is allowed; only the skill (main thread) performs it.

---

## 4. Agent output contract

### Delivery mechanism

Claude Code has **no native typed return channel** for subagents — a subagent returns results as its **final assistant message in plain text**.(2)

Therefore:

- Every agent's system prompt instructs it that **its final message must be exactly one fenced ` ```yaml ` block conforming to the contract below — no prose before or after.**
- The **skill (main thread)** extracts the **last** fenced `yaml` block from the returned message and parses it: reading `status` to drive control flow, and passing `summary` / `issues` forward to the next agent.
- The contract is "machine-checkable" because **the skill parses and validates it** — not because the harness enforces a schema. There is no native validation. If an agent returns malformed or missing YAML, the skill fails loudly and escalates to the developer (see [Section 5](#5-loop-cap-escalation-and-cost-reporting)).

### Schema

A **uniform schema**: every field is always present; collections are `[]` when not applicable. This keeps parsing predictable and improves agent adherence (a fixed template is followed more reliably than conditional fields).

```yaml
agent: "<agent-name>"            # required — all agents
status: "success"               # required — one of: success | failure | needs_retry
summary: |                       # required — all agents (block scalar)
  one paragraph: what was done or what failed
artifacts:                       # always present; [] when none
  - path: "<relative file path>"
    action: "created"           # one of: created | modified | deleted
issues:                          # always present; [] when none
  - severity: "error"           # one of: error | warning
    message: "<description>"
    location: "<file:line, or omitted if not applicable>"
```

There is **no `cost` block** in the agent contract — an agent cannot reliably count its own tokens; cost is measured by the skill from the transcript (see [Section 5](#5-loop-cap-escalation-and-cost-reporting)).

### Severity semantics

- **`severity: error`** denotes a **blocker** — a finding that stops the flow and requires developer action (e.g. `issue-validator` error findings halt `implement-issue`).
- **`severity: warning`** denotes a **minor / non-blocking** finding that is passed forward (e.g. to `implementation-planner`) or surfaced for the developer to decide on.

The skill uses this field to branch.

### Field usage by agent category

The schema is uniform; this documents which fields carry the meaningful payload, by category (§1). `summary` carries the agent's primary **textual deliverable** — a short paragraph for most agents, but the complete document for an agent whose product *is* text (synthesis). `artifacts` carries **files** only: an agent with no write access produces no artifacts and reports its product in `summary`.

- **Builder** → `artifacts` is the primary payload; `issues` usually `[]`.
- **Review / validation** → `issues` is the primary payload; `artifacts` is `[]`. By default `status` is `success` on completion regardless of what was found — reporting findings is the job, and the skill/developer decides how to act on them. The one exception is a **final gate** review (a spec-conformance check that the skill treats as a STOP point): it sets `status: failure` when the work does not meet the criteria, so the skill can halt. An agent that acts as such a gate states this in its own Output section.
- **Analysis / read** → `summary` is the primary payload; `artifacts` and `issues` usually `[]`.
- **Synthesis** → the produced document is the `summary` payload; no write access, so `artifacts` is `[]`.
- **Verification** → `status` plus `issues` (the failures) are the primary payload.

---

## 5. Loop cap, escalation, and cost reporting

### `implement-issue` retry loop

- **Max retries:** 2 — `full-stack-dev` is reinvoked at most twice after an initial failure.
- **Trigger:** `implementation-verifier` returns `status: failure` (test or lint failures).
- **Passed to the builder on retry:** the original plan + the failed run's output contract (structured failure context, not free-form prose).
- **On retry exhaustion:** the skill stops and prints a structured escalation report to the developer containing what failed, the last `implementation-verifier` output, and a suggested next action. The developer reviews, adjusts the plan or issue, and re-invokes `implement-issue` manually.
- **No self-validation:** the builder never validates its own fix — `implementation-verifier` always runs as a separate agent after every `full-stack-dev` invocation.

### `check-out` fix loop

After the human gate, `full-stack-dev` applies only the developer-approved fixes, then `implementation-verifier` confirms tests still pass, then `quality-assurer` runs once, then the skill runs the pre-merge validation.

- **Skip path.** If the reviewers surface nothing — or the developer approves no fixes — there is nothing to implement: `full-stack-dev` and the post-fix `implementation-verifier` are skipped and the flow goes straight to `quality-assurer`.
- **No retry loop — failures STOP and escalate.** Unlike `implement-issue`, `check-out` has no auto-retry. Any failure at this stage halts the run and escalates to the developer, who fixes the problem and re-runs `check-out`:
  - `implementation-verifier` returns `status: failure` → STOP
  - `quality-assurer` finds unmet criteria → STOP
  - pre-merge validation fails → STOP

  This is deliberate: `check-out` is the final human-controlled finalization stage, so the developer — not the factory — decides how to resolve a failure.

### Verification scope — two tiers

The factory has two distinct verification points with deliberately different scopes:

- **`implementation-verifier` (scoped, in-loop).** Runs a **targeted subset** of the test suite — the tests covering the changed area/module (e.g. the affected Django app, or the affected CDK service/resource), not merely the changed test files and not the whole suite. It runs inside the `implement-issue` retry loop (up to 3×), so a scoped run keeps that loop fast and cheap.
- **Pre-merge validation (full, at the gate).** Runs the project's **full** test/lint suite once at `check-out` — the final safety net that catches any cross-module regression a scoped run could not see.

This two-tier split is the reason both points exist: fast scoped feedback during implementation, full validation before the PR.

**Implementation-defined:** how the affected area/module is determined (e.g. derived from `full-stack-dev`'s reported `artifacts` plus project conventions) and the exact scoped and full commands are **project-specific and sourced from `CLAUDE.md`** — not fixed by this architecture.

### `issue-validator` escalation

When `issue-validator` returns any finding with `severity: error` (blocker), the skill posts the findings as a GitHub issue comment, then stops; the developer must update the issue before re-running `implement-issue`. Findings with only `severity: warning` (minor) are posted as a comment and passed forward to `implementation-planner`. The validator never calls `gh` itself — the skill posts on its behalf.

### Malformed-contract escalation

Contract parsing must be defensive — the whole pipeline depends on it. The skill must:

1. Extract the **last** fenced ` ```yaml ` block from the agent's final message.
2. Parse it, and **validate** that all required keys are present and that enum fields hold allowed values (`status` ∈ {success, failure, needs_retry}; `severity` ∈ {error, warning}; `action` ∈ {created, modified, deleted}).
3. On any missing block, parse error, missing key, or invalid enum value → **STOP and escalate to the developer, including the agent's raw output** in the report so the failure is diagnosable.

The skill never proceeds on a partial or guessed parse.

### Cost and time reporting

Every skill run ends with a single report of **total token usage and wall-clock time** for the whole run.

- Cost is **not** self-reported by agents. The skill computes it from the session transcript at `transcript_path`, which records per-message `usage` (`input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`) and `model`, enabling correct per-model pricing.(7) (9)
- The internal mechanism for attributing usage to individual agents is an implementation detail; the architecture requires only that the final total is reported.

---

## 6. CLAUDE.md as the single source of project context

`CLAUDE.md` is the single source of project-specific context, and it is **loaded automatically into every agent** — there is no manual injection.

- **Auto-loading is native and not optional.** Every custom subagent loads the same CLAUDE.md / memory hierarchy the main conversation loads (user `~/.claude/CLAUDE.md`, project `./CLAUDE.md` or `./.claude/CLAUDE.md`, project rules, `CLAUDE.local.md`, managed policy). Only the built-in `Explore` and `Plan` agents skip it, and there is no frontmatter field or per-agent setting to change which agents skip it.(6) (8)
- **It depends on launch location, not agent config.** The hierarchy is resolved by walking up from the working directory, so the project-root `CLAUDE.md` reaches every agent as long as Claude Code is launched from within the project (the normal case). PAF keeps project context in the **root** `CLAUDE.md`; subdirectory `CLAUDE.md` files load on demand, not at launch, so PAF does not rely on them.
- **No duplication.** A value that exists in `CLAUDE.md` is never repeated in an agent prompt or skill file. `CLAUDE.md` holds project-specific context (stack, entry points, conventions, exact test/lint/pre-merge commands, GitHub repo in `owner/repo` format), kept under ~200 lines. Agent prompts hold only factory-level role, tool scope, and output-contract instructions.
- **Verification.** The `InstructionsLoaded` hook can log exactly which instruction files reached each agent and may be used to confirm the project `CLAUDE.md` is loaded into every agent.(7)

This is why skills do not manually inject CLAUDE.md sections into agents — it is unnecessary given native auto-loading.

---

## Sources

All architecture decisions are grounded in the official Claude Code documentation. Inline citations above use these numbers:

1. Subagents — Choose a model. https://code.claude.com/docs/en/sub-agents#choose-a-model
2. Subagents — Chain subagents / Choose between subagents and main conversation / What loads at startup. https://code.claude.com/docs/en/sub-agents#chain-subagents
3. Subagents — Invoke subagents explicitly. https://code.claude.com/docs/en/sub-agents#invoke-subagents-explicitly
4. Subagents — Control subagent capabilities. https://code.claude.com/docs/en/sub-agents#control-subagent-capabilities
5. Subagents — Supported frontmatter fields (`name` is received by hooks as `agent_type`). https://code.claude.com/docs/en/sub-agents#supported-frontmatter-fields
6. Subagents — What loads at startup. https://code.claude.com/docs/en/sub-agents#what-loads-at-startup
7. Hooks — `PreToolUse` input schema and `agent_type`, exit codes, environment variables (`CLAUDE_PROJECT_DIR`), `transcript_path`, `InstructionsLoaded`. https://code.claude.com/docs/en/hooks
8. Memory — How CLAUDE.md files load. https://code.claude.com/docs/en/memory#how-claude-md-files-load
9. Manage costs effectively. https://code.claude.com/docs/en/costs
