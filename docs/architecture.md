# PAF Architecture

This document is the single source of truth for the design decisions of the Personal Agentic Factory (PAF) and the reasons behind them. All agent definitions, skills, and hooks must follow it without re-deciding what is settled here.

PAF splits responsibilities cleanly:

- **Skills own the workflow** — sequencing, human approval gates, and all external I/O (GitHub via `gh`, git state, running tests, posting results).
- **Agents own the cognitive work** — code analysis, synthesis, review — each with a defined tool scope and a model suited to its task.
- **The human owns the decisions** — the factory accelerates and structures the work; it does not replace judgement.

Every decision here has been verified against official Claude Code documentation or an established best practice — nothing is guessed. Where a decision depends on a specific Claude Code behaviour, the source is cited inline and collected under [Sources](#sources). Where a decision states no external source, its record says so.

**What this document holds — WHAT and WHY.** WHY — the decisions, their reasons, their sources, and the risks accepted with them — lives only here. WHAT PAF does — steps and their order, output formats, commands, the hook's rules as implemented — lives only in the file that runs it (a `SKILL.md`, an agent file under `agents/`, the hook, or a script), plus its human explanation: `docs/skills/<skill>.md` for a skill, `hooks/README.md` for the hook, `agents/README.md` for the agents, and `docs/authoring/*.md` for the agent and skill file formats. This document never restates WHAT: a record points to the file or skill step that implements it. Two copies are deliberate, because the runtime needs them: the output-contract block in every agent file (an `@import` does not expand in an agent body — [`agent-definition-format.md`](authoring/agent-definition-format.md)), and the strict-sourcing paragraph stated inline in every `SKILL.md`.

**Record format.** Decisions are short records, adapted from the Architecture Decision Record practice (23), grouped under the section and subsection headings. Each record has a bold title and these fields:

- **Decision** — what is decided, pointing to the file that implements it.
- **Why** — the reason.
- **Source** — the numbered source(s) below, the issue that decided it, or "PAF design choice; no external source."
- **Accepted risk** — only when one exists.

A record contains no step-by-step flow, no output format, and no command line.

---

## 1. Agents

**Specialist agents, no roster**

- **Decision:** A PAF agent is a specialist subagent owning one cognitive responsibility, with a tool scope (§3) and a model suited to its task. Agents are caller-agnostic (§2) and all follow the output contract (§4). This document keeps no roster: each agent is self-describing in `agents/<name>.md`, and how to author one is in [`agent-definition-format.md`](authoring/agent-definition-format.md).
- **Why:** The files in `agents/` are the current set; a roster here would be a second statement of it.
- **Source:** PAF design choice; no external source.

### Model selection

**Aliases, not pinned IDs**

- **Decision:** Each agent declares its `model` as an alias (`haiku`, `sonnet`, `opus`), never a pinned ID, in its own file under `agents/`.
- **Why:** Model upgrades then apply automatically.
- **Source:** (1)

**Choose by reasoning and the cost of a miss**

- **Decision:** An agent's model is chosen by how much reasoning the work genuinely requires and how expensive a miss is once it propagates downstream, not by a coarse verb list. **Mechanical / I-O-bound, no reasoning** work (e.g. reading and summarising files; running tests, or a UI check, and reporting pass/fail) gets the cheapest capable model (currently `haiku`); one narrow discriminator inside otherwise mechanical work does not by itself lift an agent to mid-tier. Work that **requires reasoning, judgement, or interpretation** (planning, building, reviewing) gets the mid-tier model (currently `sonnet`). The top model (`opus`) is reserved for work that genuinely needs the deepest reasoning, or where a miss is uniquely expensive because it happens **before** there is any built work for a later reviewer to catch it — it is never the default. **Validating** an approach against authoritative documentation *and* the repository before it enters the build pipeline is such a case; where it runs and how its `error` findings are handled is the `issue-validator` escalation (§5).
- **Why:** Mechanical agents often run at the start of every flow, or repeatedly inside a fix loop, so keeping them cheap matters. A defect missed during validation — unlike one missed in the post-build reviews (§4, Field usage by agent category) — propagates into everything built after it. The tiering itself is a PAF design choice.
- **Source:** (1)

### Agent categories

**Categories drive scope and payload**

- **Decision:** Agents fall into a few stable shapes — Analysis / read, Synthesis, Builder, Review / validation, Verification — and the category drives the agent's tool scope (§3) and its output field usage (§4, Field usage by agent category).
- **Why:** Scope and payload follow from the shape of the work, so they are derived from the category rather than decided agent by agent.
- **Source:** PAF design choice; no external source.

**Analysis / read**

- **Decision:** Explores or reasons over code and returns a summary or plan. Read, plus **read-only Bash** for codebase exploration (§3).
- **Why:** The work reads and searches code and never changes it.
- **Source:** PAF design choice; no external source.

**Synthesis**

- **Decision:** Produces a document (e.g. an issue) as text. Read-only.
- **Why:** Its product is text returned in the output contract, so it needs no write access.
- **Source:** PAF design choice; no external source.

**Builder**

- **Decision:** Edits files, writes tests, runs commands — read + write, project-confined. Given a plan, a builder implements it as decided; given review findings, it triages them, and the triage is bounded by the issue, never widens the work, and is reported applied-vs-skipped with reasons. A finding that contradicts an explicit decision or out-of-scope item in the issue is skipped whatever its severity; a factual or self-consistency defect is applied whatever its severity. The builder also sweeps: a change to a fact, rule, or name stated in several places is made in all of them. The rules as implemented are in `agents/full-stack-dev.md` (Input, Task, Output).
- **Why:** The issue body is the scope the developer approved, and severity cannot override it. Triage fixes defects and never extends the feature. Severity grades impact, while a factual or self-consistency defect is a correctness defect regardless of it. The sweep keeps an edit from leaving the repository self-contradicting, and it is not a widening: it restates the *same* change elsewhere rather than adding a different one.
- **Source:** PAF design choice; no external source.

**Review / validation**

- **Decision:** Inspects implemented code, or checks a proposed approach against authoritative sources **and the repository it targets**, and reports findings. Read-only, plus read-only repo search and, for validating against external documentation, web lookup (§3). Code reviewers treat what the issue explicitly decides or places out of scope as settled, not a finding; a defect in how such a decision was implemented still is. As implemented: the shared review input (§4, Input delivery) and `skills/paf-shared/paf-review-input.py`.
- **Why:** The issue body is the scope the developer approved, as for the Builder.
- **Source:** PAF design choice; no external source.

**Verification**

- **Decision:** Runs tests (and, for a UI change, the project's UI check) and reports pass/fail. Read + execute, no writes.
- **Why:** It checks the work and never changes it.
- **Source:** PAF design choice; no external source.

**No I/O agent**

- **Decision:** There is intentionally **no `github-*` or I/O agent**; GitHub and git interaction is owned by the skill (see [Section 2](#external-io-and-vcs-state-are-skill-owned)).
- **Why:** GitHub and git interaction is mechanical, not cognitive.
- **Source:** PAF design choice; no external source.

---

## 2. Skill-to-agent orchestration

### Orchestration model

**The orchestrator is the main conversation**

- **Decision:** The orchestrator is always the main conversation (the skill), never a subagent. The skill runs in the main thread, chains agents from there — each agent returns its result to the main thread, which passes the relevant context into the next agent's prompt — and owns the human gates, external I/O, and cost accounting.
- **Why:** PAF is human-gated, and the human-gate tools — `AskUserQuestion` and plan mode — are main-thread-only: they are unavailable to subagents even when listed in `tools`, so a subagent orchestrator could not pause for a developer decision. The skill also owns all `gh`/git I/O and computes the run's cost from the transcript, both main-thread concerns (see [External I/O and VCS state are skill-owned](#external-io-and-vcs-state-are-skill-owned) and [Section 5](#5-loop-cap-escalation-and-cost-reporting)).
- **Source:** (2)

**No nested delegation**

- **Decision:** PAF does not use nested delegation: orchestration stays flat and in the main thread. Agents are single-responsibility specialists that do not orchestrate other agents — by choice, not by limitation.
- **Why:** Claude Code allows a subagent to spawn its own subagents, up to a fixed depth of five (as of v2.1.172). Nested agent hierarchies hide intermediate work from the developer, from the human gates, and from cost attribution — the opposite of PAF's human-control design.
- **Source:** (2)

**Explicit invocation by name**

- **Decision:** Each agent is invoked explicitly by name (via the Agent tool / `@agent-<name>`), never by autonomous natural-language delegation.
- **Why:** Explicit invocation guarantees the named subagent runs; natural-language naming only lets Claude decide whether to delegate.
- **Source:** (3)

**Sequencing is prompt-based**

- **Decision:** A skill's fixed sequence is enforced by explicit, imperative instructions in its `SKILL.md`, executed by the main-thread model, so skills are written imperatively, not suggestively. The body shape is in [`skill-definition-format.md`](authoring/skill-definition-format.md).
- **Why:** Claude Code skills are prompt-based — there is no harness-level deterministic state machine to enforce a sequence.
- **Source:** PAF design choice; no external source.

**Agents are caller-agnostic**

- **Decision:** An agent definition never references a specific skill — not by name and not by behaviour — and never names another agent. Its prompt describes only what it receives and what it returns, never who invokes it or where it sits in a pipeline.
- **Why:** Agents are reusable specialists: any caller may invoke any agent — a skill, or a developer directly (e.g. `@code-simplifier review the current branch`). An agent operates solely on the input it is handed and the output contract it returns.
- **Source:** PAF design choice; no external source.

#### Plan mode for the plan→build phase (`implement-issue`)

**Plan→build in the main thread**

- **Decision:** A deliberate exception to "cognitive work is delegated to agents": in `implement-issue` the plan→build phase runs in the main thread through native plan mode — explore, plan, approve at `ExitPlanMode`, and build in one context — not as a separate planner agent handing off to a separate builder agent. Implemented in `skills/paf-implement-issue/SKILL.md`, steps 4–7; what the plan may contain beyond the issue is in §5. Validation (`issue-validator`) and verification (`implementation-verifier`) remain delegated agents.
- **Why:** Two subagents do not share context: the builder starts cold, re-reads the repo, and reconstructs file state to re-derive edits the planner already worked out — exploration happens twice and the "plan" carries intent rather than concrete edits. One context means an approved plan applies in seconds. `EnterPlanMode`/`ExitPlanMode` are main-thread-only tools, which is why this lives in the skill's main thread. Validation and verification do not sit on the plan→build cold-context boundary, so their isolated contexts cost nothing there.
- **Source:** (2)
- **Accepted risk:** The build phase's file writes are main-thread writes, so they are not subject to the hook's agent-scoped project-path containment (§3) — a residual risk documented in §3, compensated by the native read-only plan phase and the `ExitPlanMode` approval gate that precede any write.

**Turn discipline in the plan→build phase**

- **Decision:** The skill instructs the plan→build phase to batch independent tool calls into one turn and not to re-read files already in context — never at the cost of a read the plan needs (`skills/paf-implement-issue/SKILL.md`, steps 4 and 7).
- **Why:** This phase is the factory's longest main-thread stretch, and every turn resends the whole conversation, so turns — not reads — multiply cost.
- **Source:** (14)

**The main-thread sweep**

- **Decision:** The main-thread implementer carries the builder's sweep obligation (§1, Builder): a fact, rule, or name the change touches is updated in every place the repository states it, located while planning and applied with the rest of the approved plan. In the review-fix loop the delegated builder agent carries it.
- **Why:** The sweep is inherent to authoring a change, so it binds whichever owner authors it — here the main-thread plan→build path, the dominant authoring path and the one that writes the plan's edits. The `ExitPlanMode` gate is where the developer sees the swept occurrences before any write.
- **Source:** PAF design choice; no external source.

**The review tail, and why there are two fix-owners**

- **Decision:** The deep review — the review agents, a builder agent's triage of their findings, and re-verification — sits in `implement-issue`, before the hand-off, not in `check-out` (`skills/paf-implement-issue/SKILL.md`, steps 9–11). Its two fix loops have two owners: the verify-fix loop stays in the main thread, and the review-fix loop is delegated to a builder agent. The acceptance loop that closes the run (§5) stays in the main thread. `implement-issue` owns producing correct, clean, reviewed code; `check-out` owns confirming and shipping it (§5).
- **Why:** A deliberate reversal of the original sequencing: placed in `check-out`, the automated review ran after the developer's manual review of the implemented code, so its fixes changed code the developer had already signed off, forcing them to re-review and re-test it. Reviewing before the hand-off means the manual review lands on already-reviewed-and-fixed code. The two owners follow one rule — keep work in-context when losing the context would cost re-derivation, delegate it when it would not. The verify-fix loop repairs the build itself, and that context still holds the plan and the exact edits, so a cold builder agent would only re-derive them. Applying a discrete list of findings is not a re-build: each finding names its own location and remedy, so nothing must be re-derived; delegating it also returns those writes to the hook's agent-scoped path containment (§3). An unmet acceptance criterion is a gap in executing the approved plan, so the main thread that holds the plan fixes it.
- **Source:** PAF design choice; no external source.

#### Main-thread readiness check (`init`)

**`init` compares in the main thread**

- **Decision:** A second deliberate exception to "cognitive work is delegated to agents": `init` compares the project instructions file against the content checklist in the main thread, without agents (`skills/paf-init/SKILL.md`). The deterministic part of the check (git, the `origin` host, the VCS CLI, the Claude Code version, which instructions file loads) is a stdlib script, `paf-shared/paf-readiness.py`, which reuses `paf-vcs` for the host and CLI rules so they stay single-sourced.
- **Why:** The comparison is by meaning (does the file name an exact test command and the base branch), which is cognitive work, but delegating it would buy nothing: an agent would start cold and re-read the same instructions file and template the main thread already holds. The skill needs the main thread anyway, to ask the developer through `AskUserQuestion` (main-thread-only) and to write the fix.
- **Source:** (2)
- **Accepted risk:** Like the plan→build phase, its writes are main-thread writes outside the hook's agent-scoped path containment (§3). They only happen after the developer picks a fix at the skill's single `AskUserQuestion`, and nothing is committed.

#### External I/O and VCS state are skill-owned

**Skill-owned external I/O**

- **Decision:** All VCS API calls (`gh`/`glab`), git state transitions (branch, commit, push), test-execution triggers, and result posting happen in the main thread / skill. Agents never call `gh`/`glab` or change git state — `full-stack-dev` edits files, but the skill owns branching, committing, pushing, and opening issues/MRs/PRs. The hook enforces it (§3).
- **Why:** Mechanical, side-effectful I/O must stay deterministic and auditable, so it lives in the orchestration layer, not inside non-deterministic LLM agents.
- **Source:** PAF design choice; no external source.

**Shared I/O helpers**

- **Decision:** Where the same `gh`/`glab`/`git` sequences recur across skills, they are factored into shared helpers in `paf-shared/` rather than duplicated or pushed into a dedicated agent.
- **Why:** The same as for skill-owned I/O: deterministic and auditable, in the orchestration layer.
- **Source:** PAF design choice; no external source.

**Posted text is never retyped**

- **Decision:** Text whose exact bytes matter is posted from a file, never retyped by the model after the fact. There is one such text: the MR/PR cost section, which must be the cost helper's output verbatim; how `check-out` builds and posts that file is its step 7 (`skills/paf-check-out/SKILL.md`). Only the main thread touches this file; agents receive content inline, or — the code reviewers — through the review input file (§4, Input delivery). `create-issue` posts its body straight from a heredoc.
- **Why:** A heredoc retyped in a later turn can differ from its source. `create-issue` has no approval gate whose approved text a file would have to preserve.
- **Source:** PAF design choice; no external source.

**Where the posted file lives**

- **Decision:** The file lives in a private directory from Python's `tempfile.mkdtemp`.
- **Why:** It is cross-platform and readable only by its creator, and Python 3 is already PAF's one runtime dependency, so this holds on any OS. Two other locations were rejected. The session scratchpad that Claude Code offers the model appears in no documentation and has no skill substitution — the documented ones, such as `${CLAUDE_SESSION_ID}` and `${CLAUDE_SKILL_DIR}`, include no scratchpad path. `~/.claude/paf/` is a protected path, and writes there are never auto-approved.
- **Source:** (18) (17) (15)

**Why the posted file runs prompt-free**

- **Decision:** Writing, appending to, reading, and removing the temporary file needs no permission prompt; PAF relies on that.
- **Why:** A write, or an `>>`/`<` redirect, to a path outside the working directories is normally checked like a direct file write or read. But the hook returns `allow` for every main-thread call (§3), and a hook `allow` skips the prompt. The exceptions are ask/deny rules, protected paths, network paths, critical-path `rm`, and non-read-only calls in plan mode, and a temp directory hits none of them.
- **Source:** (16) (15). Verified empirically on Claude Code 2.1.303 with the hook installed: in auto mode, and headless in default permission mode, the whole sequence of creating the directory, a `Write`, a second `Write` overwriting without a `Read`, an append, a read, and removing the directory ran with no prompt and no `permission_denials`.

**VCS provider abstraction**

- **Decision:** The skills call one shared adapter, `skills/paf-shared/paf-vcs`, instead of `gh`/`glab` directly. It auto-detects the provider per project from the `origin` remote's host — `github.com` and `gitlab.com` only, and any other host fails clearly, with no silent fallback — and exposes provider-neutral verbs. Self-hosted/custom-domain instances and an explicit provider override are out of scope.
- **Why:** The two CLIs' flag differences are normalised in one place, so the skills stay provider-neutral.
- **Source:** PAF design choice; no external source.

### Human interception model

**The skill boundaries are the primary gates**

- **Decision:** The factory's main skills — `create-issue` → `implement-issue` → `check-out` — are three separate, developer-invoked skills, not a single end-to-end skill. The developer reviews the result of each before running the next: the posted issue (or the linked issues of a split run), the implemented code and tests, and the MR/PR, which they merge. This trip is fixed: further skills may be added alongside it, but the main skills and their order do not change.
- **Why:** This three-way split is the human-control architecture: the gaps between the main skills are the mandatory review gates.
- **Source:** PAF design choice; no external source.

**In-skill interception mechanisms**

- **Decision:** A skill may also pause mid-run for developer input through two mechanisms: a plan-approval pause (the skill presents a plan and waits for explicit confirmation before implementing) and a structured decision through `AskUserQuestion` (e.g. choosing between two viable approaches, or resolving an ambiguity the skill must not decide alone). How many in-skill interceptions a skill has, and where, belongs to the skill: its `SKILL.md`, and the "Human interception points" section of its `docs/skills/` page. The architecture defines only the mechanisms.
- **Why:** Both mechanisms are main-thread tools, available to the skill but not to subagents.
- **Source:** (2)

### Per-skill orchestration maps

**Each skill's flow lives with the skill**

- **Decision:** A skill's flow, diagram, and diagram legend live on its own page under `docs/skills/`, and its `SKILL.md` is what runs; this section only points to them. The project instructions (`CLAUDE.md` or `AGENTS.md`) are loaded automatically into the main thread and into every agent ([Section 6](#6-project-instructions-as-the-single-source-of-project-context)), so no flow passes them explicitly.
- **Why:** A flow restated here is a second copy of behaviour that the WHAT/WHY rule (introduction) keeps only in the file that runs it and its human page.
- **Source:** #124, #125.

#### `init`

Implemented — see [`docs/skills/init.md`](skills/init.md) for the current flow and explanation. It is a setup and health check run before the main skills, not part of the feature pipeline.

#### `create-issue`

Implemented — see [`docs/skills/create-issue.md`](skills/create-issue.md) for the current orchestration diagram and explanation.

#### `implement-issue`

Implemented — see [`docs/skills/implement-issue.md`](skills/implement-issue.md) for the current orchestration diagram and explanation.

#### `check-out`

Implemented — see [`docs/skills/check-out.md`](skills/check-out.md) for the current orchestration diagram and explanation.

---

## 3. Tool access scope per agent

### Enforcement model (three layers)

**Three enforcement layers**

- **Decision:** Tool restriction is enforced in three layers. (1) **Advisory (system prompt):** the agent's prompt describes its role and what it should not do — guidance only, which the model may ignore, so not an enforcement layer. (2) **Native, coarse (frontmatter):** each agent's `tools` allowlist, real harness-level enforcement at the **whole-tool** granularity — a tool the agent does not have is genuinely unavailable. (3) **Hook, granular (`PreToolUse`):** one centralized hook, `hooks/PreToolUse-agent-guard.py`, is the factory's **allow+deny authority**: it allows the factory's vetted calls, denies the sub-tool restrictions frontmatter cannot express, and gives no decision on anything it does not recognize. Its rules as implemented are explained in `hooks/README.md`.
- **Why:** Only layers 2 and 3 are enforced by the harness. Allowing a vetted call is what makes a run autonomous *between* the deliberate human gates: without it, every permitted call falls through to a prompt, because frontmatter `allowed-tools` grants are per-turn and do not cover subagents' tool calls. Deferring on what the hook does not recognize keeps Claude Code's normal permission prompt as a human safety net.
- **Source:** (4) (7)

**Why the hook is required and not redundant**

- **Decision:** The sub-tool restrictions live in the `PreToolUse` hook (layer 3), not in frontmatter.
- **Why:** Frontmatter can allow or deny a tool *as a whole* but cannot restrict it conditionally. An agent granted Bash for read-only exploration, and `full-stack-dev` (project-path-only writes), need command- and path-level rules that only a `PreToolUse` hook inspecting `tool_input` can apply.
- **Source:** (4) (7)

**How the hook identifies the active agent**

- **Decision:** The hook identifies the calling agent by the `agent_type` field of the hook payload, which carries the agent's `name`. When the field is absent, the call is the main thread's (the orchestrating skill); an empty or unknown `agent_type` is never treated as the main thread (`hooks/README.md`).
- **Why:** `agent_type` is the documented, native mechanism, so no environment variable or prompt-header sentinel is needed, and it is omitted entirely for the main thread.
- **Source:** (7) (5), #44.

**The hook governs only PAF's own agents**

- **Decision:** The hook decides only for PAF's own agents, named in one explicit set in the script (`PAF_AGENTS`). An agent whose `agent_type` is not in it — a Claude Code built-in such as `general-purpose` or `Explore`, or the user's own — gets no decision.
- **Why:** PAF then behaves for those agents as if it were not installed.
- **Source:** #122.

**One centralized hook script, registered by frontmatter**

- **Decision:** The whole policy lives in one script, keyed on `agent_type`. The PAF skills and every PAF agent register that same script through an identical frontmatter `hooks` block that only points at the script and holds no policy (the block is in `hooks/README.md`, Registration). The hook is not in the user-level `settings.json`: the installer writes no settings entry and, on upgrade, removes the one an earlier version wrote (`scripts/install.sh`). The registered command reaches the installed script through the shell's expansion of the Claude config directory, so no install-time rewriting of the files is needed.
- **Why:** A settings hook runs in every session of every project: there it answered `allow` to every main-thread call — piping a download into a shell, a recursive delete of a home folder, a write to a shell profile — in sessions that never ran PAF, and applied PAF's agent rules to agents that are not PAF's. A shell-form hook command runs via `sh -c`, which expands variables(21), and the default expansion is the same config directory the installer writes to; a relative path or `${CLAUDE_SKILL_DIR}` is not documented to work in a hook command(17)(21).
- **Source:** (21) (17), #122.
- **Accepted risk:**
  - **The skill's hook outlives the skill.** It stays registered for the rest of the session(21), so after a PAF skill finishes, that one session's main thread stays prompt-free under the hook's unconditional `allow`. A new session starts without it.
  - **Several copies per main-thread call.** Each skill's copy of a handler stays separate; only identical settings-file handlers are deduplicated(21). In a session that invoked several PAF skills, every copy runs on each matching main-thread call, in parallel. Each is the same script and returns the same decision.
  - **A hook script that cannot be reached blocks.** If the registered command cannot open the script (not installed, a partial install, or `CLAUDE_CONFIG_DIR` set differently from the installer's), `python3` exits 2 (verified: running it on a nonexistent file exits 2), and exit 2 from a `PreToolUse` hook is a blocking error. Every matched call of that skill or agent is then blocked, the main thread's included, rather than falling back to normal prompts. The failure is loud and is fixed by re-running the installer. A fail-open wrapper is not built: it would hide a broken install and add a second script to the policy.
  - **The managed-settings lock.** When managed settings list `hooks` in `strictPluginOnlyCustomization`, a personal skill keeps no frontmatter hooks and loses its `allowed-tools` pre-approval(21)(17), so PAF's skills run without their hook and grants and fall back to normal permission prompts.

**Where the hook runs (verified empirically)**

- **Decision:** The PAF agents register the hook themselves, alongside the PAF skills. So, in a session where no PAF skill was invoked, the hook never runs for the main thread or for agents that are not PAF's, and a **PAF agent is governed by the agent rules wherever it runs**, also in a session where no PAF skill was invoked.
- **Why:** The docs say a skill's hooks stay registered for the rest of the session once it is invoked, and a subagent's run only while that subagent runs(21), but not whether a skill's hook also fires inside the subagents spawned in that session. Tested, it does not, so an agent relying on the skill's registration would run unguarded.
- **Source:** (21) (22), #122. Verified empirically on Claude Code 2.1.323 with `claude -p`, a logging hook, and a scratch project:
  - A skill-frontmatter `PreToolUse` hook fired for the main thread's calls from the skill's own turn on, and did **not** fire for the calls of a subagent the session spawned (the subagent's `Bash` call ran and was not logged).
  - An agent-frontmatter hook fired for that agent's own calls, with `agent_type` set, also in a session where no skill was invoked, and not for the main thread's calls. (The agent was passed with `--agents`; hooks of user-level agents in `~/.claude/agents/`, where PAF installs, and of `--agents` definitions run without workspace trust, while a project agent's need it and a `-p` run does not grant it(22).)
  - The registered command expanded to `$HOME/.claude` with `CLAUDE_CONFIG_DIR` unset and reached the installed script; the unit tests run it through `sh -c` with the variable set and unset.
  - In a session where no skill was invoked, neither the main thread's calls nor a `general-purpose` subagent's reached the hook.
- **Accepted risk:** An agent from a higher-priority scope (managed, `--agents`, project) with the same name as a PAF agent replaces PAF's definition(22) and so runs without PAF's hook.

### Scoping an agent

**Default-deny allowlist, derived from the agent's category**

- **Decision:** An agent's tool scope is declared as a `tools` **allowlist** containing only what its job needs; every other tool — including all MCP tools — is denied by omission. The allowlist is derived from the agent's category (§1):
  - **Read / analysis / synthesis / review** → `Read` only; plus `WebSearch`, `WebFetch` only if the job needs external lookups; plus `Grep`, `Glob` when the job requires validating claims against the codebase, or checking a change against it (e.g. finding the nearest existing pattern), rather than reading paths it is already given. The hook path-contains an agent's reads (Project-path containment of reads, below).
  - **Exploration / planning** → also `Bash`, which the hook restricts to read-only commands (Read-only Bash, below).
  - **Builder** → also `Edit`, `Write`, `Bash`; the hook confines `Edit`/`Write` to the project root, and `Bash` carries no path restriction (Build/test Bash, below).
  - **Verification** → also `Bash` for running tests and the UI check command; no `Edit`/`Write`.

  Each agent's exact allowlist lives in its file (`agents/<name>.md`); the architecture keeps no per-agent table.
- **Why:** The allowlist is default-deny: only what is listed is available, so a tool added to Claude Code later is unavailable until an agent lists it. Deriving it from the category ties the scope to the shape of the work (§1, Categories drive scope and payload).
- **Source:** (4)

### Hook enforcement policy (layer 3)

**Policy here, command patterns in the hook**

- **Decision:** This document fixes the hook's *policy patterns*; the exact command patterns are an implementation detail of the hook (`hooks/PreToolUse-agent-guard.py`, explained in `hooks/README.md`). Which pattern applies to an agent follows from its scope (Scoping an agent). The hook allows each vetted call, denies the forbidden ones, and defers the rest.
- **Why:** The rules as implemented live only in the file that runs them and its human explanation (introduction).
- **Source:** #124.

**Explicit agent sets in the hook**

- **Decision:** The hook holds two short explicit name sets: `PAF_AGENTS`, every PAF agent, and `READ_ONLY_AGENTS`, the agents whose Bash is read-only. Adding any agent means one line in `PAF_AGENTS` plus the hook block in its frontmatter, and one line in `READ_ONLY_AGENTS` when it uses Bash for exploration only. Every other pattern needs no change when an agent is added.
- **Why:** The read-only-vs-build/test Bash distinction has **no** runtime-visible discriminator in `tools:` — `code-explorer`, `implementation-planner`, and `implementation-verifier` all declare identical `Read, Bash` — so the hook is the *sole* place that distinction can live. Adding a Bash-using agent is a rare event for PAF's stable, first-party set of agents, so a short explicit set is kept deliberately, rather than a mechanism deriving it from frontmatter.
- **Source:** PAF design choice; no external source.

**Read-only Bash**

- **Decision:** An agent granted Bash for exploration only may run only an explicit set of read-only commands — an **allowlist (default-deny)** — and every other Bash command is denied. The allowlist applies to **every segment** of a compound command, the body of a command substitution included. Output redirection to anywhere but the null device, and a command's **own write flags**, are denied; a command the hook cannot lex is denied. As implemented: `hooks/PreToolUse-agent-guard.py`, explained in `hooks/README.md`.
- **Why:** Default-deny is required because a denylist of mutating commands inevitably leaks. The allowlist alone is not sufficient, because a command's *first word* does not determine what it runs or writes (#41). Segment boundaries are recognized by a property of the token, not a list of known operators: the lexer returns a run of shell punctuation as one token, so an enumeration silently missed every operator it did not name — four bypasses of the first attempt at this fix — while under the property rule, syntax nobody anticipated still splits the segment and what follows must clear the allowlist on its own. A redirection or a write flag writes however read-only the command is, and what the guard cannot read, it cannot clear.
- **Source:** #41; PAF design choice.

**Project-path containment of writes**

- **Decision:** An agent with write access may `Edit`/`Write` inside the project root; the hook denies any write whose target resolves **outside** it. The root is the project directory Claude Code exports to hooks(7) (`hooks/README.md`).
- **Why:** Frontmatter cannot confine a write tool to a path (Why the hook is required and not redundant); the hook can.
- **Source:** (7)
- **Accepted risk:** This containment is keyed on `agent_type`, so it applies only to agents — not to the main thread, which the hook treats as unrestricted (No allow-list on the main thread). `implement-issue` deliberately runs its plan→build phase, including the file writes, in the **main thread** (§2), so those writes are **not** path-contained by the hook. The compensating controls are structural: the write phase is reached only through native read-only plan mode and the `ExitPlanMode` developer-approval gate (nothing is written until the developer approves the concrete plan), and the skill performs no commit/push (it hands off uncommitted work, `skills/paf-implement-issue/SKILL.md` step 12). Consistent with the trust model — cooperating Claude agents, not an external adversary — this is an accepted limit, not a closed hole.

**Project-path containment of reads**

- **Decision:** An agent's `Read`/`Grep`/`Glob` is allowed inside the project root, in the session's own `tool-results/` directory, and — `Read` only, never `Grep`/`Glob` — on a file under PAF's review input folder, `~/.claude/paf/review-input/`; no other path under `~/.claude/paf/` is opened up. Anything reaching outside all three gets **`ask`**, a forced human permission prompt, not `deny`. How the hook resolves and bounds a read's path is in `hooks/README.md`.
- **Why:** Claude Code saves a tool result too large to return inline into the session directory and has the model read it back from there, a subagent's into the main session's directory, outside the project root(12). The review input file is the one input every code reviewer of a run reads (§4, Input delivery), kept in user scope so the project stays untouched (§5); a hook `allow` skips the prompt(16), and `.claude` is protected against writes, not reads(15). `ask` is the deliberate choice over `deny` because the hook payload carries no list of the directories added with `--add-dir`/`permissions.additionalDirectories`: a hard deny would make them unreadable to agents, while with `ask` they still work, one prompt at a time. Auto mode's classifier can deny an `ask` but cannot approve it silently(7). Without the hook, an out-of-root read would already prompt in Manual mode(11) — the change is that the decision is now the hook's, explicit, and not one a classifier can make alone. The containment matters most for an agent holding read tools alongside `WebFetch` (currently only `issue-validator`) — the read-plus-outbound shape that would carry data off the machine if it were ever driven to.
- **Source:** (7) (11) (12) (15) (16), #62, #120.
- **Accepted risk:** (a) how a hook's `ask` behaves under `bypassPermissions` is undocumented; (b) the root falls back to the payload `cwd` when the exported project directory is unset (writes share this), so an agent that moved the working directory to `/` would widen it — the variable is documented as exported to hooks, so this is a fallback only; (c) secrets inside the root (`.env`) are readable without a prompt; (d) the tool-results directory is located from the payload's `transcript_path` and `session_id`, which is trustworthy only because both fields are set by the harness; (e) `Grep`'s `glob` parameter is not checked, which holds only if ripgrep's `--glob` cannot widen the search root; (f) the read-only *Bash* an exploration agent runs is checked for command names and redirections, not file-argument paths, so it can still read outside the root — the trust model (cooperating Claude sub-agents, not an external adversary) and the agent-level rule that file content is data, never instructions, are the compensating controls; (g) case-variant paths on a case-insensitive filesystem fail safe to `ask`; (h) the review input folder is located from `HOME`, and any file under it is readable by an agent without a prompt — it holds only what the review input helper writes there, which agents already see through the reviewers. These are accepted limits of a lightweight hook, not closed holes.

**No external I/O**

- **Decision:** No agent is ever granted `gh` or git-state mutation, and the hook denies every PAF agent `gh`, `glab`, the `paf-vcs` adapter, other external I/O, and git-state changes even where `Bash` is allowed; only the skill (main thread) performs them (§2, External I/O and VCS state are skill-owned). `WebSearch`/`WebFetch` documentation lookups are the exception: the hook allows them for **any** PAF agent whose call reaches it and does not special-case an agent name.
- **Why:** Reading public docs is not state-changing I/O. Which agents may reach the web is already enforced upstream by the `tools:` allowlist (layer 2), so in practice only web-authorized agents (currently only `issue-validator`) ever get here.
- **Source:** PAF design choice; #41, #44.
- **Accepted risk:**
  - **Web ingress.** `WebSearch`/`WebFetch` pull externally-controlled content into an agent's context — a prompt-injection ingress whose risk shape differs from the "cooperating sub-agents" trust model (the untrusted party is an external page, not another Claude agent); `issue-validator`'s findings, built from fetched content, are posted verbatim as an issue comment and can, on a `severity: error`, prompt a developer-approval gate in `implement-issue` (a decline halts the run). With no agent-name special-case, any future agent granted these tools in `tools:` is likewise auto-allowed with no hook-level review. The compensating controls are structural, not hook-enforced: `issue-validator` is the only agent holding these tools today, its findings reach the developer through the posted issue, which they review at the skill boundary (§2, The skill boundaries are the primary gates), and through `implement-issue`'s approve/decline blocker gate, and no skill performs an unreviewed commit/push on the strength of fetched content. This is an accepted limit of a lightweight hook, not a closed hole.
  - **String inspection, not runtime interception.** The deny matches the command text — also past git's global options, and after undoing backslash-escaping and quote concatenation while keeping a quoted multi-word argument whole (#41, #44) — so it catches direct and embedded invocations, including ones reached through a shell operator, a redirection, or a git global option. What it cannot catch is indirection whose binary name only exists after **expansion**: an agent writing a helper script inside the project root and running it through an interpreter, inline interpreter code that opens a network connection, a renamed wrapper, or an encoded command decoded and evaluated at run time. Closing that would need runtime interception rather than pre-execution string inspection. Given the trust model (cooperating Claude sub-agents, not an external adversary), it is an accepted limit of a lightweight hook, not a closed hole.

**No allow-list on the main thread**

- **Decision:** The hook allows every main-thread call unconditionally — its `Bash` whatever the command's shape (bare, compound, piped, or `cd`-prefixed), and its `WebSearch`/`WebFetch` without a prompt — rather than gating its `Bash` on a command-family allow-list (previously `MAIN_THREAD_COMMANDS`) and deferring its web lookups to the normal permission flow. The hook reaches the main thread only through a PAF skill's registration, so only once a PAF skill was invoked in the session (Where the hook runs).
- **Why:** An earlier form gated the main thread on the command's first word, which made any compound command miss the list and fall through to a prompt, interrupting runs mid-flight. The per-command allow-list and deny rules exist to constrain **agents** (§2), not the trusted orchestrator.
- **Source:** (7) (5), #22.
- **Accepted risk:** `WebFetch`/`WebSearch` pull externally-controlled content into the model's context — a prompt-injection ingress whose risk shape differs from the "cooperating sub-agents" trust model used elsewhere in this section, since the untrusted party here is an external page or search result, not another Claude agent. The compensating controls are structural, not hook-enforced: the main thread reaches these calls only inside skills whose own structure gates them — native plan mode plus the `ExitPlanMode` developer-approval gate in `implement-issue`, and in `check-out` the developer's own invocation after reviewing the implemented branch, followed by a chain of checks only one of which (the pre-merge gate's optional, single-attempt mechanical auto-fix — see §5, `check-out` mutation posture) may be fixed-and-continued — and no skill performs an unreviewed commit/push on the strength of fetched content. This is an accepted limit of a lightweight hook, not a closed hole.

**Autonomous triage**

- **Decision:** The developer does not pre-approve individual review fixes anywhere in the pipeline; the builder agent's own triage is the only judgement before a finding is written into the code (§1, Builder; `agents/full-stack-dev.md`).
- **Why:** The developer's manual review lands on already-reviewed-and-fixed code and is the curation and revert point (§2, The review tail, and why there are two fix-owners).
- **Source:** PAF design choice; no external source.
- **Accepted risk:** The "a skip must be loud and justified" rule is **self-reported** — nothing independently checks that the agent complied. The same holds for the rest of the builder's triage obligations (§1, Builder). Nothing verifies that the builder recognised a **factual / self-consistency defect** as belonging to the non-skippable class rather than grading it away as discretionary, or that a finding it skipped as contradicting the issue's decided scope really did contradict it. And nothing verifies that its **sweep** actually found every occurrence of a fact it changed — a missed occurrence is indistinguishable, from the outside, from there having been nothing to sweep. Nor does anything verify that its **behaviour changes beyond the plan** list names every such change — the list relies on the builder noticing it went beyond the plan. Compensating controls: the fixes land on **uncommitted** work; the hand-off flags any behaviour change beyond the plan on one warning line and names every skipped `error` finding on its own line; and the developer's manual review of the uncommitted diff is the curation and revert point. Applied fixes are deliberately **not** listed at the hand-off: the diff is the authoritative record of what was applied, and a long verbatim applied-vs-skipped report went unread, so it was no control; no commit or push happens without them running `check-out`. This is an accepted limit of a self-reported triage rule, not a closed hole.

**Unreviewed remediation**

- **Decision:** The review agents run exactly once per `implement-issue` invocation and do not re-review the code the builder agent writes while applying their findings (`skills/paf-implement-issue/SKILL.md`, steps 9–11).
- **Why:** The second look at the code is the developer's manual review, backed by `check-out`'s safety-net review whenever the branch's content changed after the hand-off (§5, `check-out` safety-net review and gate).
- **Source:** PAF design choice; no external source.
- **Accepted risk:** The code the builder agent writes while applying findings — including any file its **sweep** (§1, Builder) reaches that no plan or finding ever named — is the one slice of the final diff no review agent sees again — the review agents are never re-run inside an invocation, and `check-out`'s safety net runs only when the branch's content changed after the hand-off, and then applies only the functional lens. Its only automated check is `implementation-verifier` (the scoped tests, plus the UI check command for a UI change). Compensating control: the developer's manual review, plus the trust model of cooperating agents rather than an adversary. This is an accepted limit of the pipeline's review coverage, not a closed hole.

**Build/test Bash**

- **Decision:** For the builder and the verifier, Bash that is neither external I/O nor a git-state change is allowed, so tests, linters, and migrations — and the project's optional **UI check command** — run without prompts.
- **Why:** Running the project's commands is their job. The UI check command (a dev server, a browser launch, possibly a browser download, screenshots/traces) is a trusted, project-defined, developer-privileged command like the test command.
- **Source:** PAF design choice; no external source.
- **Accepted risk:** This allowance carries no output-redirection or write-path check the way `Edit`/`Write` does, so an agent's "do not modify source files" boundary (e.g. `implementation-verifier`'s) is enforced at the advisory system-prompt layer alone (layer 1), regardless of its model tier — lowering an agent's model does not change what the hook allows, only how reliably the agent follows its own advisory boundary. This is an accepted limit of the advisory layer, not a hook change tied to model selection. The UI check command runs under the same allowance, and the hook's external-I/O guard covers only network-call-style commands, not what the suite itself does — repository content (`CLAUDE.md`, the Playwright config) is the trust boundary.

**Matcher coverage**

- **Decision:** The hook is registered for every tool it decides on — `Bash`, the write tools, the read tools it path-contains, `WebSearch`/`WebFetch`, and `Task` — not just Bash and writes. The matcher itself is in `hooks/README.md`, Registration.
- **Why:** The hook then sees every call that would otherwise prompt, notably web lookups and agent spawns.
- **Source:** PAF design choice; no external source.

---

## 4. Agent output contract

### Delivery mechanism

**Final message as the return channel**

- **Decision:** Every agent returns its result as one machine-parseable YAML block in its final message, and the **skill (main thread)** extracts, parses, and validates it. Malformed or missing output fails loudly and escalates to the developer ([Section 5](#5-loop-cap-escalation-and-cost-reporting)). As implemented: the `## Output` section of every agent ([`agent-definition-format.md`](authoring/agent-definition-format.md), Output contract) and the parsing rules in `skills/paf-shared/output-contract.md`.
- **Why:** Claude Code has **no native typed return channel** for subagents — a subagent returns results as its final assistant message in plain text — and there is no native schema validation. The contract is machine-checkable only because the skill parses and validates it.
- **Source:** (2)

### Input delivery

**In the prompt, read from the project, or — for the code reviewers — the review input file**

- **Decision:** A skill passes every agent input as text in the invocation prompt, or names files inside the project root that the agent `Read`s itself. The code reviewers (`implement-issue`'s deep review, `check-out`'s safety net) instead get one shared review input file. Each skill step that invokes an agent states exactly what it passes.
- **Why:** A skill that leaves the input open lets the model improvise — and an improvised input breaks the run.
- **Source:** PAF design choice; no external source.

**Never through any other file outside the project**

- **Decision:** A skill never writes an agent input to a scratchpad, `/tmp`, or any other path outside the project root for the agent to read. The one exception is the **review input file**, user-scoped, written by the shared helper `skills/paf-shared/paf-review-input.py` through `Bash`, not through the `Write` tool. The helper failing stops the run. As implemented: the helper and the review steps of `skills/paf-implement-issue/SKILL.md` and `skills/paf-check-out/SKILL.md`.
- **Why:** The hook forces a permission prompt on every agent read outside the project root (§3), which stops an otherwise autonomous run. The review input file means the main thread never retypes the input and every reviewer of a run reads the same bytes. It is user-scoped because PAF leaves no trace in the project (§5) — no `.paf/` directory, no ignore or exclude entry — and the hook allows an agent `Read` of exactly that folder (§3). `Write` is avoided because its writes to the protected `.claude` path are never auto-approved.
- **Source:** (15); #120.

**Verbatim means verbatim**

- **Decision:** An input the skill names as verbatim — the issue body, its acceptance criteria, the removed lines of a change manifest, a findings list — reaches the agent exactly as it was fetched or printed: pasted, or, for the code reviewers, written by the review input helper straight from the commands' output. Never summarized, shortened, or omitted, whatever the prompt size.
- **Why:** A shortened input silently removes what the agent was meant to judge. Pasting into every reviewer prompt — what the review input file replaces — had the main thread retype the same text as output tokens once per reviewer, and measured runs showed reviewers handed an orchestrator-written summary instead of the verbatim text.
- **Source:** #120.

### Schema

**Uniform schema**

- **Decision:** One schema for every agent: every field is always present, and collections are `[]` when not applicable. The schema itself is in [`agent-definition-format.md`](authoring/agent-definition-format.md) (Output contract) and `skills/paf-shared/output-contract.md`.
- **Why:** It keeps parsing predictable and improves agent adherence — a fixed template is followed more reliably than conditional fields.
- **Source:** PAF design choice; no external source.

**No cost block**

- **Decision:** The agent contract carries no cost; cost is measured by the skill from the transcript (see [Section 5](#5-loop-cap-escalation-and-cost-reporting)).
- **Why:** An agent cannot reliably count its own tokens.
- **Source:** PAF design choice; no external source.

### Severity semantics

**Error blocks, warning passes forward**

- **Decision:** **`severity: error`** denotes a **blocker** — a finding that stops the flow and requires developer action. **`severity: warning`** denotes a **minor / non-blocking** finding that is passed forward or surfaced for the developer to decide on. How each skill branches on it is in its own `SKILL.md` (for `issue-validator`, see its escalation in §5).
- **Why:** The skill needs one field that separates what stops the flow from what is carried forward.
- **Source:** PAF design choice; no external source.

**Severity does not decide triage**

- **Decision:** Severity drives the **skill-level** branching only; it does **not** by itself decide whether the builder may skip a finding. A finding identifying a factual or self-consistency defect is applied whatever severity it carries — see the triage rule in §1, Builder.
- **Why:** Severity grades impact, while a factual or self-consistency defect is a correctness defect regardless of it.
- **Source:** PAF design choice; no external source.

### Field usage by agent category

**Payload follows the category**

- **Decision:** The schema is uniform, but which fields carry the meaningful payload follows the agent's category (§1). `summary` carries the agent's primary **textual deliverable** — the complete document for an agent whose product *is* text (synthesis). `artifacts` carries **files** only. The usage per category is in [`agent-definition-format.md`](authoring/agent-definition-format.md) (Output contract).
- **Why:** An agent with no write access produces no files, so its product can only be reported in `summary`.
- **Source:** PAF design choice; no external source.

**Review status reports completion**

- **Decision:** A review or validation agent sets `status: success` on completion regardless of what it found. The one exception is a **final gate** review — a spec-conformance check that the skill treats as a STOP point — which sets `status: failure` when the work does not meet the criteria, and states this in its own Output section.
- **Why:** Reporting findings is the job; the skill and the developer decide how to act on them. A final gate needs `failure` so the skill can halt.
- **Source:** PAF design choice; no external source.

---

## 5. Loop cap, escalation, and cost reporting

### `implement-issue` retry loops

`implement-issue` has **three** fix loops: the verify and review loops, with different owners for the reason given in §2 ("the review tail, and why there are two fix-owners"), and the acceptance loop that closes the run. All share the same cap and the same escalation.

**Verify-fix loop (main-thread owner).** Repairs the build itself.

- **Max retries:** 2 — after an initial failure, the **same main-thread context that built the code** (now in edit mode, post-`ExitPlanMode`) re-applies the fix (planning ran in plan mode; building and this fix run in the same main-thread context, §2), at most twice — never a cold builder agent.
- **Trigger:** `implementation-verifier` returns `status: failure` (test or UI check failures).
- **Used on retry:** the verifier's failure output (structured failure context, not free-form prose); the approved plan and the code already sit in the main thread's context.

**Review-fix loop (builder-agent owner).** Runs after the verify loop passes, over the deep review's findings.

- **The review runs exactly once per invocation.** The review agents run in parallel over the implemented change; they are **never** re-run inside the same `implement-issue` run — not in this loop and not anywhere else. The second look at the code is the developer's manual review of the implemented code, backed by `check-out`'s safety-net review (below) whenever the branch's content changed after the hand-off.
- **Triage is the builder's, not the developer's.** The builder agent receives **all** aggregated findings and the issue body verbatim (the reviewers read it from the review input file, §4), and decides which to apply, bounded by the triage rule in §1, Builder — a finding contradicting the issue's explicit decisions or out-of-scope items skipped whatever its severity, `error` by default, a factual / self-consistency defect whatever its severity, a `warning` that would change behaviour beyond the plan skipped, everything else at `warning` discretionary — and by the same section's sweep obligation. The developer does not pre-select: they curate the applied fixes from the uncommitted diff in their manual review, the curation and revert point, while the hand-off flags only what the diff cannot show at a glance — a behaviour change beyond the plan (one warning line) and each skipped `error` finding (one line each). This is why there is no `AskUserQuestion` gate here — pre-selecting fixes would put a decision in front of the developer that their own review answers better, with the code in hand.
- **Max retries:** 2 — `implementation-verifier` re-runs after the fixes are applied; on failure the builder agent fixes again from the verifier's failure output, at most twice.

**Acceptance loop (main-thread owner).** Runs last, before the hand-off, so an unmet acceptance criterion is caught by `implement-issue` and never first surfaces at `check-out`.

- **Precondition:** the issue has acceptance criteria. `implement-issue` stops in step 1, before validating or planning, on an issue with no `## Acceptance criteria` section or an empty one: there is nothing to check the work against, so the issue is not ready. `check-out` instead falls back to the issue body as the spec, silently, so a legacy issue still ships (below).
- **Trigger:** `quality-assurer` reports an unmet criterion. It receives the acceptance criteria verbatim and the changed paths, and reads the files in the project (§4, Input delivery).
- **Max retries:** 2 — the main-thread context that planned and built the change fixes the gap, `implementation-verifier` re-runs, then `quality-assurer` re-runs. A fix never adds a detail that is not must-have; when it needs a must-have item beyond the issue, the skill asks the developer (`AskUserQuestion` — the plan approval is already past): yes is fixed within the loop and its cap, no or no answer stops the run with no fingerprint. Something the issue requires that the code makes impossible stops it too.

**Shared to all loops:**

- **On retry exhaustion:** the skill stops and prints its hand-off with `Result: failure`, whose `Next` line names what failed, quotes the essential lines of the last `implementation-verifier` output, and gives a suggested next action. The developer reviews, adjusts the plan or issue, and re-invokes `implement-issue` manually.
- **No self-validation:** whoever applied a fix never validates it — `implementation-verifier` always runs as a separate agent after every fix.

### `check-out` safety-net review and gate

`check-out` is a **confirmation-and-ship gate**, not a review-and-fix stage: the deep review already ran in `implement-issue`, before the developer's manual review (§2). It runs a single `senior-engineer-reviewer` pass, then `quality-assurer` once — both skipped when nothing changed since `implement-issue`'s hand-off — then the pre-merge validation, then finalises git/VCS. The step order is fixed: pre-merge validation stays the last gate before the commit and the MR/PR (developer's decision, #121).

- **One caller-framed safety net.** The reviewer is invoked as a **high-level confirmation pass**, framed at the call site (the diff was already deep-reviewed; look for critical regressions, especially the developer's hand-edits since then). The framing lives in the caller, never in the agent definition — a permanent "be shallow" instruction would damage the same agent's deep use inside `implement-issue`'s deep review, and agents are caller-agnostic (§2). Its purpose is the one slice of code no agent has seen: the developer's hand-edits. Like the deep reviewers, it reads the issue body verbatim from the review input file (§4, Input delivery), which tells it that what the issue's Decisions and Constraints — with its binding Approach and Acceptance criteria — decide or place out of scope is not a finding. For an issue without the agent section (a legacy or hand-written one), whatever the issue body states is decided — the same rule `implement-issue` uses. The framing also asks for critical regressions only, as `error`, and no warnings: `check-out` has no fixer, so a warning could neither be acted on nor usefully printed. That reviewer-side rule is the only one that carries over: `check-out` has no triage, so its gate counts every parsed `error`, and a decided item wrongly flagged as `error` STOPs for the developer to decide. **Accepted gap:** only the functional lens is applied there; the complexity, security, test-coverage, and conformance reviews are not repeated.
- **Skipped, deterministically, when there are no hand-edits.** When the developer approves `implement-issue`'s output without editing it — a common case — the safety net has, by its own purpose, nothing to review, and `quality-assurer` would re-check the exact content `implement-issue`'s own acceptance check already passed: the fingerprint is recorded only on that path, so it is the proof that `implement-issue` built this code and its acceptance check passed. An exact match therefore skips **both** agents (#121) — the repeated acceptance check cost €0.15–0.32 per `check-out` run (measured from session transcripts, 2026-11-12), and a second pass over identical input risks a false block because same-definition agents are non-deterministic (the reason `implement-issue` step 1 already skips re-validating a PAF-authored issue). Code built any other way has no record, gets `VERDICT=review`, and both agents run. So `implement-issue` pins a **content fingerprint** at its hand-off and `check-out` recomputes it before step 2 (shared helper `paf-shared/paf-fingerprint.py`). The fingerprint is one merged path → content-hash map over every path that differs from a **pinned base commit sha** — tracked changes (`git diff --name-only --no-renames <sha>`) and untracked files (`git ls-files --others --exclude-standard`), each hashed from the working tree (a deleted-path sentinel, a symlink's target, a file's bytes plus its executable bit). It is **base-pinned** (the sha is stored in the record, so a later move of the base ref cannot shift it), **commit-invariant** (committing changes neither the working tree nor the pinned sha, and the single map has no tracked/untracked buckets a commit could move a path between), and **content-based** (nothing hashes `git diff` text, so diff config and external diff/textconv drivers cannot shift it). An exact match skips the review and the acceptance check deterministically, never on judgement — a skip is the standard run, so the final output says nothing about it; a commit that changes no content still matches, since committing is not editing. A mismatch, a missing or unreadable record, or any failure to recompute runs both exactly as before: absence of evidence fails safe. The record lives in the user's `~/.claude/paf/` namespace, never in the project, like the cost ledger (below), keyed by repository root and issue; it is overwritten by a re-run of `implement-issue` and removed when `check-out` totals and cleans up the ledger.
- **Accepted limit — the fingerprint covers branch content, not the issue.** If the issue's acceptance criteria are edited after the hand-off while the code is unchanged, the fingerprint still matches and `check-out` skips both agents, so the edited criteria are not re-checked. The safety-net skip already ignored issue edits the same way. Changed criteria mean re-running `implement-issue`. This is an accepted limit (developer's choice, #121), not a closed hole.
- **Accepted limits of the safety net when it runs.** The hand-edits cannot be isolated from the implementation already reviewed in `implement-issue` — the skill hands the reviewer the whole branch change against the base (a change manifest of created and changed files, §4 Input delivery), and when the work is left uncommitted there is no git boundary that could carve the hand-edits out of it. So the reviewer may re-see, and re-flag, code the deep review already reviewed and fixed — the very rework cycle this design exists to remove. The invocation framing instructs the reviewer not to re-litigate the already-reviewed implementation, but this is not a mechanism that isolates the hand-edits; the fingerprint only decides *whether* the review runs, not *what* it sees. And a hand-edit to a path marked `--assume-unchanged` or `--skip-worktree` is invisible to `git diff` and so to the fingerprint (as is a line-ending-only edit that a clean filter or `core.autocrlf` normalises away), which can then skip a review it should have run. Both are accepted limits of a caller-framed, single-diff safety net, not closed holes.
- **The gate is computed by the skill, from severity.** The skill branches on the parsed `issues[].severity`, **not** on the agent's `status` — a review agent reports `success` on completion regardless of findings (§4), and it is not a final-gate agent. `error` → STOP; a `warning` returned despite the framing is dropped, never printed.
- **No fix loop, no retry — failures STOP and escalate.** Unlike `implement-issue`, `check-out` never fixes-and-continues on anything requiring judgement, and never retries a check, with two bounded exceptions: the mechanical auto-fix defined in the mutation posture below and the isolated re-run of failed tests (flaky tests, below), each capped at a single attempt and neither a fix loop. Any blocker halts the run and escalates to the developer, who resolves it and re-runs `check-out`:
  - the safety-net review returns an `error` finding → STOP
  - `quality-assurer` finds unmet criteria (when it runs) → STOP
  - pre-merge validation fails — after the optional auto-fix and its single re-validation, where the project defines one, and after the isolated re-run, when only failed tests remain → STOP
  - malformed or missing agent output → STOP
  - opening the MR/PR fails → STOP

  This is deliberate: `check-out` is the final human-controlled finalization stage, so the developer — not the factory — decides how to resolve a failure. Every STOP prints the same short failure output: `Result: failure`, `Blocker: <one line>`, `Next: <what the developer does>`, then the failing findings verbatim, one per line, with a blank line between fields.
- **Minimal final output.** On success `check-out` prints `Result: success`, the MR/PR link, and one line per deviation from the standard run, only when it applies: the safety-net review ran, and the pre-merge auto-fix ran (with what it changed) — then this run's cost block, as every skill prints it — with a blank line between fields and no recap of the steps. A missing or empty acceptance-criteria section, for which `quality-assurer` gets the issue body as the spec, is not a deviation and is not printed. Invoking the skill is the developer's go-ahead, so it asks no in-skill confirmation.
- **`check-out` mutation posture.** `check-out` may run a **tool-driven, behaviour-preserving auto-fix** as part of the pre-merge gate: on a pre-merge failure, if the project defines an auto-fix command in its project instructions, the skill runs **that** command exactly as defined and re-runs the pre-merge validation **once**. It may **never** apply a judgement-requiring or semantic fix — that remains a STOP-and-escalate case resolved by the developer. Three properties keep this from re-opening the fix loop the point above closes: the fix is performed by the **project's own tooling**, never authored by the model (so it cannot make a semantic change under the guise of a format fix); the re-validation **is** the fixability split, deterministically — whatever the tool could fix is gone, whatever remains needs judgement by definition, so nothing has to *judge* which failures were mechanical; and the attempt is capped at **one**, so a failure that survives it escalates exactly as it does today. The command is entirely **project-defined and optional** — the architecture names no tool or flag (consistent with the project instructions being a content checklist, not a format), and a project that defines none keeps the STOP-on-fail behaviour, subject only to the isolated re-run of failed tests (flaky tests, below).

  **Accepted residual risk:** this mutation is a new shape of exposure in `check-out`, not one already covered elsewhere in this document. It runs downstream of every review layer `check-out` has — the safety-net review (step 2, when it runs), `quality-assurer` (step 3, when it runs), and the developer's own manual review of the implemented code, all of which precede it — and its diff is committed, pushed, and put in front of the MR/PR with no review agent re-run and no additional developer-approval gate; the only signal surfaced is the `Pre-merge auto-fix ran:` line of the final output. The claim above that a tool-driven fix "cannot make a semantic change under the guise of a format fix" is an assumption about the configured command's behaviour, not something PAF verifies at runtime — an aggressive auto-fix mode could still ship an unreviewed semantic change. The single-attempt cap and the "never a tool/flag you chose yourself" constraint are themselves enforced only at the advisory prompt layer, consistent with "No allow-list on the main thread" above. The command is also `check-out`'s first instructions-sourced value that **writes** files which are then committed and pushed, run with the developer's full privileges on the strength of only the developer's invocation of `check-out` after their review of the implemented code — a go-ahead given before, and unable to anticipate, a mid-run pre-merge failure; `check-out` asks no in-skill confirmation. The compensating control is structural, not an added gate: the developer's own review of the MR/PR at the skill boundary (§2, The skill boundaries are the primary gates) is still the last human eyes on this diff before merge, exactly as for every other change `check-out` ships. This is an accepted limit of a mechanical, tool-driven auto-fix, not a closed hole.
- **Flaky tests — isolated re-run** (#121, developer's decision 2026-11-12). A flaky test should not stop `check-out` when it passes on its own. When the pre-merge failure left after the auto-fix handling above (which does not change) consists only of failed tests that the output names, `check-out` re-runs each of them **on its own, once**, with the project's **test** command exactly as the project instructions define it, scoped to that single test the way `implementation-verifier` scopes it to an area — no new project-instruction value and no other tool. Every one passing → the run continues as on a passing pre-merge validation, without re-running the full command. Any one failing again → STOP, naming each such test and saying it fails even in an isolated run. Any other failure (e.g. lint), output that names no failed test, or a project with no test command → STOP as before, with no isolated re-run. It is capped at one run per test, never a loop, and changes no code, so it is neither a fix loop nor a mutation; `check-out` still never hand-edits code to make the gate pass. When it carried the gate, the MR/PR description's Validation line says so rather than claiming the full command passed.

### Verification scope — two tiers

The factory has two distinct verification points with deliberately different scopes:

- **`implementation-verifier` (scoped, in-loop).** Runs a **targeted subset** of the test suite — the tests covering the changed area/module (e.g. the affected Django app, or the affected CDK service/resource), not merely the changed test files and not the whole suite. When the change touches UI (a template, a stylesheet, or browser-side JavaScript/TypeScript), it then runs the project's optional **UI check command** verbatim — whether or not the tests passed, so one fix pass sees every failure — and a UI check failure counts as a verification failure under the same cap (#83). Server-side tests cannot observe rendering, so for a UI change they alone would claim a verification never performed. The command is **project-defined**, like the test command, rather than PAF rendering pages itself: browser tools are not reliably available in every session, which pages and element states to check is project knowledge, and rendering in PAF would break project-agnostic skills and the zero-dependency rule. It is **never skipped silently**: a UI-touching change with no UI check command defined gets `UI not verified: no UI check command defined` in `implement-issue`'s hand-off and in `check-out`'s MR/PR description. Never the project's lint command and never its full pre-merge command, both of which belong to the tier below. It runs inside **both** of `implement-issue`'s fix loops (up to 3× each), so a scoped run keeps them fast and cheap — and pulling the fuller command into this tier would inflate exactly the cost and latency the split exists to contain.
- **Pre-merge validation (full, at the gate).** Runs the project's **full** test/lint suite once at `check-out` — the final safety net that catches any cross-module regression a scoped run could not see, and the tier the lint command belongs to. It is the only verification tier `check-out` runs: it authors no fixes of its own, and its sole mutation is the optional mechanical auto-fix defined in the mutation posture above, which this same full command re-validates. The one scoped run there is the isolated re-run of a failed test (flaky tests, above), with the project's test command scoped to that single test — a flakiness check, not a verification tier.

This two-tier split is the reason both points exist: fast scoped feedback during implementation, full validation before the PR.

**Implementation-defined:** how the affected area/module is determined (e.g. derived from `full-stack-dev`'s reported `artifacts` plus project conventions) and the exact scoped and full commands are **project-specific and sourced from the project instructions** — not fixed by this architecture.

### `issue-validator` escalation

`issue-validator` validates an approach against authoritative docs **and** the repository. It checks an issue's **factual claims** and its **completeness**, never an implementation plan. It always runs in `create-issue`; in `implement-issue` it runs **only for issues PAF did not already validate** — a shift-left pass plus a source-aware safety net. The validator never calls `gh` itself — the caller acts on its findings.

**In `create-issue` (authoring time, before the issue exists).** The drafted issue is validated *before* it is posted, so a defect is caught at the source rather than surfacing later. This closes the gap where `issue-writer` (read-only, no web access) faithfully transcribes an unverified approach.

- **What is checked** — both externally-verifiable claims (a CLI flag, an API signature, library behaviour, and the cited spec's caveats and scope limits, not just its headline rule) **and** repo-grounded ones (a named path that does not exist, a description of current behaviour that contradicts the code, an approach infeasible against the existing implementation). **Findings are bounded to factual/feasibility and completeness defects** — the approach is wrong or infeasible — never to implementation guidance (flag choices, edge-case handling, fixture design, output formatting): that class is decided later, against the live repository, not at validation time. This boundary is owned by `agents/issue-validator.md` itself (caller-agnostic, §2), so it applies wherever the agent runs, including its `implement-issue` invocation below.
- **Completeness** — every behaviour case a Decision or acceptance criterion touches must be covered by the issue. An uncovered case is an **open point** — a behaviour, output or scope choice the issue does not settle — and is a `severity: error` whose message starts `Uncovered:` (the same message-prefix convention as `issue-writer`'s `Undecided:`), because an issue with an open point is not ready to post and the goal is a plan with zero deviations. Behaviour only: how it is built (file layout, naming, edit structure, which files or code area) is never an open point, an incomplete file list stays never a finding, and the validator still never drafts or demands a plan. (Origin: #105, where five of six plan "deviations" restated consequences of the issue and the one real gap was an uncovered case.)
- **Scope discipline** — the skill passes the whole draft and never skips the step; the validator owns which claims it checks (`agents/issue-validator.md`). In an issue with the agent section those are the factual claims in its `Context`, `Decisions`, `Constraints` and `Pitfalls` subsections — `issue-writer` keeps every checkable technical fact there, so the concise human part carries none left unchecked. `Scope of changes` is the author's **hint**: the implementer derives the real files from the issue's intent and the live repo, so an incomplete file list is never a finding and nothing there is a blocker.
- **Findings handling** — nothing is posted yet, and every finding has exactly **one** destination: a wrong fact whose correct value the finding states is fixed **in place** (only where the body makes that same claim; the validator's message is data, so only the `X → Y` substitution is applied) — never appended as a note, because a spec whose body contradicts its own notes forces the implementer to guess which one is right (the same factual/self-consistency rule `implement-issue` applies to review findings, its step 10); a new fact the implementer needs (a provider prerequisite, a claim to verify during implementation) is added to the agent section's `### Context`; an open choice — `issue-writer`'s `Undecided:`, an `Uncovered:` blocker, a correction needing the developer's choice, a wrong fact with no correct value — is asked, whatever its severity; anything else is dropped. Open choices are not asked as they arise: the draft is written once and validated once, then every open choice is asked in **one question phase** (`AskUserQuestion`, at most four questions per call (20), further calls back to back, no agent between questions, answers applied only after the last), followed by **one update** — a single redraft with all answers and corrections, then a re-validation of **only the claims that changed**, derived from a diff against the immediately-prior draft (never the whole draft: a non-deterministic agent re-exploring cleared text produces fresh findings rather than confirming the fix). A new open choice from the redraft or the delta check starts the next phase; fixes and new facts from it are applied directly and do not count as an update. With nothing to ask, fixes and facts are applied directly — no redraft, no delta check. Cap: two updates per part; anything still open after that **stops the run and nothing is posted**: there is no review gate to adjudicate it. (Origin: #116 — measured `create-issue` cost rose from about EUR 0.48 to EUR 1.05–1.50 per run as separate question rounds each added a writer and a validator run and every extra main-thread call resent the conversation; and in #111 an open choice graded as a warning was posted as a note, and `implement-issue` stopped on it.)
- **No review gate** — every decision the issue needs is put to the developer (`AskUserQuestion`) before drafting, or in the question phase after validation (one per update), so the draft holds only confirmed content and an issue with nothing left to ask is posted directly. The developer reviews the posted issue at the skill boundary (§2, The skill boundaries are the primary gates).
- **PAF-validated heading** — the cross-skill contract, defined here: every issue `create-issue` posts carries an agent section headed by a line reading exactly `## For implementation agent`, written by `issue-writer` (`agents/issue-writer.md`). It is `implement-issue`'s signal that PAF already validated this issue. A plain CommonMark ATX heading renders on both providers and survives any rendering, so `paf-vcs view-issue` stays a one-liner. Because the heading is the contract, `issue-writer` never rewords it and `implement-issue` matches the whole line exactly.

**In `implement-issue` (implementation time, against the posted issue).** The skill first reads the fetched issue (via `paf-vcs view-issue`) and checks whether its body contains a line reading exactly `## For implementation agent` (verified: `gh issue view`'s non-interactive output prints the raw issue body; the GitLab path — whether `glab issue view` prints raw Markdown when not attached to a terminal — inherits the pending #14 validation caveat):

- **Heading present** → the issue was already validated in `create-issue`; the skill **skips** the validator entirely and proceeds to plan mode, which starts from the agent section's Context (and Scope of changes) as a hint of the code area; where the code differs, the plan works from the real code, unreported. The plan builds only what the issue states; a must-have item the issue missed is listed in its own plan part and agreed by approving the plan, and only something the code makes impossible stops the run with `Result: failure`. This removes the redundant re-validation that — because same-definition LLM agents are non-deterministic — could otherwise "block" an issue `create-issue` had already validated (the recurring validated-then-disabled failure).
- **Heading absent** (a hand-written issue, or one created outside PAF — the only validation it ever gets) → the skill runs the validator and posts **only** the actual findings as an issue comment — one line each, none when there are none (never the verdict or a recap of confirmed claims). A completeness blocker (`Uncovered:`) always stops the run, with no approve-and-fold option: the developer fixes the issue (or creates it with `create-issue`) and re-runs. A factual `severity: error` does not stop unconditionally: the skill informs the developer, quoting the finding(s), and asks via `AskUserQuestion` whether to fold the blocker into the plan and continue (**approve**) or stop (**decline**; a missing answer counts as decline — never auto-approve). `warning` findings are posted (terse) and carried into the implementation plan.

**Accepted residual risk (false skip).** The heading is content in the issue body, which admits two symmetric false-skip cases. (1) *Heading survives manual edits* — an issue PAF authored and a developer then edited **after** creation still carries it and is skipped at implementation time. (2) *Coincidental content* — a hand-written, non-PAF issue that happens to use a line reading exactly `## For implementation agent` would be mistaken for a validated one and skip the validator that is otherwise its only check; matching the whole line exactly makes this unlikely but not impossible. Both share one compensating control: the plan-review gate (`ExitPlanMode`) is where the concrete plan is scrutinised against the live repo before any code is written, so an infeasible approach surfaces there regardless of how the issue was validated. Re-validating these edge cases is traded for never re-validating a PAF issue (and never hitting the non-deterministic false blocker); this is an accepted limit, not a closed hole.

### Malformed-contract escalation

Contract parsing must be defensive — the whole pipeline depends on it. The skill must:

1. Extract the **last** fenced ` ```yaml ` block from the agent's final message. A block with no closing fence runs to the end of the message, which is what CommonMark specifies for an unclosed fence,(19) so it is extracted and validated, not treated as missing.
2. Parse it, and **validate** that all required keys are present and that enum fields hold allowed values (`status` ∈ {success, failure, needs_retry}; `severity` ∈ {error, warning}; `action` ∈ {created, modified, deleted}).
3. On any missing block, parse error, missing key, or invalid enum value → **STOP and escalate to the developer, including the agent's raw output** in the report so the failure is diagnosable.
4. If the block had no closing fence and passed validation, continue, but tell the developer the report may be truncated and repeat that in the run's final report.

The skill never proceeds on a partial or guessed parse. An unclosed fence is not a guess at the block's boundary, since the spec defines it, and stopping on one threw away complete reports. **Accepted residual risk:** the closing fence is the only sign a report was not cut off. `issues` is the last key, so a cut before it fails on a missing key and a cut inside a quoted value fails to parse, but a cut between two `issues` entries validates with findings lost. Rule 4 surfaces that case to the developer rather than closing it.

### Cost reporting

Every skill run ends with a single report of the **token cost of that invocation** — except the skills listed here, which report no cost:

- `init` — a setup and health check run before any feature exists, so there is no issue to key a ledger entry on (below).

A new skill reports cost by default; exempting one means adding it to this list with its reason.

- Cost is **not** self-reported by agents. The skill computes it from the session transcript at `transcript_path`, which records per-message `usage` (`input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`) and `model`, enabling correct per-model pricing.(7) (9)
- **Per-invocation slice, not the whole session.** A skill marks its start at its first step and prices only the transcript slice from that mark onward (main-thread and subagent messages alike). This is required because multiple skills can run in **one** CLI session (see the aggregation note below): pricing the whole transcript would re-price an earlier skill's tokens and inflate the feature total, and a `create-issue` run inside a large multi-day session would price the entire session. Each run is therefore costed as a disjoint slice.
- **Stopped runs are recovered, not lost.** A run that STOPs never reaches its cost step, so its start marker stays open. The marker therefore carries its own attribution — session, skill, project, and feature key (the issue number, or the branch when there is none; below) — and every mark and record also appends its time to a per-session boundary log. An open marker is closed into its own `<skill>-stopped` ledger row (e.g. `check-out-stopped`) by the next run of the same skill in the same session, and by `check-out`'s aggregation for every open marker of that project and feature, in any session. Its slice runs from its start to the first later boundary in its session — the next PAF skill's mark or record — so it never overlaps a run recorded after it; with no later boundary, it ends at the close, which is logged as a boundary in turn. Recovery lives in the cost helper, not in the skills' STOP paths: STOPs are many and often unplanned, so a failure-path instruction could not be relied on. **Known limits:** a run marked before its feature has any key cannot be attributed if it stops — a `create-issue` run that stops before posting (no issue number yet), or an `implement-issue` run without an issue number (it marks on the base branch, before the feature branch exists); and a run still going in another session when `check-out` aggregates is recorded as stopped up to that moment, its later record pricing only what follows.
- **Pricing is per model, not per snapshot.** A model id is canonicalised before it is priced: a trailing snapshot date (`-YYYYMMDD`) is stripped, so a dated snapshot and its alias are the same model at the same rate.(10) The price table's keys are therefore **dateless** — a dated key could never match — and a dated snapshot of a priced model is an exact match, not a fallback.
- **Rates are per model, priced per request.** Every model carries its own five rates, as the pricing page lists them: cache rates are not a fixed multiple of input across models — cache reads are 0.1x input on most models, 0.05x on Opus 5.5 and Sonnet 5.5, and 0.025x on Fable 5.2, Mythos 5.2, Fable 5.1 and Mythos 5.1.(13) A model priced by prompt length (Haiku 5.5: up to / over 100,000 prompt tokens) is priced per transcript message at the tier that message's prompt length selects, because Anthropic prices each request on its own and counts all of its input tokens — cache reads and cache writes included — toward that length.(13) Every term of that sum is in each message's `usage`, so the tier is exact, not approximated.
- **Unpriced models are never dropped.** If the session used a model still absent from the price table after that canonicalisation, its tokens are priced at the latest known rate of the same family (opus/sonnet/haiku) and the report flags that the price table must be updated — an undercount is never silently produced.
- **Currency.** Anthropic bills in USD; PAF reports cost in **EUR**, converted with a factory-maintained USD→EUR rate kept alongside the per-model price table. Both are updated together and carry their source and date.
- **Tokens as well as money.** The report shows the token breakdown — in, out, cached, total — beside the EUR cost, in both the CLI output and the PR. Money alone hides whether a run was expensive because of volume or because of model choice; the counts are already collected for pricing, so surfacing them costs nothing.
- The internal mechanism for attributing usage to individual agents is an implementation detail; the architecture requires only that the final total is reported.

#### Cross-skill cost aggregation

A feature spans the three main-skill runs — `create-issue`, `implement-issue`, `check-out`. These are usually separate Claude Code sessions, but they need not be: `implement-issue` and `check-out` in particular are often run back-to-back in a **single** CLI session (which is exactly why each run prices only its own invocation slice, above). Claude Code has no native cross-session cost aggregation, so PAF maintains its own **per-feature cost ledger**:

- **Keyed by issue number, or by branch when there is none.** Every skill run appends its own per-invocation cost to the ledger entry for the feature. A feature with an issue is keyed by its number: `create-issue` knows it after posting (a split run that posts several issues shares its cost and token counts equally across their ledgers, the remainder to the first, since no part of the run can be attributed to one issue); `implement-issue` is given it; `check-out` derives it from the branch name (`feature/<issue-number>-<...>`). Not every feature has an issue, so a feature without one is keyed by its branch name instead, and PAF never stops or fails over a missing or malformed issue number — it falls back to the branch, and with neither a run's cost is still reported, just not added to a ledger. The issue number wins whenever both are known, so an issue-keyed feature keeps one ledger across all three skills.
- **User-scoped, never in the project.** The ledger lives under the user's `~/.claude/` namespace, not in the target repository — no `.paf/` directory, no gitignore entry. This preserves PAF's project-agnostic principle: installing and running PAF leaves no trace in the project. The hand-off fingerprints (above) and the reviewers' review input file (§4, Input delivery) share this user scope.
- **Totalled at check-out.** `check-out` records its own run, recovers any stopped run of the feature (above), then sums every entry for the feature and writes the **total cost — with a per-skill breakdown — into the PR description**, then removes the ledger. This gives the PR reviewer, who never sees the CLI session, the whole feature's cost.
- **Graceful degradation.** If the branch → issue-number mapping is unavailable, `check-out` totals the feature by its branch rather than failing.

The exact ledger location, record format, and pricing table are implementation details of the shared cost helper; the architecture fixes only that per-feature cost is aggregated across the three main skills, stored in user scope, reported in EUR with a token breakdown, and surfaced in the PR.

---

## 6. Project instructions as the single source of project context

**Single source of project context**

- **Decision:** The project's **instructions file** — `CLAUDE.md` or `AGENTS.md`, whichever Claude Code loads for the project — is the single source of project-specific context; this document calls it "the project instructions". PAF is tool-agnostic here: a project that keeps its context in an `AGENTS.md` shared with other coding agents needs no `CLAUDE.md`, and nothing in a skill or agent may assume one filename.
- **Why:** The file is **loaded automatically into every agent** (see "Auto-loading is native and not optional"), so there is no manual injection. Claude Code reads `AGENTS.md` as the project instructions when no `CLAUDE.md`, `.claude/CLAUDE.md`, or `CLAUDE.local.md` exists in the working directory or above it; when one does, by default only the `CLAUDE.md` files load, unless the `CLAUDE.md` imports `@AGENTS.md` or the **Project instructions** setting is `claude-md-and-agents-md`.
- **Source:** (6) (8)
- **Accepted risk:** Reading `AGENTS.md` directly needs Claude Code v2.1.277 or later; earlier versions, and sessions that disabled the built-in plugin, read `CLAUDE.md` only.

**Auto-loading is native and not optional**

- **Decision:** Skills never manually inject project-instruction sections into agents.
- **Why:** Every custom subagent loads the same instruction hierarchy the main conversation loads (user `~/.claude/CLAUDE.md`, project `CLAUDE.md`/`.claude/CLAUDE.md`, project rules, `CLAUDE.local.md`, managed policy, and any `AGENTS.md` loaded as project instructions). Only the built-in `Explore` and `Plan` agents skip it, and a custom agent whose frontmatter sets `omitClaudeMd: true`; no PAF agent sets it.
- **Source:** (6) (8)

**It depends on launch location, not agent config**

- **Decision:** PAF keeps project context in the **root** instructions file and does not rely on subdirectory instruction files.
- **Why:** The hierarchy is resolved by walking up from the working directory, so the project-root instructions file reaches every agent as long as Claude Code is launched from within the project (the normal case); subdirectory instruction files load on demand, not at launch.
- **Source:** (8)

**No duplication**

- **Decision:** A value that exists in the project instructions is never repeated in an agent prompt or skill file. The project instructions hold the project-specific context; agent prompts hold only factory-level role, tool scope, and output-contract instructions.
- **Why:** The project instructions already reach every agent natively (see "Auto-loading is native and not optional"); a repeat would be a second statement that can drift.
- **Source:** PAF design choice; no external source.

**Verification**

- **Decision:** The `InstructionsLoaded` hook is the way to check which instruction files reached each agent, rather than assuming it.
- **Why:** It logs exactly which instruction files reached each agent, so a missing file is seen, not inferred.
- **Source:** (7) (8)
- **Accepted risk:** It does **not** fire for an `AGENTS.md` read directly through the Project instructions setting — only for one a `CLAUDE.md` imports or symlinks to — so it cannot confirm an `AGENTS.md`-only project.

**Feature-branch naming is PAF's, not the project's**

- **Decision:** Every feature branch is `feature/<issue-number>-<short-description>`, fixed by the factory and not part of the project instructions. The merge strategy is not project context either: PAF opens the MR/PR but never merges it. As implemented: `skills/paf-implement-issue/SKILL.md` creates the branch and `skills/paf-check-out/SKILL.md` reads the issue number back out of it.
- **Why:** `check-out` reads the issue number back out of the branch to find the issue and the cost ledger, so the pattern must be the factory's; merging is the developer's.
- **Source:** PAF design choice; no external source.

**Strict sourcing — no cross-project bleed**

- **Decision:** Project-specific values come **only** from *this* project's instructions and repository. Skills never substitute a value — especially a filename or command — from the operator's memory, another project, or a prior session. If a value a step needs is not defined here, the skill **STOPs and asks the developer** rather than inventing or borrowing one. Each skill states this guardrail inline in its own `Input` section (a deliberate runtime copy), and its verification / pre-merge steps STOP when no command is defined.
- **Why:** Auto-recalled memories are unrelated background and may name files that do not exist in the current repo.
- **Source:** PAF design choice; no external source.

---

## Sources

Decisions are grounded in the official Claude Code documentation or an established standard or practice. Inline citations above use these numbers:

1. Subagents — Choose a model. https://code.claude.com/docs/en/sub-agents#choose-a-model
2. Subagents — Chain subagents / What loads at startup / Available tools (`AskUserQuestion`, `EnterPlanMode`, and `ExitPlanMode` depend on the main conversation's UI/session state and are unavailable to subagents even when listed in `tools` — `ExitPlanMode` unless the subagent's `permissionMode` is `plan`) / Spawn nested subagents (a subagent may spawn subagents up to depth 5, as of v2.1.172). https://code.claude.com/docs/en/sub-agents#chain-subagents
3. Subagents — Invoke subagents explicitly. https://code.claude.com/docs/en/sub-agents#invoke-subagents-explicitly
4. Subagents — Control subagent capabilities. https://code.claude.com/docs/en/sub-agents#control-subagent-capabilities
5. Subagents — Supported frontmatter fields (`name` is received by hooks as `agent_type`). https://code.claude.com/docs/en/sub-agents#supported-frontmatter-fields
6. Subagents — What loads at startup. https://code.claude.com/docs/en/sub-agents#what-loads-at-startup
7. Hooks — `PreToolUse` input schema and `agent_type`, common input fields (`cwd`, `session_id`, `transcript_path`), `permissionDecision` values (`ask` forces a prompt even in auto mode), exit codes, environment variables (`CLAUDE_PROJECT_DIR`), `InstructionsLoaded`. https://code.claude.com/docs/en/hooks
8. Memory — How CLAUDE.md files load / AGENTS.md (when it is read, precedence, version floor, `InstructionsLoaded` difference). https://code.claude.com/docs/en/memory
9. Manage costs effectively. https://code.claude.com/docs/en/costs
10. Model ids and versions — the id grammar `claude-{name}-{major}[-{minor}]` (4.6 and later) and `claude-{name}-{major}-{minor}-{YYYYMMDD}` (before it), which is what makes a trailing 8-digit segment a snapshot date rather than a version. https://platform.claude.com/docs/en/about-claude/models/model-ids-and-versions
11. Permissions — Permission system (read-only tools need no approval within the working directory and additional directories) / Working directories. https://code.claude.com/docs/en/permissions#working-directories
12. Tools reference — Read, Grep, and Glob behavior (they prompt outside the working directories), and large tool results saved to the session directory for Claude to read back. https://code.claude.com/docs/en/tools-reference
13. Pricing — model pricing table, prompt-caching multipliers, and long context (prompt-length) pricing. https://platform.claude.com/docs/en/about-claude/pricing
14. Prompting best practices — Optimize parallel tool calling. https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#optimize-parallel-tool-calling
15. Permission modes — Protected paths (`.claude` among them; writes never auto-approved outside `bypassPermissions`) and critical paths. https://code.claude.com/docs/en/permission-modes#protected-paths
16. Permissions — Redirections (`>`/`>>`/`<` targets are checked like direct writes/reads against the working directories) and Extend permissions with hooks (a `PreToolUse` `allow` skips the prompt; deny and ask rules still apply). https://code.claude.com/docs/en/permissions#redirections
17. Skills — available string substitutions (`${CLAUDE_SESSION_ID}`, `${CLAUDE_SKILL_DIR}`, …; substituted in skill content and `allowed-tools` Bash rules; no scratchpad path), the frontmatter `hooks` field, and managed settings (under `strictPluginOnlyCustomization` with `hooks`, a personal skill declaring `hooks` loses its `allowed-tools` pre-approval). https://code.claude.com/docs/en/skills
18. Python standard library — `tempfile.mkdtemp` (secure, creator-only temporary directory on every platform). https://docs.python.org/3/library/tempfile.html#tempfile.mkdtemp
19. CommonMark Spec 0.31.2 — Fenced code blocks (an unclosed fence runs to the end of the containing block or document). https://spec.commonmark.org/0.31.2/#fenced-code-blocks
20. Agent SDK — Handle approvals and user input, Limitations (each `AskUserQuestion` call supports 1–4 questions with 2–4 options each). https://code.claude.com/docs/en/agent-sdk/user-input#limitations
21. Hooks — Hooks in skills and agents (skill hooks stay registered for the rest of the session; subagent hooks run only while that subagent runs; same format as settings hooks), a skill's copy of a handler stays separate from identical settings handlers, shell-form commands run via `sh -c`, which expands variables, and `strictPluginOnlyCustomization` (a personal skill keeps no frontmatter hooks under it). https://code.claude.com/docs/en/hooks#hooks-in-skills-and-agents
22. Subagents — Hooks in subagent frontmatter (hooks of user-level `~/.claude/agents/` and `--agents` subagents run without workspace trust; a project subagent's need it, and a `-p` session does not count) and the scope priority for agents sharing a name. https://code.claude.com/docs/en/sub-agents
23. Michael Nygard, "Documenting Architecture Decisions", 2011 — the Architecture Decision Record practice (title, context, decision, status, consequences), adapted here into Decision, Why, Source, and Accepted risk. https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions
