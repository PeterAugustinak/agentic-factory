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

Each agent declares its `model` as an alias (`haiku`, `sonnet`, `opus`) — aliases, not pinned IDs, so model upgrades apply automatically.(1) Choose by how much reasoning the work genuinely requires and how expensive a miss is once it propagates downstream, not by a coarse verb list.

- **Mechanical / I-O-bound, no reasoning** (e.g. reading and summarising files; running the project's test command and reporting pass/fail) → the cheapest capable model (currently `haiku`). Such agents often run at the start of every flow, or repeatedly inside a fix loop, so keeping them cheap matters. One narrow discriminator inside otherwise mechanical work does not by itself lift an agent to mid-tier.
- **Requires reasoning, judgement, or interpretation** (planning, building, reviewing) → the mid-tier model (currently `sonnet`).
- Reserve the top model (`opus`) for work that genuinely needs the deepest reasoning, or where a miss is uniquely expensive because it happens **before** there is any built work for a later reviewer to catch it in — do not default to it. **Validating** an approach against authoritative documentation *and* the repository *before* it enters the build pipeline is such a case: unlike the post-build reviews in §4's field usage, a defect missed here propagates into everything subsequently built. See the issue-validator escalation (§5) for where it runs and how its `error` findings are handled.

### Agent categories

Agents fall into a few stable shapes. The category drives tool scope (§3) and output field usage (§4):

- **Analysis / read** — explore or reason over code and return a summary or plan. Read, plus **read-only Bash** for codebase exploration (§3).
- **Synthesis** — produce a document (e.g. an issue) as text. Read-only.
- **Builder** — edit files, write tests, run commands. Read + write, project-confined. Given a plan, a builder implements it as decided; given a set of **review findings**, it also triages them — deciding which are worth applying and reporting applied-vs-skipped with reasons. Triage is bounded by a rule that is severity-based **with one class carved out of it**: `error` applies by default; a **factual or self-consistency defect** (a stale reference, a contradiction between two stated facts) applies **whatever severity it carries**, because severity grades impact while that class is a correctness defect regardless; everything else at `warning` is discretionary. A builder also **sweeps**: when it changes a fact, rule, or name stated in more than one place, it updates every occurrence in the same change, so an edit never leaves the repository self-contradicting. Triage is scoped to the findings it was handed; it never widens the work — and the sweep is not a widening, since it restates the *same* change elsewhere rather than adding a different one.
- **Review / validation** — inspect implemented code, or check a proposed approach against authoritative sources **and the repository it targets**, and report findings. Read-only, plus read-only repo search when validating claims against the codebase and web lookup when validating against external documentation (§3).
- **Verification** — run tests and report pass/fail. Read + execute, no writes.

There is intentionally **no `github-*` or I/O agent** — GitHub and git interaction is mechanical, not cognitive, and is owned by the skill (see [Section 2](#external-io-and-vcs-state-are-skill-owned)).

---

## 2. Skill-to-agent orchestration

### Orchestration model

The orchestrator is always the **main conversation (the skill)**, never a subagent — because two things PAF depends on only work in the main thread:

- **Human interception.** PAF is human-gated, and the human-gate tools — `AskUserQuestion` and plan mode — are **main-thread-only**; they are unavailable to subagents even when listed in `tools`.(2) A subagent orchestrator could not pause for a developer decision.
- **External I/O and cost accounting.** The skill owns all `gh`/git I/O and computes the run's cost from the transcript — main-thread concerns (see below and [Section 5](#5-loop-cap-escalation-and-cost-reporting)).

Claude Code *does* now allow a subagent to spawn its own subagents, up to a fixed depth of five (as of v2.1.172).(2) PAF deliberately does **not** use nested delegation: orchestration stays **flat and in the main thread**. Nested agent hierarchies hide intermediate work from the developer, from the human gates, and from cost attribution — the opposite of PAF's human-control design. Agents are therefore single-responsibility specialists that do not orchestrate other agents — by choice, not by limitation.

Therefore:

- **The skill runs in the main thread.** The main thread is the orchestrator; keeping orchestration here is what makes the human gates, external I/O, and cost accounting possible.
- **Agents are chained from the main thread.** Each agent completes its task and returns results to the main thread, which then passes relevant context into the next agent's delegation prompt.(2)
- **Each agent is invoked explicitly by name** (via the Agent tool / `@agent-<name>`), never by autonomous natural-language delegation. Explicit invocation guarantees the named subagent runs; natural-language naming only lets Claude *decide whether* to delegate.(3)
- **Sequencing is prompt-based, not harness-enforced.** Claude Code skills are prompt-based — there is no harness-level deterministic state machine. The fixed sequence is enforced by explicit, imperative skill instructions ("Step N: invoke the `<exact-agent>` agent with this context"), executed by the main-thread model. Skills must therefore be written imperatively, not suggestively.
- **Agents are caller-agnostic.** An agent definition must never reference a specific skill — not by name and not by behaviour. Agents are reusable specialists: any caller may invoke any agent — a skill, or a developer invoking it directly (e.g. `@code-simplifier review the current branch`). An agent's prompt describes only what it receives and what it returns, never who invokes it or where it sits in a pipeline. The same rule applies between agents — an agent does not name another agent; it operates solely on the input it is handed and the output contract it returns.

#### Plan mode for the plan→build phase (`implement-issue`)

One deliberate exception to "cognitive work is delegated to agents": in `implement-issue` the **plan→build phase runs in the main thread via native plan mode** (`EnterPlanMode` → explore + produce a concrete plan → `ExitPlanMode` approval gate → execute in the same context), **not** as a separate planner agent handing off to a separate builder agent. Two subagents do not share context: the builder starts **cold**, re-reads the repo, and reconstructs file state to re-derive edits the planner already worked out — exploration happens twice and the "plan" carries intent rather than concrete edits. Plan mode keeps exploration, the concrete plan, and execution in **one context**, so an approved plan applies in seconds. `EnterPlanMode`/`ExitPlanMode` are main-thread-only tools, which is why this lives in the skill's main thread. Validation (`issue-validator`) and verification (`implementation-verifier`) remain delegated agents — they do not sit on the plan→build cold-context boundary, so their isolated contexts cost nothing there.

Running the build phase in the main thread means its file writes are **not** subject to the hook's agent-scoped project-path containment (§3) — an accepted trade-off documented as a residual risk in §3, compensated by the native read-only plan phase and the `ExitPlanMode` approval gate that precede any write.

The main-thread implementer also carries the builder's **sweep** obligation (§1, Builder): a fact, rule, or name the change touches is updated in **every** place the repository states it, located while planning and applied with the rest of the approved plan. The sweep is inherent to *authoring a change*, so it binds whichever owner authors it — the main-thread plan→build path here (the dominant authoring path, and the one that writes the plan's edits), and the delegated builder agent in the review-fix loop. Here the `ExitPlanMode` gate is where the developer sees the swept occurrences before any write.

**The review tail, and why there are two fix-owners.** After verification passes, `implement-issue` continues into a **deep review**: the review agents run in parallel over the implemented change, a builder agent triages and applies their findings, and the verifier re-runs. This review sits **here**, in `implement-issue`, and not in `check-out` — a deliberate reversal of the original sequencing. Placed in `check-out`, the automated review ran *after* the developer's manual review at interception 2, so the fixes it produced changed code the developer had already signed off, forcing them to re-review and re-test it. Reviewing before the hand-off means the developer's manual review lands on already-reviewed-and-fixed code. It also sharpens the per-skill responsibilities: `implement-issue` owns *producing correct, clean, reviewed code*; `check-out` owns *confirming and shipping it* (§5).

This gives `implement-issue` two fix loops with two different owners, which is consistent rather than contradictory. The **verify-fix loop** repairs the build itself and therefore stays in the **main thread**: that context still holds the plan and the exact edits, so a cold builder agent would only re-derive them — precisely the cost this section exists to avoid. The **review-fix loop** is delegated to a builder agent, because applying a *discrete list of findings* is not a re-build: each finding names its own location and remedy, so nothing must be re-derived and the cold-context penalty does not arise. Delegating it also returns those writes to the hook's agent-scoped path containment (§3), which main-thread writes do not get. The rule is one rule: keep work in-context when losing the context would cost re-derivation, delegate it when it would not.

#### External I/O and VCS state are skill-owned

All VCS API calls (`gh`/`glab`), git state transitions (branch, commit, push), test-execution triggers, and result posting happen in the main thread / skill. Agents never call `gh`/`glab` or change git state — `full-stack-dev` edits files, but the skill owns branching, committing, pushing, and opening issues/MRs/PRs.

Where the same `gh`/`glab`/`git` sequences recur across skills, they are factored into shared helpers in `paf-shared/` rather than duplicated or pushed into a dedicated agent. This is deliberate: mechanical, side-effectful I/O must stay deterministic and auditable, so it lives in the orchestration layer, not inside non-deterministic LLM agents.

**VCS provider abstraction.** The skills call one shared adapter, `skills/paf-shared/paf-vcs`, instead of `gh`/`glab` directly. It auto-detects the provider per project from `git remote get-url origin` (`github.com` → `gh`, `gitlab.com` → `glab`; any other host fails clearly, with no silent fallback) and exposes provider-neutral verbs — create/view/comment an issue, list labels, create a change request (PR on GitHub, MR on GitLab) — that normalise the two CLIs' flag differences. Self-hosted/custom-domain instances and an explicit provider override are out of scope.

### Human interception model

The primary human interception points are **the skill boundaries themselves**. The factory's **main skills** — `create-issue` → `implement-issue` → `check-out` — are deliberately three separate, developer-invoked skills, not a single end-to-end skill. This trip is fixed: further skills may be added alongside it, but the main skills and their order do not change. The developer runs one skill, reviews the result, then runs the next:

1. Run `create-issue` → finishes → **interception 1**: developer reviews the GitHub issue before any implementation.
2. Run `implement-issue` → finishes → **interception 2**: developer reviews the implemented code and tests.
3. Run `check-out` → finishes → developer reviews and merges the PR.

This three-way split of the main skills *is* the human-control architecture; the gaps between them are the mandatory review gates.

A skill may additionally contain **in-skill interception points** where it pauses mid-run for developer input. Two general mechanisms are available:

- **Plan-approval pause** — the skill presents a plan and waits for explicit developer confirmation before implementing.
- **Structured decision** — the skill uses the `AskUserQuestion` tool to present a structured choice (e.g. choosing between two viable approaches, or resolving an ambiguity the skill must not decide alone). `AskUserQuestion` is a main-thread tool, available to the skill but not to subagents. `implement-issue` uses it to gate a validator blocker on an unmarked issue — fold it into the plan and continue, or stop (§5).

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

Implemented — see [`docs/skills/implement-issue.md`](skills/implement-issue.md) for the current orchestration diagram and explanation.

#### `check-out`

Implemented — see [`docs/skills/check-out.md`](skills/check-out.md) for the current orchestration diagram and explanation.

---

## 3. Tool access scope per agent

### Enforcement model (three layers)

Tool restriction is enforced in three layers:

1. **Advisory (system prompt).** The agent's prompt describes its role and what it should not do. This is guidance only — the model may ignore it. Not an enforcement layer.
2. **Native, coarse (frontmatter).** Each agent declares `tools` (allowlist) and/or `disallowedTools` (denylist) in its definition. This is real, harness-level enforcement at the **whole-tool** granularity: a tool the agent does not have is genuinely unavailable. If both fields are set, `disallowedTools` is applied first, then `tools` resolves against the remainder.(4)
3. **Hook, granular (`PreToolUse`).** A single, centralized `PreToolUse` hook is the factory's **allow+deny authority**. It inspects `tool_input` before each call and returns an explicit `permissionDecision`: **`allow`** for the factory's vetted calls (so they run without a permission prompt), **`deny`** for the sub-tool restrictions frontmatter cannot express (e.g. "Bash read-only commands only", "writes within project paths only", "no external I/O for agents"), and emits **nothing (defer)** for anything unrecognized, so Claude Code's normal permission prompt still applies as a human safety net.(7) Emitting `allow` is what makes a run autonomous *between* the deliberate human gates: without it, every permitted call falls through to a prompt, because frontmatter `allowed-tools` grants are per-turn and do not cover subagents' tool calls.

**Why the hook is required and not redundant:** frontmatter can allow or deny a tool *as a whole* but cannot restrict it conditionally. An agent granted Bash for read-only exploration, and `full-stack-dev` (project-path-only Bash/writes), need command- and path-level rules that only a `PreToolUse` hook inspecting `tool_input.command` can apply.

**How the hook identifies the active agent:** the `PreToolUse` hook payload (delivered as JSON on stdin) includes an `agent_type` field carrying the agent's `name`. This is the documented, native mechanism — no environment variable or prompt-header sentinel is needed. When `agent_type` is **absent**, the hook is firing in the **main thread (the orchestrating skill)**: it is not restricted, and the hook `allow`s **every** tool call it receives — unconditionally, not gated on a command-family list — so orchestration runs prompt-free regardless of command shape (bare, compound, piped, or `cd`-prefixed).(7) (5) An earlier form gated the main thread on the command's first word, which made any compound command miss the list and fall through to a prompt, interrupting runs mid-flight; the per-command allow-list and deny rules exist to constrain **agents** (§2), not the trusted orchestrator.

**One centralized hook, not per-agent hooks.** Claude Code supports per-agent scoped hooks via the `hooks` frontmatter field, but PAF uses a single global `PreToolUse` hook keyed on `agent_type`. This centralizes the policy in one file and avoids duplicating enforcement logic across every agent definition.

### Scoping an agent

An agent's tool scope is declared as a `tools` **allowlist** containing only what its job needs; every other tool — including all MCP tools — is denied by omission (default-deny).(4) Derive the allowlist from the agent's category (§1):

- **Read / analysis / synthesis / review** → `Read` only; add `WebSearch`, `WebFetch` only if the job needs external lookups; add `Grep`, `Glob` when the job requires validating claims against the codebase rather than reading paths it is already given. **Accepted residual risk:** the hook's matcher does not cover `Read`/`Grep`/`Glob`, so — unlike `Edit`/`Write` — no rule confines *reads* to the project root, and `Grep`/`Glob` make bulk search across the filesystem materially more efficient than `Read` alone. An agent holding them alongside `WebFetch` (currently only `issue-validator`) therefore has the read-plus-outbound shape that would carry data off the machine if it were ever driven to. Exploiting it requires the agent to act on hostile instructions, which the trust model (cooperating Claude sub-agents, not an external adversary) excludes; the compensating control is the agent-level rule that file content is data, never instructions. This is an accepted limit of a lightweight hook, not a closed hole — path-containing reads the way `within_project()` contains writes would close it.
- **Exploration / planning** → also `Bash` (the hook restricts it to read-only commands).
- **Builder** → also `Edit`, `Write`, `Bash` (the hook confines `Edit`/`Write` to the project root; `Bash` is allowed without a path restriction — see Build/test Bash below).
- **Verification** → also `Bash` for running tests; no `Edit`/`Write`.

No agent is ever granted `gh` or git-state mutation — external I/O and VCS are skill-owned (§2). Each agent's exact allowlist lives in its file (`agents/<name>.md`); the architecture keeps no per-agent table.

### Hook enforcement policy (layer 3)

The architecture fixes the *policy patterns*; the exact command patterns are an implementation detail of the hook. Which pattern applies to an agent follows from its scope (above). One nuance keeps this from being "no change ever": the hook holds a small explicit read-only-agent set (`READ_ONLY_AGENTS`) because the read-only-vs-build/test Bash distinction has **no** runtime-visible discriminator in `tools:` — `code-explorer`, `implementation-planner`, and `implementation-verifier` all declare identical `Read, Bash`, so the hook is the *sole* place that distinction can live. Adding a new Bash-using agent therefore means one line in that set — a rare event for PAF's stable, first-party roster, deliberately kept as a short explicit set rather than a derive-it-from-frontmatter mechanism. Every other pattern needs no change when an agent is added. The hook `allow`s each vetted call (no prompt), `deny`s the forbidden ones below, and defers the rest:

- **Read-only Bash** (any agent granted Bash for exploration only): the hook uses an **allowlist (default-deny)** — only an explicit set of read-only commands (e.g. `grep`, `find`, `git log`, `git diff`, `cat`, `ls`) is allowed; every other Bash command is denied. Default-deny is required because a denylist of mutating commands inevitably leaks. The allowlist alone is not sufficient, because a command's *first word* does not determine what it runs or writes (#41). It is therefore applied to **every segment** of a compound command: the command is lexed quote-aware (so a `|` inside a `grep` pattern is data, not a boundary) and split at each segment boundary, and every segment's command name must be on the allowlist — which also puts the body of a `$(...)` or backtick substitution under the same rule. A **segment boundary is defined as a property, not a list**: any token made entirely of shell punctuation that is not a redirection operator ends the segment. This matters because the lexer returns a *run* of punctuation as one token, so an enumeration of known operators silently misses every operator it does not name (`|&`, `<(`, `>(`, `;;` each arrive as a single token equal to no named operator, and all four were bypasses of the first attempt at this fix). Under the property rule, syntax nobody anticipated splits the segment and whatever follows must clear the allowlist on its own. A newline is split before lexing, since the lexer counts it as whitespace and would otherwise let the next command pose as arguments to the current one. Alongside the allowlist run two checks no command name can express: **output redirection** to anywhere but `/dev/null` is denied (`echo pwned > /tmp/pwned.txt` is a write however read-only `echo` is), with a file-descriptor target accepted only when the operator itself carries `&` — `>&1` duplicates a descriptor, but `> 1` writes a file named `1`; and a command's **own write flags** are denied where the file is the command's argument rather than a shell redirection (`find -delete`/`-exec`/`-fprint*`, `tree -o`). A command that cannot be lexed at all (unbalanced quoting) is denied: what the guard cannot read, it cannot clear.
- **Project-path containment** (any agent with write access): the hook allows `Edit`/`Write` targeting the project root and denies any whose target resolves **outside** it. The project root is read from the `CLAUDE_PROJECT_DIR` environment variable available to hooks.(7) **Accepted residual risk:** this containment is keyed on `agent_type`, so it applies only to agents — not to the main thread, which the hook treats as unrestricted (above). `implement-issue` deliberately runs its plan→build phase, including the file writes, in the **main thread** (§2), so those writes are **not** path-contained by the hook. The compensating controls are structural: the write phase is reached only through native read-only plan mode and the `ExitPlanMode` developer-approval gate (nothing is written until the developer approves the concrete plan), and the skill performs no commit/push (it hands off uncommitted work, §2). Consistent with the trust model above — cooperating Claude agents, not an external adversary — this is an accepted limit, not a closed hole.
- **No external I/O** (all agents): `gh`, `glab`, the `paf-vcs` adapter, and other external I/O are denied at the hook even where `Bash` is allowed; only the skill (main thread) performs them. `WebSearch`/`WebFetch` documentation lookups are the exception — they are allowed (reading public docs is not state-changing I/O). The hook allows them for **any** agent whose call reaches it and does not special-case an agent name: which agents may reach the web is already enforced upstream by the `tools:` allowlist (layer 2), so in practice only web-authorized agents (currently only `issue-validator`) ever get here. **Accepted residual risk (web ingress):** `WebSearch`/`WebFetch` pull externally-controlled content into an agent's context — a prompt-injection ingress whose risk shape differs from the "cooperating sub-agents" trust model (the untrusted party is an external page, not another Claude agent); `issue-validator`'s findings, built from fetched content, are posted verbatim as an issue comment and can, on a `severity: error`, prompt a developer-approval gate in `implement-issue` (a decline halts the run). With the agent-name special-case gone, any future agent granted these tools in `tools:` is likewise auto-allowed with no hook-level review. The compensating controls are structural, not hook-enforced: `issue-validator` is the only agent holding these tools today, its findings pass through the skills' developer gates (`create-issue`'s draft-review gate and `implement-issue`'s approve/decline blocker gate), and no skill performs an unreviewed commit/push on the strength of fetched content. This is an accepted limit of a lightweight hook, not a closed hole. **Accepted residual risk:** this deny is a token/regex match over the command string. It catches direct and embedded invocations, including ones reached through a shell operator, a redirection, or a git global option (`git -C /tmp commit`, `git --no-pager push` — the git-state pattern skips a run of git's documented global options before matching the subcommand, since requiring adjacency to `git` made every one of them a bypass, #41; options that take a **separate** argument are named explicitly, because git accepts `--work-tree /tmp` as readily as `--work-tree=/tmp`, and an argument may be quoted and contain a space). What it cannot catch is indirection whose binary name only exists after **expansion**: an agent writing a helper script inside the project root and running it via `bash`/`python3`, `python3 -c "import urllib.request..."`, a renamed wrapper, or an encoded command (`$(echo Y3VybA== | base64 -d)`) piped to `eval`. Closing that would need runtime interception rather than pre-execution string inspection. Given the trust model (cooperating Claude sub-agents, not an external adversary), it is an accepted limit of a lightweight hook, not a closed hole.
- **No allow-list on the main thread** (#22): the hook allows the main thread unconditionally rather than gating its `Bash` on a command-family allow-list (previously `MAIN_THREAD_COMMANDS`), and its `WebSearch`/`WebFetch` calls without a prompt (previously deferred to the normal permission flow). **Accepted residual risk:** `WebFetch`/`WebSearch` pull externally-controlled content into the model's context — a prompt-injection ingress whose risk shape differs from the "cooperating sub-agents" trust model used elsewhere in this section, since the untrusted party here is an external page or search result, not another Claude agent. The compensating controls are structural, not hook-enforced: the main thread reaches these calls only inside skills whose own structure gates them — native plan mode plus the `ExitPlanMode` developer-approval gate in `implement-issue`, and in `check-out` the opening confirmation that the developer has reviewed the branch, followed by a chain of checks only one of which (the pre-merge gate's optional, single-attempt mechanical auto-fix — see `check-out` mutation posture below) may be fixed-and-continued — and no skill performs an unreviewed commit/push on the strength of fetched content. This is an accepted limit of a lightweight hook, not a closed hole.
- **Autonomous triage.** The developer no longer pre-approves individual review fixes anywhere in the pipeline; the builder agent's own triage is the only judgement before a finding is written into the code. The "a skip must be loud and justified" rule is **self-reported** — nothing independently checks that the agent complied. The same holds for the rest of the builder's triage obligations (§1, Builder). Nothing verifies that the builder recognised a **factual / self-consistency defect** as belonging to the non-skippable class rather than grading it away as discretionary. And nothing verifies that its **sweep** actually found every occurrence of a fact it changed — a missed occurrence is indistinguishable, from the outside, from there having been nothing to sweep. Compensating controls: the fixes land on **uncommitted** work, the skill surfaces the applied-vs-skipped report to the developer, and the developer's manual review at interception 2 is the curation and revert point; no commit or push happens without them running `check-out`. This is an accepted limit of a self-reported triage rule, not a closed hole.
- **Unreviewed remediation.** The code the builder agent writes while applying findings — including any file its **sweep** (§1, Builder) reaches that no plan or finding ever named — is the one slice of the final diff no review agent sees again — the review agents are never re-run inside an invocation, and `check-out`'s safety net applies only the functional lens. Its only automated check is `implementation-verifier` (the scoped tests). Compensating control: the developer's manual review, plus the trust model of cooperating agents rather than an adversary. This is an accepted limit of the pipeline's review coverage, not a closed hole.
- **Build/test Bash** (builder, verifier): Bash that is neither external I/O nor a git-state change is allowed, so tests, linters, and migrations run without prompts. **Accepted residual risk:** this allowance carries no output-redirection or write-path check the way `Edit`/`Write` does, so an agent's "do not modify source files" boundary (e.g. `implementation-verifier`'s) is enforced at the advisory system-prompt layer alone (layer 1), regardless of its model tier — lowering an agent's model does not change what the hook allows, only how reliably the agent follows its own advisory boundary. This is an accepted limit of the advisory layer, not a hook change tied to model selection.
- **Matcher coverage:** the hook is wired for `Bash|Edit|Write|MultiEdit|WebSearch|WebFetch|Task` so it sees every call that would otherwise prompt (notably web lookups and agent spawns), not just Bash/writes.

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

- **`severity: error`** denotes a **blocker** — a finding that stops the flow and requires developer action (e.g. `quality-assurer`'s unmet-criteria findings halt `check-out`; an `issue-validator` error finding prompts an informed developer-approval gate in `implement-issue` rather than an unconditional stop — §5).
- **`severity: warning`** denotes a **minor / non-blocking** finding that is passed forward (e.g. carried into the implementation plan) or surfaced for the developer to decide on.

The skill uses this field to branch.

Severity drives that **skill-level** branching; it does **not** by itself decide whether the builder may skip a finding. A finding identifying a factual or self-consistency defect is applied whatever severity it carries — see the triage rule in §1, Builder.

### Field usage by agent category

The schema is uniform; this documents which fields carry the meaningful payload, by category (§1). `summary` carries the agent's primary **textual deliverable** — a short paragraph for most agents, but the complete document for an agent whose product *is* text (synthesis). `artifacts` carries **files** only: an agent with no write access produces no artifacts and reports its product in `summary`.

- **Builder** → `artifacts` is the primary payload; `issues` usually `[]`.
- **Review / validation** → `issues` is the primary payload; `artifacts` is `[]`. By default `status` is `success` on completion regardless of what was found — reporting findings is the job, and the skill/developer decides how to act on them. The one exception is a **final gate** review (a spec-conformance check that the skill treats as a STOP point): it sets `status: failure` when the work does not meet the criteria, so the skill can halt. An agent that acts as such a gate states this in its own Output section.
- **Analysis / read** → `summary` is the primary payload; `artifacts` and `issues` usually `[]`.
- **Synthesis** → the produced document is the `summary` payload; no write access, so `artifacts` is `[]`.
- **Verification** → `status` plus `issues` (the failures) are the primary payload.

---

## 5. Loop cap, escalation, and cost reporting

### `implement-issue` retry loops

`implement-issue` has **two** fix loops, with different owners for the reason given in §2 ("the review tail, and why there are two fix-owners"). Both share the same cap and the same escalation.

**Verify-fix loop (main-thread owner).** Repairs the build itself.

- **Max retries:** 2 — after an initial failure, the **same main-thread context that built the code** (now in edit mode, post-`ExitPlanMode`) re-applies the fix (planning ran in plan mode; building and this fix run in the same main-thread context, §2), at most twice — never a cold builder agent.
- **Trigger:** `implementation-verifier` returns `status: failure` (test failures).
- **Used on retry:** the verifier's failure output (structured failure context, not free-form prose); the approved plan and the code already sit in the main thread's context.

**Review-fix loop (builder-agent owner).** Runs after the verify loop passes, over the deep review's findings.

- **The review runs exactly once per invocation.** The review agents run in parallel over the implemented change; they are **never** re-run inside the same `implement-issue` run — not in this loop and not anywhere else. The second look at the code is the developer's manual review at interception 2, backed by `check-out`'s safety-net review (below).
- **Triage is the builder's, not the developer's.** The builder agent receives **all** aggregated findings and decides which to apply, bounded by the triage rule in §1, Builder — `error` by default, a factual / self-consistency defect whatever its severity, everything else at `warning` discretionary — and by the same section's sweep obligation. The developer does not pre-select: the skill surfaces the applied-vs-skipped report and their manual review is the curation and revert point. This is why there is no `AskUserQuestion` gate here — pre-selecting fixes would put a decision in front of the developer that their own review answers better, with the code in hand.
- **Max retries:** 2 — `implementation-verifier` re-runs after the fixes are applied; on failure the builder agent fixes again from the verifier's failure output, at most twice.

**Shared to both loops:**

- **On retry exhaustion:** the skill stops and prints a structured escalation report to the developer containing what failed, the last `implementation-verifier` output, and a suggested next action. The developer reviews, adjusts the plan or issue, and re-invokes `implement-issue` manually.
- **No self-validation:** whoever applied a fix never validates it — `implementation-verifier` always runs as a separate agent after every fix.

### `check-out` safety-net review and gate

`check-out` is a **confirmation-and-ship gate**, not a review-and-fix stage: the deep review already ran in `implement-issue`, before the developer's manual review (§2). It runs a single `senior-engineer-reviewer` pass, then `quality-assurer` once, then the pre-merge validation, then finalises git/VCS.

- **One caller-framed safety net.** The reviewer is invoked as a **high-level confirmation pass**, framed at the call site (the diff was already deep-reviewed; look for critical regressions, especially the developer's hand-edits since then). The framing lives in the caller, never in the agent definition — a permanent "be shallow" instruction would damage the same agent's deep use inside `implement-issue`'s deep review, and agents are caller-agnostic (§2). Its purpose is the one slice of code no agent has seen: the developer's hand-edits. **Accepted gap:** only the functional lens is applied there; the complexity and security reviews are not repeated. A second, related limit: the hand-edits cannot be isolated from the implementation already reviewed in `implement-issue` — the skill hands the reviewer the whole branch diff (`git diff <base>`), and when the work is left uncommitted there is no git boundary that could carve the hand-edits out of it. So the reviewer may re-see, and re-flag, code the deep review already reviewed and fixed — the very rework cycle this design exists to remove. The invocation framing instructs the reviewer not to re-litigate the already-reviewed implementation, but this is not a mechanism that isolates the hand-edits; it is an accepted limit of a caller-framed, single-diff safety net, not a closed hole.
- **The gate is computed by the skill, from severity.** The skill branches on the parsed `issues[].severity`, **not** on the agent's `status` — a review agent reports `success` on completion regardless of findings (§4), and it is not a final-gate agent. `error` → STOP; `warning` → surfaced to the developer, non-blocking.
- **No fix loop, no retry — failures STOP and escalate.** Unlike `implement-issue`, `check-out` never fixes-and-continues on anything requiring judgement, and never retries a check. The one exception is the mechanical auto-fix defined in the mutation posture below, which is bounded to a single attempt and is not a fix loop. Any blocker halts the run and escalates to the developer, who resolves it and re-runs `check-out`:
  - the safety-net review returns an `error` finding → STOP
  - `quality-assurer` finds unmet criteria → STOP
  - pre-merge validation fails — after the optional auto-fix and its single re-validation, where the project defines one → STOP

  This is deliberate: `check-out` is the final human-controlled finalization stage, so the developer — not the factory — decides how to resolve a failure.
- **`check-out` mutation posture.** `check-out` may run a **tool-driven, behaviour-preserving auto-fix** as part of the pre-merge gate: on a pre-merge failure, if the project defines an auto-fix command in `CLAUDE.md`, the skill runs **that** command exactly as defined and re-runs the pre-merge validation **once**. It may **never** apply a judgement-requiring or semantic fix — that remains a STOP-and-escalate case resolved by the developer. Three properties keep this from re-opening the fix loop the point above closes: the fix is performed by the **project's own tooling**, never authored by the model (so it cannot make a semantic change under the guise of a format fix); the re-validation **is** the fixability split, deterministically — whatever the tool could fix is gone, whatever remains needs judgement by definition, so nothing has to *judge* which failures were mechanical; and the attempt is capped at **one**, so a failure that survives it escalates exactly as it does today. The command is entirely **project-defined and optional** — the architecture names no tool or flag (consistent with `CLAUDE.md` being a content checklist, not a format), and a project that defines none keeps today's STOP-on-fail behaviour unchanged.

  **Accepted residual risk:** this mutation is a new shape of exposure in `check-out`, not one already covered elsewhere in this document. It runs downstream of every review layer `check-out` has — the safety-net review (step 2), `quality-assurer` (step 3), and the developer's own manual review at interception 2, all of which precede it — and its diff is committed, pushed, and put in front of the MR/PR with no review agent re-run and no additional developer-approval gate; the only signal surfaced is an informational `git diff --stat` after it runs. The claim above that a tool-driven fix "cannot make a semantic change under the guise of a format fix" is an assumption about the configured command's behaviour, not something PAF verifies at runtime — an aggressive auto-fix mode could still ship an unreviewed semantic change. The single-attempt cap and the "never a tool/flag you chose yourself" constraint are themselves enforced only at the advisory prompt layer, consistent with "No allow-list on the main thread" above. The command is also `check-out`'s first `CLAUDE.md`-sourced value that **writes** files which are then committed and pushed, run with the developer's full privileges under only step 1's "ready to finalise" confirmation — which precedes, and cannot anticipate, a mid-run pre-merge failure. The compensating control is structural, not an added gate: the developer's own review at the MR/PR interception point (§2) is still the last human eyes on this diff before merge, exactly as for every other change `check-out` ships. This is an accepted limit of a mechanical, tool-driven auto-fix, not a closed hole.

### Verification scope — two tiers

The factory has two distinct verification points with deliberately different scopes:

- **`implementation-verifier` (scoped, in-loop).** Runs a **targeted subset** of the test suite — the tests covering the changed area/module (e.g. the affected Django app, or the affected CDK service/resource), not merely the changed test files and not the whole suite. **Tests only:** never the project's lint command and never its full pre-merge command, both of which belong to the tier below. It runs inside **both** of `implement-issue`'s fix loops (up to 3× each), so a scoped run keeps them fast and cheap — and pulling the fuller command into this tier would inflate exactly the cost and latency the split exists to contain.
- **Pre-merge validation (full, at the gate).** Runs the project's **full** test/lint suite once at `check-out` — the final safety net that catches any cross-module regression a scoped run could not see, and the tier the lint command belongs to. It is the only verification `check-out` runs: it authors no fixes of its own, and its sole mutation is the optional mechanical auto-fix defined in the mutation posture above, which this same full command re-validates — so there is no scoped run there.

This two-tier split is the reason both points exist: fast scoped feedback during implementation, full validation before the PR.

**Implementation-defined:** how the affected area/module is determined (e.g. derived from `full-stack-dev`'s reported `artifacts` plus project conventions) and the exact scoped and full commands are **project-specific and sourced from `CLAUDE.md`** — not fixed by this architecture.

### `issue-validator` escalation

`issue-validator` validates an approach against authoritative docs **and** the repository. It always runs in `create-issue`; in `implement-issue` it runs **only for issues PAF did not already validate** — a shift-left pass plus a source-aware safety net. The validator never calls `gh` itself — the caller acts on its findings.

**In `create-issue` (authoring time, before the issue exists).** The **whole** drafted issue is validated *before* it is posted, so a defect is caught at the source rather than surfacing later. This closes the gap where `issue-writer` (read-only, no web access) faithfully transcribes an unverified approach.

- **What is checked** — both externally-verifiable claims (a CLI flag, an API signature, library behaviour, and the cited spec's caveats and scope limits, not just its headline rule) **and** repo-grounded ones (a named path that does not exist, a description of current behaviour that contradicts the code, an approach infeasible against the existing implementation).
- **Scope discipline** — the skill never narrows the validator's scope by declaring part of the draft "given," and never skips the step; a draft with no external claims still makes checkable claims about the repository. What the validator does **not** judge is how completely the issue enumerates the files to touch: the stated scope is a hint, and the implementer derives the real files from the issue's intent and the live repo, so an incomplete file list is never a blocker (see `agents/issue-validator.md`). This removes the false-blocker class where an otherwise-sound issue was stopped for omitting a file.
- **Findings handling** — because nothing is posted yet, a `severity: error` blocker does **not** stop the run: the skill folds the validator's prescribed correction back into a re-draft and re-validates (capped at two rounds). Any residual blocker, and all `warning` findings, are surfaced at the draft-review human gate for the developer to resolve.
- **PAF-validated marker** — every issue `create-issue` posts has passed both the validator and the developer's review gate, so the skill appends a marker as the posted body's final line: a lone line reading `PAF`. It is a **visible** footer, not a hidden HTML comment — a hidden comment would have to survive rendering, forcing `paf-vcs view-issue` to fetch the raw body, whereas a plain line survives any rendering and keeps `view-issue` a one-liner. It is `implement-issue`'s signal that PAF already validated and the developer already approved this issue. Detection anchors on the **final line being exactly `PAF`**, never the word elsewhere (issue prose is full of "PAF"). It is appended even when the developer approved despite a residual blocker at the gate: that blocker was surfaced and adjudicated here, so re-raising it at implementation time would add nothing.

**In `implement-issue` (implementation time, against the posted issue).** The skill first reads the fetched issue (via `paf-vcs view-issue`) and checks whether its final line is exactly `PAF` (verified: `gh issue view`'s non-interactive output ends with the issue body, so the appended marker is the last line; the GitLab path inherits the pending #14 validation caveat):

- **Marker present** → the issue was already validated and developer-approved in `create-issue`; the skill **skips** the validator entirely and proceeds to plan mode. This removes the redundant re-validation that — because same-definition LLM agents are non-deterministic — could otherwise "block" an issue `create-issue` had already approved (the recurring validated-then-disabled failure).
- **Marker absent** (a hand-written issue, or one created outside PAF — the only validation it ever gets) → the skill runs the validator and posts **only** the actual findings as an issue comment — one line each, none when there are none (never the verdict or a recap of confirmed claims). A `severity: error` no longer stops unconditionally: the skill informs the developer, quoting the finding(s), and asks via `AskUserQuestion` whether to fold the blocker into the plan and continue (**approve**) or stop (**decline**; a missing answer counts as decline — never auto-approve). `warning` findings are posted (terse) and carried into the implementation plan.

**Accepted residual risk (false skip).** The marker is content in the issue body, which admits two symmetric false-skip cases. (1) *Marker survives manual edits* — an issue PAF authored and a developer then edited **after** creation still carries it and is skipped at implementation time. (2) *Coincidental content* — a hand-written, non-PAF issue whose body happens to **end** with a lone line reading `PAF` would be mistaken for a validated one and skip the validator that is otherwise its only check; anchoring detection on the **final line being exactly `PAF`** (not the word anywhere — it is common in this repo's prose) makes this unlikely but not impossible. Both share one compensating control: the plan-review gate (`ExitPlanMode`) is where the concrete plan is scrutinised against the live repo before any code is written, so an infeasible approach surfaces there regardless of how the issue was validated. Re-validating these edge cases is traded for never re-validating a PAF issue (and never hitting the non-deterministic false blocker); this is an accepted limit, not a closed hole.

### Malformed-contract escalation

Contract parsing must be defensive — the whole pipeline depends on it. The skill must:

1. Extract the **last** fenced ` ```yaml ` block from the agent's final message.
2. Parse it, and **validate** that all required keys are present and that enum fields hold allowed values (`status` ∈ {success, failure, needs_retry}; `severity` ∈ {error, warning}; `action` ∈ {created, modified, deleted}).
3. On any missing block, parse error, missing key, or invalid enum value → **STOP and escalate to the developer, including the agent's raw output** in the report so the failure is diagnosable.

The skill never proceeds on a partial or guessed parse.

### Cost reporting

Every skill run ends with a single report of the **token cost of that invocation**.

- Cost is **not** self-reported by agents. The skill computes it from the session transcript at `transcript_path`, which records per-message `usage` (`input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`) and `model`, enabling correct per-model pricing.(7) (9)
- **Per-invocation slice, not the whole session.** A skill marks its start at its first step and prices only the transcript slice from that mark onward (main-thread and subagent messages alike). This is required because multiple skills can run in **one** CLI session (see the aggregation note below): pricing the whole transcript would re-price an earlier skill's tokens and inflate the feature total, and a `create-issue` run inside a large multi-day session would price the entire session. Each run is therefore costed as a disjoint slice.
- **Pricing is per model, not per snapshot.** A model id is canonicalised before it is priced: a trailing snapshot date (`-YYYYMMDD`) is stripped, so a dated snapshot and its alias are the same model at the same rate.(10) The price table's keys are therefore **dateless** — a dated key could never match — and a dated snapshot of a priced model is an exact match, not a fallback.
- **Unpriced models are never dropped.** If the session used a model still absent from the price table after that canonicalisation, its tokens are priced at the latest known rate of the same family (opus/sonnet/haiku) and the report flags that the price table must be updated — an undercount is never silently produced.
- **Currency.** Anthropic bills in USD; PAF reports cost in **EUR**, converted with a factory-maintained USD→EUR rate kept alongside the per-model price table. Both are updated together and carry their source and date.
- **Tokens as well as money.** The report shows the token breakdown — in, out, cached, total — beside the EUR cost, in both the CLI output and the PR. Money alone hides whether a run was expensive because of volume or because of model choice; the counts are already collected for pricing, so surfacing them costs nothing.
- The internal mechanism for attributing usage to individual agents is an implementation detail; the architecture requires only that the final total is reported.

#### Cross-skill cost aggregation

A feature spans the three main-skill runs — `create-issue`, `implement-issue`, `check-out`. These are usually separate Claude Code sessions, but they need not be: `implement-issue` and `check-out` in particular are often run back-to-back in a **single** CLI session (which is exactly why each run prices only its own invocation slice, above). Claude Code has no native cross-session cost aggregation, so PAF maintains its own **per-feature cost ledger**:

- **Keyed by issue number.** Every skill run appends its own per-invocation cost to the ledger entry for the feature's issue. `create-issue` knows the issue number after posting; `implement-issue` is given it; `check-out` derives it from the branch name (`feature/<issue-number>-<...>`).
- **User-scoped, never in the project.** The ledger lives under the user's `~/.claude/` namespace, not in the target repository — no `.paf/` directory, no gitignore entry. This preserves PAF's project-agnostic principle: installing and running PAF leaves no trace in the project.
- **Totalled at check-out.** `check-out` records its own run, then sums every entry for the feature and writes the **total cost — with a per-skill breakdown — into the PR description**, then removes the ledger. This gives the PR reviewer, who never sees the CLI session, the whole feature's cost.
- **Graceful degradation.** If the branch → issue-number mapping is unavailable, `check-out` reports whatever entries it can correlate rather than failing.

The exact ledger location, record format, and pricing table are implementation details of the shared cost helper; the architecture fixes only that per-feature cost is aggregated across the three main skills, stored in user scope, reported in EUR with a token breakdown, and surfaced in the PR.

---

## 6. CLAUDE.md as the single source of project context

`CLAUDE.md` is the single source of project-specific context, and it is **loaded automatically into every agent** — there is no manual injection.

- **Auto-loading is native and not optional.** Every custom subagent loads the same CLAUDE.md / memory hierarchy the main conversation loads (user `~/.claude/CLAUDE.md`, project `./CLAUDE.md` or `./.claude/CLAUDE.md`, project rules, `CLAUDE.local.md`, managed policy). Only the built-in `Explore` and `Plan` agents skip it, and there is no frontmatter field or per-agent setting to change which agents skip it.(6) (8)
- **It depends on launch location, not agent config.** The hierarchy is resolved by walking up from the working directory, so the project-root `CLAUDE.md` reaches every agent as long as Claude Code is launched from within the project (the normal case). PAF keeps project context in the **root** `CLAUDE.md`; subdirectory `CLAUDE.md` files load on demand, not at launch, so PAF does not rely on them.
- **No duplication.** A value that exists in `CLAUDE.md` is never repeated in an agent prompt or skill file. `CLAUDE.md` holds project-specific context (stack, entry points, conventions, exact test/lint/pre-merge commands, and the optional auto-fix command), kept under ~200 lines. Agent prompts hold only factory-level role, tool scope, and output-contract instructions.
- **Verification.** The `InstructionsLoaded` hook can log exactly which instruction files reached each agent and may be used to confirm the project `CLAUDE.md` is loaded into every agent.(7)

This is why skills do not manually inject CLAUDE.md sections into agents — it is unnecessary given native auto-loading.

- **Strict sourcing — no cross-project bleed.** Project-specific values come **only** from *this* project's `CLAUDE.md` and repository. Skills must never substitute a value — especially a filename or command — from the operator's memory, another project, or a prior session. Auto-recalled memories are unrelated background and may name files that do not exist in the current repo. If a value a step needs is not defined here, the skill **STOPs and asks the developer** rather than inventing or borrowing one. Each skill states this guardrail in its own `Input` section, and the verification / pre-merge steps STOP when no command is defined.

---

## Sources

All architecture decisions are grounded in the official Claude Code documentation. Inline citations above use these numbers:

1. Subagents — Choose a model. https://code.claude.com/docs/en/sub-agents#choose-a-model
2. Subagents — Chain subagents / What loads at startup / Available tools (`AskUserQuestion`, `EnterPlanMode`, and `ExitPlanMode` depend on the main conversation's UI/session state and are unavailable to subagents even when listed in `tools` — `ExitPlanMode` unless the subagent's `permissionMode` is `plan`) / Spawn nested subagents (a subagent may spawn subagents up to depth 5, as of v2.1.172). https://code.claude.com/docs/en/sub-agents#chain-subagents
3. Subagents — Invoke subagents explicitly. https://code.claude.com/docs/en/sub-agents#invoke-subagents-explicitly
4. Subagents — Control subagent capabilities. https://code.claude.com/docs/en/sub-agents#control-subagent-capabilities
5. Subagents — Supported frontmatter fields (`name` is received by hooks as `agent_type`). https://code.claude.com/docs/en/sub-agents#supported-frontmatter-fields
6. Subagents — What loads at startup. https://code.claude.com/docs/en/sub-agents#what-loads-at-startup
7. Hooks — `PreToolUse` input schema and `agent_type`, exit codes, environment variables (`CLAUDE_PROJECT_DIR`), `transcript_path`, `InstructionsLoaded`. https://code.claude.com/docs/en/hooks
8. Memory — How CLAUDE.md files load. https://code.claude.com/docs/en/memory#how-claude-md-files-load
9. Manage costs effectively. https://code.claude.com/docs/en/costs
10. Model ids and versions — the id grammar `claude-{name}-{major}[-{minor}]` (4.6 and later) and `claude-{name}-{major}-{minor}-{YYYYMMDD}` (before it), which is what makes a trailing 8-digit segment a snapshot date rather than a version. https://platform.claude.com/docs/en/about-claude/models/model-ids-and-versions
