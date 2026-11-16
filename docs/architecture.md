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

- **Decision:** The skill instructs the plan→build phase to keep both turn count and main-thread context size down — batching independent calls, not re-reading, and keeping search output small — never at the cost of a read or a sweep the plan needs (`skills/paf-implement-issue/SKILL.md`, steps 4 and 7).
- **Why:** This phase is the factory's longest main-thread stretch. Every turn resends the whole conversation, and everything that enters the main-thread context is billed as a cache write and then as a cache read on every later turn, so both the number of turns and the size of what enters the context multiply cost. A measured run spent 30% of its cost on main-thread cache writes, with the same sweep run three times and three large saved tool outputs read back whole.
- **Source:** (13), (14)

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

- **Decision:** Text whose exact bytes matter is posted from a file, never retyped by the model after the fact. There is one such text: the MR/PR cost section, which must be the cost helper's output verbatim; how `check-out` builds and posts that file is its step 7 (`skills/paf-check-out/SKILL.md`). Only the main thread touches this file; agents receive content inline, or — the code reviewers — through the review input file, and the convention suggester through its own input file (§4, Input delivery). `create-issue` posts its body straight from a heredoc.
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

**Three skill kinds: setup, core, helper**

- **Decision:** Every PAF skill is one of three kinds. **Setup** — `init`, run once per repository before the pipeline. **Core** — the three main skills above, the end-to-end workflow in their fixed order. **Helper** — a developer-invoked skill for one specific purpose, outside the pipeline; it invokes no agents and does not report cost (§5). The installer lists the skills in these three groups: `init` and the core skills are named in `scripts/install.sh`, and every other installed skill is listed as a helper automatically; no frontmatter field records the kind.
- **Why:** The main skills and their order do not change (above), so naming them costs no maintenance, and a skill that is neither setup nor core is a helper by elimination. A frontmatter field would be a second place to state what the installer already knows.
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

- **Decision:** Every agent returns its result as one machine-parseable YAML block in its final message, and the **skill (main thread)** extracts, parses, and validates it. Malformed or missing output fails loudly and escalates to the developer ([Section 5](#5-loop-cap-escalation-and-cost-reporting)), with one advisory exception there. As implemented: the `## Output` section of every agent ([`agent-definition-format.md`](authoring/agent-definition-format.md), Output contract) and the parsing rules in `skills/paf-shared/output-contract.md`.
- **Why:** Claude Code has **no native typed return channel** for subagents — a subagent returns results as its final assistant message in plain text — and there is no native schema validation. The contract is machine-checkable only because the skill parses and validates it.
- **Source:** (2)

### Input delivery

**In the prompt, read from the project, or — for the code reviewers and the convention suggester — an input file**

- **Decision:** A skill passes every agent input as text in the invocation prompt, or names files inside the project root that the agent `Read`s itself. The code reviewers (`implement-issue`'s deep review, `check-out`'s safety net) instead get one shared review input file, and `check-out`'s convention suggester gets an input file of its own. Each skill step that invokes an agent states exactly what it passes.
- **Why:** A skill that leaves the input open lets the model improvise — and an improvised input breaks the run.
- **Source:** PAF design choice; no external source.

**Never through any other file outside the project**

- **Decision:** A skill never writes an agent input to a scratchpad, `/tmp`, or any other path outside the project root for the agent to read. The two exceptions are the **review input file**, written by the shared helper `skills/paf-shared/paf-review-input.py`, and the **convention suggester's input file**, written by `skills/paf-shared/paf-snapshot.py` as a separate file in the same folder. Both are user-scoped and written through `Bash`, not through the `Write` tool. A review input helper failure stops the run; a convention input failure only skips the suggestions (§5, Convention suggestions). As implemented: the helpers and the review steps of `skills/paf-implement-issue/SKILL.md` and `skills/paf-check-out/SKILL.md`.
- **Why:** The hook forces a permission prompt on every agent read outside the project root (§3), which stops an otherwise autonomous run. The review input file means the main thread never retypes the input and every reviewer of a run reads the same bytes. It is user-scoped because PAF leaves no trace in the project (§5) — no `.paf/` directory, no ignore or exclude entry — and the hook allows an agent `Read` of exactly that folder (§3). `Write` is avoided because its writes to the protected `.claude` path are never auto-approved. The suggester's file is its own so that neither helper overwrites or clears the other's input.
- **Source:** (15); #120; #130.

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

**Verify-fix loop (main-thread owner)**

- **Decision:** When `implementation-verifier` reports a test or UI check failure, the same main-thread context that built the code fixes it, never a cold builder agent, informed by the verifier's structured failure output, under the shared cap below. As implemented: the verify step of `skills/paf-implement-issue/SKILL.md`.
- **Why:** That context still holds the approved plan and the exact edits, so a cold agent would only re-derive them (§2, The review tail, and why there are two fix-owners).
- **Source:** PAF design choice; no external source.

**Review-fix loop (builder-agent owner)**

- **Decision:** The deep review runs **exactly once** per `implement-issue` run and is never re-run inside it. A builder agent receives all aggregated findings and the issue body verbatim and decides which to apply, bounded by the triage rule and sweep obligation of §1, Builder; re-verification after its fixes runs under the shared cap below. The developer does not pre-select fixes, so there is no `AskUserQuestion` gate; the hand-off flags only what the diff cannot show at a glance — a behaviour change beyond the plan and each skipped `error` finding. As implemented: the review, triage, and re-verify steps of `skills/paf-implement-issue/SKILL.md`, and `agents/full-stack-dev.md`.
- **Why:** The second look at the code is the developer's manual review, backed by `check-out`'s safety-net review whenever the branch's content changed after the hand-off. The developer curates the applied fixes from the uncommitted diff, the curation and revert point; pre-selecting them would put a decision in front of the developer that their own review answers better, with the code in hand.
- **Source:** PAF design choice; no external source.

**Acceptance loop (main-thread owner)**

- **Decision:** An acceptance check against the issue's acceptance criteria runs last, before the hand-off. An issue with no acceptance criteria, or an empty section, stops `implement-issue` before validating or planning; `check-out` instead falls back silently to the issue body as the spec, so a legacy issue still ships. An unmet criterion is fixed by the main-thread context that planned and built the change, under the shared cap below. A fix never adds a detail that is not must-have; a must-have item beyond the issue is put to the developer, and a no or no answer stops the run with no fingerprint, as does something the issue requires that the code makes impossible. As implemented: the read and acceptance steps of `skills/paf-implement-issue/SKILL.md`.
- **Why:** An unmet acceptance criterion is caught by `implement-issue` and never first surfaces at `check-out`. An issue with no criteria has nothing to check the work against, so it is not ready. The must-have item is asked because the plan approval is already past.
- **Source:** PAF design choice; no external source.

**Shared to all loops**

- **Decision:** Each of the three fix loops above allows at most **2** retries after the initial failure, with the same escalation: on exhaustion the run stops and hands back what failed (the last verifier output, or for the acceptance loop the unmet criteria), and a suggested next action; the developer adjusts the plan or issue and re-invokes `implement-issue`. Whoever applied a fix never validates it: `implementation-verifier` runs as a separate agent after every fix. As implemented: `skills/paf-implement-issue/SKILL.md`.
- **Why:** A loop that cannot converge in two attempts needs the developer's judgement, not more attempts; one cap and one escalation keep the stopping rule the same in every loop. A fixer judging its own fix is not an independent check.
- **Source:** PAF design choice; no external source.

### `check-out` safety-net review and gate

**Confirmation-and-ship gate**

- **Decision:** `check-out` is a **confirmation-and-ship gate**, not a review-and-fix stage: a single safety-net review and one acceptance check, both skipped when nothing changed since `implement-issue`'s hand-off, with the advisory convention suggestions under the same condition, then the pre-merge validation, then git/VCS finalisation. The pre-merge validation stays the last gate before the commit and the MR/PR. As implemented: `skills/paf-check-out/SKILL.md`.
- **Why:** The deep review already ran in `implement-issue`, before the developer's manual review (§2).
- **Source:** #121 (the gate order, developer's decision).

**One caller-framed safety net**

- **Decision:** `senior-engineer-reviewer` runs as a high-level confirmation pass framed at the call site, never in the agent definition: the diff was already deep-reviewed, so it looks for critical regressions, especially in the developer's hand-edits, reports them as `error`, and reports no warnings. Like the deep reviewers it reads the issue body verbatim from the review input file (§4, Input delivery), and what the issue decides or places out of scope is not a finding — for an issue without the agent section, whatever its body states. `check-out` has no triage, so its gate counts every parsed `error`, and a decided item wrongly flagged as `error` stops the run for the developer to decide. As implemented: the safety-net step of `skills/paf-check-out/SKILL.md`.
- **Why:** A permanent "be shallow" instruction in the agent would damage the same agent's deep use in `implement-issue`, and agents are caller-agnostic (§2). The net's purpose is the one slice of code no agent has seen: the developer's hand-edits. `check-out` has no fixer, so a warning could neither be acted on nor usefully printed.
- **Source:** PAF design choice; no external source.
- **Accepted risk:** Accepted gap — only the functional lens is applied; the complexity, security, test-coverage, and conformance reviews are not repeated.

**Skipped, deterministically, when there are no hand-edits**

- **Decision:** `implement-issue` pins a content fingerprint at a successful hand-off, and `check-out` recomputes it before its review. An exact match skips **both** the safety-net review and the acceptance check, deterministically and silently — a skip is the standard run. A mismatch, a missing or unreadable record, or any failure to recompute runs both: absence of evidence fails safe. The fingerprint covers every path that differs from a pinned base commit, tracked and untracked, hashed from the working tree; it is base-pinned, commit-invariant, and content-based. Its record lives in the user's `~/.claude/paf/` namespace, never in the project, keyed by repository root and issue, overwritten by a re-run of `implement-issue` and removed when `check-out` cleans up the cost ledger. As implemented: `skills/paf-shared/paf-fingerprint.py` and both skills' `SKILL.md`.
- **Why:** With no hand-edits the safety net has nothing to review, and the acceptance check would re-check exactly the content `implement-issue`'s own acceptance check passed — the fingerprint is recorded only on that path, so it proves it. The repeated acceptance check cost €0.15–0.32 per `check-out` run, and a second pass over identical input risks a false block because same-definition agents are non-deterministic (the reason `implement-issue` skips re-validating a PAF-authored issue). Code built any other way has no record and is reviewed. Base-pinning means a later move of the base ref cannot shift the fingerprint; commit-invariance means a commit that changes no content still matches, since committing is not editing; content-based means diff config and external diff/textconv drivers cannot shift it.
- **Source:** #121; cost measured from session transcripts, 2026-11-12.

**Accepted limit — the fingerprint covers branch content, not the issue**

- **Decision:** The fingerprint covers the branch content only; changed acceptance criteria mean re-running `implement-issue`.
- **Why:** The safety-net skip already ignored issue edits the same way.
- **Source:** #121 (developer's choice).
- **Accepted risk:** If the issue's acceptance criteria are edited after the hand-off while the code is unchanged, the fingerprint still matches, `check-out` skips both agents, and the edited criteria are not re-checked. An accepted limit, not a closed hole.

**Hand-off snapshot**

- **Decision:** At the same successful hand-off that pins the fingerprint, `implement-issue` also saves a snapshot of the working tree — tracked and untracked files, ignored files left out — as a git tree. It is built with a temporary index, and every new git object goes to an object directory in the user's `~/.claude/paf/` namespace that reaches the repository's object store as an alternate, so the repository's index, status and object store stay unchanged. It is keyed like the fingerprint, replaced by a re-run of `implement-issue`, and removed with the fingerprint when `check-out` ships; an abandoned one is left in place, with no age-based cleanup. A failed save prints its error and the run continues. As implemented: `skills/paf-shared/paf-snapshot.py` and both skills' `SKILL.md`.
- **Why:** The fingerprint stores checksums, so it knows which files changed since the hand-off but not what changed; the convention suggester (below) needs the diff. A git tree yields that diff with git alone, standard library only, and git's own environment variables redirect the index and the object store without touching the repository.
- **Source:** (24) (25); #130 (verified in a scratch repository and a linked worktree).
- **Accepted risk:** The snapshot refers to the repository's object store through the alternate, and git may prune an object there that only the snapshot still uses — for example a blob that was staged and later replaced(25). The snapshot then cannot be read, and the convention suggestions are skipped with a deviation line; `check-out` itself continues. An accepted limit, not a closed hole.

**Convention suggestions — advisory**

- **Decision:** When the content changed since the hand-off, a snapshot exists, and a project instructions file exists, `check-out` runs `convention-suggester` alongside the safety-net review on the diff between the snapshot and the current code. Its suggestions — general conventions the developer's hand-edits show that the instructions do not state, at most three — are put to the developer one question each, after the acceptance check passes and before the pre-merge validation; **Add** writes the sentence into the project instructions file, and it is committed with the feature. The feature is advisory and never stops a run; without a change, a snapshot, or an instructions file there is no agent, no question, and nothing printed. As implemented: the safety-net and spec-check steps of `skills/paf-check-out/SKILL.md` and `agents/convention-suggester.md`.
- **Why:** The deep review checks the code against the conventions the project instructions state; every correction the developer makes after the hand-off is about one that is not written there, and unless it reaches the instructions the next feature repeats it. The developer's own **Add** is the only way a rule lands, so a wrong suggestion costs a click, not a rule. Asking before the pre-merge validation keeps that validation the last gate before the commit and the MR/PR.
- **Source:** #130 (developer's decisions).

**Accepted limits of the safety net when it runs**

- **Decision:** When it runs, the safety net sees the whole branch change against the base (§4, Input delivery), and its framing tells it not to re-litigate the already-reviewed implementation.
- **Why:** The hand-edits cannot be isolated from the implementation already reviewed: when the work is left uncommitted there is no git boundary that could carve them out. The fingerprint decides only *whether* the review runs, not *what* it sees.
- **Source:** PAF design choice; no external source.
- **Accepted risk:** The reviewer may re-see, and re-flag, code the deep review already reviewed and fixed — the rework cycle this design exists to remove; the framing is an instruction, not a mechanism that isolates the hand-edits. And a hand-edit to a path marked `--assume-unchanged` or `--skip-worktree` is invisible to `git diff` and so to the fingerprint, as is a line-ending-only edit that a clean filter or `core.autocrlf` normalises away, which can then skip a review it should have run. Both are accepted limits of a caller-framed, single-diff safety net, not closed holes.

**The gate is computed by the skill, from severity**

- **Decision:** The skill branches on the parsed `issues[].severity`, not on the agent's `status`: `error` stops the run; a `warning` returned despite the framing is dropped, never printed.
- **Why:** A review agent reports `success` on completion regardless of findings (§4), and this one is not a final-gate agent.
- **Source:** PAF design choice; no external source.

**No fix loop, no retry — failures STOP and escalate**

- **Decision:** `check-out` never fixes-and-continues on anything requiring judgement and never retries a check, with two bounded exceptions, each capped at a single attempt and neither a fix loop: the mechanical auto-fix (mutation posture, below) and the isolated re-run of failed tests (flaky tests, below). Any blocker — an `error` from the safety net, an unmet criterion, a failing pre-merge validation, malformed agent output (bar the advisory convention suggester's, Malformed-contract escalation below), a failure to open the MR/PR — halts the run and escalates to the developer, who resolves it and re-runs `check-out`. The stop points and the failure output are in `skills/paf-check-out/SKILL.md` (its output step and Escalation section).
- **Why:** `check-out` is the final human-controlled finalisation stage, so the developer — not the factory — decides how to resolve a failure.
- **Source:** PAF design choice; no external source.

**Minimal final output**

- **Decision:** On success `check-out` prints only the result, the MR/PR link, one line per deviation from the standard run when it applies, and the cost, with no recap of the steps; a missing or empty acceptance-criteria section is not a deviation. It asks no in-skill confirmation. The fields are in the output step of `skills/paf-check-out/SKILL.md` and in `docs/skills/check-out.md`.
- **Why:** Invoking the skill is the developer's go-ahead, and only a departure from the standard run tells them something they do not already know.
- **Source:** PAF design choice; no external source.

**`check-out` mutation posture**

- **Decision:** On a pre-merge failure `check-out` may run a **tool-driven, behaviour-preserving auto-fix**: the auto-fix command the project instructions define, exactly as defined, then the pre-merge validation **once** more. It may **never** apply a judgement-requiring or semantic fix — that stays a stop for the developer. The command is entirely **project-defined and optional**: the architecture names no tool or flag, and a project that defines none keeps the stop-on-fail behaviour, subject only to the isolated re-run of failed tests (flaky tests, below). As implemented: the pre-merge step of `skills/paf-check-out/SKILL.md`.
- **Why:** Three properties keep this from re-opening the fix loop closed above: the fix is performed by the **project's own tooling**, never authored by the model, so it cannot make a semantic change under the guise of a format fix; the re-validation **is** the fixability split, deterministically — whatever the tool could fix is gone, whatever remains needs judgement by definition, so nothing has to *judge* which failures were mechanical; and the attempt is capped at **one**, so a failure that survives it escalates as any other. Leaving the command to the project is consistent with the project instructions being a content checklist, not a format.
- **Source:** PAF design choice; no external source.
- **Accepted risk:** This mutation is a new shape of exposure in `check-out`, not one covered elsewhere in this document. It runs downstream of every review layer `check-out` has — the safety-net review and the acceptance check when they run, and the developer's own manual review of the implemented code, all of which precede it — and its diff is committed, pushed, and put in front of the MR/PR with no review agent re-run and no additional developer-approval gate; the only signal is the auto-fix line of the final output. That a tool-driven fix cannot make a semantic change is an assumption about the configured command's behaviour, not something PAF verifies at runtime — an aggressive auto-fix mode could still ship an unreviewed semantic change. The single-attempt cap and the "never a tool or flag you chose yourself" constraint are enforced only at the advisory prompt layer, consistent with "No allow-list on the main thread" (§3). The command is also `check-out`'s first instructions-sourced value that **writes** files which are then committed and pushed, run with the developer's full privileges on the strength of only the developer's invocation of `check-out` after their review of the implemented code — a go-ahead given before, and unable to anticipate, a mid-run pre-merge failure; `check-out` asks no in-skill confirmation. The compensating control is structural, not an added gate: the developer's own review of the MR/PR at the skill boundary (§2, The skill boundaries are the primary gates) is still the last human eyes on this diff before merge, as for every other change `check-out` ships. An accepted limit of a mechanical, tool-driven auto-fix, not a closed hole.

**Flaky tests — isolated re-run**

- **Decision:** When the pre-merge failure left after the auto-fix handling consists only of failed tests that the output names, `check-out` re-runs each of them **on its own, once**, with the project's test command scoped to that single test the way `implementation-verifier` scopes it to an area — no new project-instruction value and no other tool. Every one passing lets the run continue without re-running the full command; any one failing again, any other failure, output that names no failed test, or a project with no test command stops the run as before. It is capped at one run per test and changes no code, so it is neither a fix loop nor a mutation; `check-out` still never hand-edits code to make the gate pass, and when the re-run carried the gate the MR/PR description says so rather than claiming the full command passed. As implemented: the pre-merge step of `skills/paf-check-out/SKILL.md`.
- **Why:** A flaky test should not stop `check-out` when it passes on its own.
- **Source:** #121 (developer's decision, 2026-11-12).

### Verification scope — two tiers

**Scoped in the loop, full at the gate**

- **Decision:** The factory has two verification points with deliberately different scopes. `implementation-verifier` (scoped, in-loop) runs a **targeted subset** of the test suite — the tests covering the changed area or module (e.g. the affected Django app, or the affected CDK service/resource), not merely the changed test files and not the whole suite — and never the project's lint command or its full pre-merge command. The pre-merge validation (full, at the gate) runs the project's **full** test/lint suite once at `check-out`; it is the only verification tier `check-out` runs, and its auto-fix (mutation posture, above) is re-validated by that same full command. The isolated re-run of a failed test (flaky tests, above) is a flakiness check, not a tier. As implemented: `agents/implementation-verifier.md` and the verification steps of `skills/paf-implement-issue/SKILL.md` and `skills/paf-check-out/SKILL.md`.
- **Why:** Fast scoped feedback during implementation, full validation before the PR. The scoped tier runs inside `implement-issue`'s fix loops, so keeping it scoped keeps them fast and cheap — pulling the fuller command into it would inflate exactly the cost and latency the split exists to contain. The full tier is the final safety net that catches any cross-module regression a scoped run could not see, and the tier the lint command belongs to.
- **Source:** PAF design choice; no external source.

**The UI check in the scoped tier**

- **Decision:** When a change touches UI (a template, a stylesheet, or browser-side JavaScript/TypeScript), the scoped tier also runs the project's optional **UI check command**, verbatim, whether or not the tests passed, and a UI check failure is a verification failure under the same cap. The command is **project-defined**, like the test command, rather than PAF rendering pages itself. It is **never skipped silently**: a UI-touching change with no UI check command defined is flagged in `implement-issue`'s hand-off and in `check-out`'s MR/PR description. As implemented: `agents/implementation-verifier.md` and both skills' `SKILL.md`.
- **Why:** Server-side tests cannot observe rendering, so for a UI change they alone would claim a verification never performed. Running it regardless of the tests lets one fix pass see every failure. Project-defined because browser tools are not reliably available in every session, which pages and element states to check is project knowledge, and rendering in PAF would break project-agnostic skills and the zero-dependency rule.
- **Source:** #83.

**Implementation-defined**

- **Decision:** How the affected area or module is determined (e.g. derived from the builder's reported `artifacts` plus project conventions) and the exact scoped and full commands are **project-specific and sourced from the project instructions** (§6) — not fixed by this architecture.
- **Why:** They are project knowledge, which PAF's skills and agents do not hold.
- **Source:** PAF design choice; no external source.

### `issue-validator` escalation

**Where the validator runs**

- **Decision:** `issue-validator` checks an issue's **factual claims**, against authoritative docs **and** the repository, and its **completeness** — never an implementation plan. It always runs in `create-issue`, on the drafted issue before it is posted; in `implement-issue` it runs **only for issues PAF did not already validate** — a shift-left pass plus a source-aware safety net. The validator never calls `gh` itself; the caller acts on its findings.
- **Why:** Validating the draft before it is posted catches a defect at the source rather than later, closing the gap where `issue-writer` (read-only, no web access) faithfully transcribes an unverified approach.
- **Source:** PAF design choice; no external source.

**What is checked**

- **Decision:** Both externally-verifiable claims (a CLI flag, an API signature, library behaviour, and the cited spec's caveats and scope limits, not just its headline rule) **and** repo-grounded ones (a named path that does not exist, a description of current behaviour that contradicts the code, an approach infeasible against the existing implementation). **Findings are bounded to factual/feasibility and completeness defects**, never implementation guidance (flag choices, edge-case handling, fixture design, output formatting). The boundary is owned by `agents/issue-validator.md`, so it applies wherever the agent runs.
- **Why:** Implementation guidance is decided later, against the live repository, not at validation time. Owning the boundary in the agent keeps it caller-agnostic (§2).
- **Source:** PAF design choice; no external source.

**Completeness**

- **Decision:** Every behaviour case a Decision or acceptance criterion touches must be covered by the issue. An uncovered case is an **open point** — a behaviour, output or scope choice the issue does not settle — and a `severity: error` whose message starts `Uncovered:` (the same message-prefix convention as `issue-writer`'s `Undecided:`). Behaviour only: how it is built (file layout, naming, edit structure, which files or code area) is never an open point, an incomplete file list is never a finding, and the validator never drafts or demands a plan.
- **Why:** An issue with an open point is not ready to post, and the goal is a plan with zero deviations.
- **Source:** #105, where five of six plan "deviations" restated consequences of the issue and the one real gap was an uncovered case.

**Scope discipline**

- **Decision:** The skill passes the whole draft and never skips the step; the validator owns which claims it checks (`agents/issue-validator.md`) — in an issue with the agent section, the factual claims in its `Context`, `Decisions`, `Constraints` and `Pitfalls` subsections. `Scope of changes` is the author's **hint**: an incomplete file list is never a finding and nothing there is a blocker.
- **Why:** `issue-writer` keeps every checkable technical fact in those subsections, so the concise human part carries none left unchecked. The implementer derives the real files from the issue's intent and the live repository.
- **Source:** PAF design choice; no external source.

**Findings handling**

- **Decision:** Nothing is posted before the findings are handled, and every finding has exactly **one** destination: a wrong fact whose correct value the finding states is fixed **in place**, where the body makes that same claim, never appended as a note; a new fact the implementer needs goes into the agent section's `### Context`; an open choice is asked, whatever its severity; anything else is dropped. Open choices are asked together in **one question phase** (`AskUserQuestion` takes at most four questions per call, so more than four take back-to-back calls within the phase) followed by **one update**, which re-validates only the claims that changed; at most two updates per part, and anything still open after that **stops the run and nothing is posted**. As implemented: the findings step of `skills/paf-create-issue/SKILL.md`.
- **Why:** A spec whose body contradicts its own notes forces the implementer to guess which is right — the same factual/self-consistency rule `implement-issue` applies to review findings. The validator's message is data, so only its substitution is applied. Asking open choices as they arose added a writer and a validator run per round, and every extra main-thread call resent the conversation. Re-validating the whole draft makes a non-deterministic agent re-explore cleared text and produce fresh findings rather than confirm the fix. There is no review gate to adjudicate what is still open after the cap.
- **Source:** (20) for the `AskUserQuestion` four-questions-per-call limit; #116 — measured `create-issue` cost rose from about EUR 0.48 to EUR 1.05–1.50 per run as separate question rounds each added a writer and a validator run; #111, where an open choice graded as a warning was posted as a note and `implement-issue` stopped on it.

**No review gate**

- **Decision:** `create-issue` has no review gate: every decision the issue needs is put to the developer before drafting or in the question phase, so an issue with nothing left to ask is posted directly.
- **Why:** The draft then holds only confirmed content, and the developer reviews the posted issue at the skill boundary (§2, The skill boundaries are the primary gates).
- **Source:** PAF design choice; no external source.

**PAF-validated heading**

- **Decision:** The cross-skill contract, defined here: every issue `create-issue` posts carries an agent section headed by a line reading exactly `## For implementation agent`, written by `issue-writer` (`agents/issue-writer.md`). It is `implement-issue`'s signal that PAF already validated the issue. Because the heading is the contract, `issue-writer` never rewords it and `implement-issue` matches the whole line exactly.
- **Why:** A plain CommonMark ATX heading renders on both providers and survives any rendering, so fetching the issue through `paf-vcs` stays a one-liner.
- **Source:** PAF design choice. Verified: `gh issue view`'s non-interactive output prints the raw issue body; the GitLab path — whether `glab issue view` prints raw Markdown when not attached to a terminal — inherits the pending #14 validation caveat.

**Heading present**

- **Decision:** `implement-issue` skips the validator and goes to plan mode, which starts from the agent section's Context (and Scope of changes) as a hint of the code area; where the code differs, the plan works from the real code, unreported. The plan builds only what the issue states; a must-have item the issue missed is listed in its own plan part and agreed by approving the plan, and only something the code makes impossible stops the run. As implemented: the read and plan steps of `skills/paf-implement-issue/SKILL.md`.
- **Why:** The issue was already validated in `create-issue`. Re-validating it is redundant, and because same-definition agents are non-deterministic it could "block" an issue `create-issue` had already validated — the recurring validated-then-disabled failure.
- **Source:** PAF design choice; no external source.

**Heading absent**

- **Decision:** A hand-written issue, or one created outside PAF, gets the validator as its only validation. `implement-issue` posts only the actual findings as an issue comment, none when there are none, never the verdict or a recap of confirmed claims. A completeness (`Uncovered:`) blocker always stops the run, with no approve-and-fold option. A factual `severity: error` is put to the developer, quoting the findings, to fold into the plan or stop; a missing answer counts as stop, never auto-approved. `warning` findings are carried into the plan. As implemented: the validation steps of `skills/paf-implement-issue/SKILL.md`.
- **Why:** An open behaviour case is settled in the issue, never in the plan. The files an issue names are only a hint decided in plan mode, so a factual blocker is the developer's call rather than an automatic halt.
- **Source:** PAF design choice; no external source.

**Accepted residual risk (false skip)**

- **Decision:** The skip rests on the heading, which is content in the issue body; the compensating control is the plan-review gate (`ExitPlanMode`), where the concrete plan is scrutinised against the live repository before any code is written.
- **Why:** An infeasible approach surfaces at the plan-review gate regardless of how the issue was validated. Re-validating the edge cases below is traded for never re-validating a PAF issue and never hitting the non-deterministic false blocker.
- **Source:** PAF design choice; no external source.
- **Accepted risk:** Two symmetric false-skip cases. (1) *Heading survives manual edits* — an issue PAF authored and a developer then edited after creation still carries it and is skipped at implementation time. (2) *Coincidental content* — a hand-written issue that happens to contain a line reading exactly `## For implementation agent` would be mistaken for a validated one and skip the validator that is otherwise its only check; matching the whole line exactly makes this unlikely but not impossible. An accepted limit, not a closed hole.

### Malformed-contract escalation

**Defensive parsing**

- **Decision:** The skill extracts the **last** fenced YAML block from an agent's final message and validates its required keys and enum values; on any missing block, parse error, missing key, or invalid enum value it **stops and escalates to the developer, including the agent's raw output**. It never proceeds on a partial or guessed parse. As implemented: `skills/paf-shared/output-contract.md`.
- **Why:** The whole pipeline depends on the contract, and the raw output makes the failure diagnosable.
- **Source:** PAF design choice; no external source.

**Advisory exception — `convention-suggester`**

- **Decision:** A missing or malformed report from `convention-suggester`, or a `status` other than `success`, does not stop `check-out`: the convention suggestions are skipped, one deviation line in the final output says so, and the run continues. It is the only agent whose output is exempt from the stop above. As implemented: the safety-net step of `skills/paf-check-out/SKILL.md`.
- **Why:** The suggestions are an optional improvement to the project instructions, never a gate on shipping work that was already reviewed and accepted; stopping the ship over them would trade the feature for a nicety. The deviation line keeps the skip visible.
- **Source:** #130 (developer's decision).

**Unclosed fence**

- **Decision:** A block with no closing fence runs to the end of the message, so it is extracted and validated, not treated as missing; if it passes, the run continues and the developer is told the report may be truncated, here and in the run's final report. As implemented: `skills/paf-shared/output-contract.md`.
- **Why:** That is what CommonMark specifies for an unclosed fence, so it is not a guess at the block's boundary; stopping on one threw away complete reports.
- **Source:** (19)
- **Accepted risk:** The closing fence is the only sign a report was not cut off. `issues` is the last key, so a cut before it fails on a missing key and a cut inside a quoted value fails to parse, but a cut between two `issues` entries validates with findings lost. Telling the developer surfaces that case rather than closing it.

### Cost reporting

**Every skill reports its cost, with an exemption list**

- **Decision:** Every skill run ends with a single report of the **token cost of that invocation**, except the skills listed here:
  - `init` — a setup and health check run before any feature exists, so there is no issue to key a ledger entry on (below).
  - helper skills ([Three skill kinds](#human-interception-model)) — they run outside the feature pipeline and invoke no agents, so their cost is near zero and there is no feature to attribute it to.

  A new skill reports cost by default; exempting one means adding it to this list with its reason.
- **Why:** Reporting is the default, so an exemption is a deliberate choice that carries its own reason.
- **Source:** PAF design choice; no external source.

**Measured from the transcript, not self-reported**

- **Decision:** Agents do not report cost; the skill computes it from the session transcript, which records per-message `usage` (input, output, cache-read, and cache-creation tokens) and `model`, so every message is priced at its own model's rates. The mechanism for attributing usage to individual agents is an implementation detail; the architecture requires only that the final total is reported. As implemented: `skills/paf-shared/paf-report-cost.py`.
- **Why:** An agent cannot reliably count its own tokens (§4, No cost block), while the transcript holds exact per-message counts.
- **Source:** (7) (9)

**Per-invocation slice, not the whole session**

- **Decision:** Each run is priced as a disjoint slice of the transcript, from the mark it sets at its start onward, main-thread and subagent messages alike. As implemented: `skills/paf-shared/paf-report-cost.py`.
- **Why:** Several skills can run in **one** CLI session (Cross-skill cost aggregation, below): pricing the whole transcript would re-price an earlier skill's tokens and inflate the feature total, and a `create-issue` run inside a large multi-day session would price the entire session.
- **Source:** PAF design choice; no external source.

**Stopped runs are recovered, not lost**

- **Decision:** A run that stops before its cost step is still priced and added to its feature's ledger as a stopped run: its start marker carries its own attribution, and the cost helper closes an open marker on the next run of the same skill in that session and in `check-out`'s aggregation, ending its slice at the next PAF skill boundary in its session so it never overlaps a run recorded after it. Recovery lives in the cost helper, not in the skills' stop paths. As implemented: `skills/paf-shared/paf-report-cost.py`.
- **Why:** Stops are many and often unplanned, so a failure-path instruction could not be relied on.
- **Source:** PAF design choice; no external source.
- **Accepted risk:** Known limits — a run marked before its feature has any key cannot be attributed if it stops: a `create-issue` run that stops before posting (no issue number yet), or an `implement-issue` run without an issue number (it marks on the base branch, before the feature branch exists). A run still going in another session when `check-out` aggregates is recorded as stopped up to that moment, its later record pricing only what follows.

**Pricing is per model, not per snapshot**

- **Decision:** A model id is canonicalised before it is priced: a trailing snapshot date is stripped, so a dated snapshot and its alias are the same model at the same rate, and the price table's keys are dateless. As implemented: `skills/paf-shared/paf-report-cost.py` and `pricing.json`.
- **Why:** The model-id grammar makes a trailing eight-digit segment a snapshot date, not a version. A dated key could never match, and a dated snapshot of a priced model is then an exact match, not a fallback.
- **Source:** (10)

**Rates are per model, priced per request**

- **Decision:** Every model carries its own five rates, as the pricing page lists them, and a model priced by prompt length is priced per transcript message at the tier that message's prompt length selects.
- **Why:** Cache rates are not a fixed multiple of input across models — cache reads are 0.1x input on most models, 0.05x on Opus 5.5 and Sonnet 5.5, and 0.025x on Fable 5.2, Mythos 5.2, Fable 5.1 and Mythos 5.1. A model priced by prompt length (Haiku 5.5: up to / over 100,000 prompt tokens) is billed per request, counting all of its input tokens — cache reads and cache writes included — toward that length; every term of that sum is in each message's `usage`, so the tier is exact, not approximated.
- **Source:** (13)

**Unpriced models are never dropped**

- **Decision:** Tokens of a model still absent from the price table after canonicalisation are priced at the latest known rate of the same family (opus/sonnet/haiku), and the report flags that the price table must be updated.
- **Why:** An undercount is never silently produced.
- **Source:** PAF design choice; no external source.

**Currency**

- **Decision:** PAF reports cost in **EUR**, converted with a factory-maintained USD→EUR rate kept alongside the per-model price table; both are updated together and carry their source and date.
- **Why:** Anthropic bills in USD, so the rate and the price table change together.
- **Source:** PAF design choice; no external source.

**Tokens as well as money**

- **Decision:** The report shows the token breakdown — in, out, cached, total — beside the EUR cost, in both the CLI output and the PR.
- **Why:** Money alone hides whether a run was expensive because of volume or because of model choice; the counts are already collected for pricing, so surfacing them costs nothing.
- **Source:** PAF design choice; no external source.

#### Cross-skill cost aggregation

**Per-feature cost ledger**

- **Decision:** PAF maintains its own **per-feature cost ledger** that every run of the three main skills — `create-issue`, `implement-issue`, `check-out` — appends its per-invocation cost to.
- **Why:** A feature spans the three main-skill runs, usually in separate Claude Code sessions, though `implement-issue` and `check-out` in particular often run back-to-back in one; Claude Code has no native cross-session cost aggregation.
- **Source:** PAF design choice; no external source.

**Keyed by issue number, or by branch when there is none**

- **Decision:** A feature with an issue is keyed by its number, and one without by its branch name; the issue number wins whenever both are known, so an issue-keyed feature keeps one ledger across all three skills. A split `create-issue` run that posts several issues shares its cost and token counts equally across their ledgers. PAF never stops or fails over a missing or malformed issue number: it falls back to the branch, and with neither a run's cost is still reported, just not added to a ledger. How each skill obtains the key is in its `SKILL.md`; the keying and the split are in `skills/paf-shared/paf-report-cost.py`.
- **Why:** Not every feature has an issue, and no part of a split run can be attributed to one issue.
- **Source:** PAF design choice; no external source.

**User-scoped, never in the project**

- **Decision:** The ledger lives under the user's `~/.claude/` namespace, not in the target repository — no `.paf/` directory, no gitignore entry. The hand-off fingerprints and snapshots (above) and the review and convention input files (§4, Input delivery) share this user scope.
- **Why:** It preserves PAF's project-agnostic principle: installing and running PAF leaves no trace in the project.
- **Source:** PAF design choice; no external source.

**Totalled at check-out**

- **Decision:** `check-out` records its own run, recovers any stopped run of the feature, sums every entry, writes the **total cost — with a per-skill breakdown — into the PR description**, then removes the ledger. As implemented: the cost and MR/PR steps of `skills/paf-check-out/SKILL.md`.
- **Why:** The PR reviewer never sees the CLI session, so the PR is where the whole feature's cost is shown.
- **Source:** PAF design choice; no external source.

**Graceful degradation**

- **Decision:** If the branch → issue-number mapping is unavailable, `check-out` totals the feature by its branch rather than failing.
- **Why:** Cost reporting never stops a run, as with the missing-issue fallback above.
- **Source:** PAF design choice; no external source.

**What the architecture fixes**

- **Decision:** The exact ledger location, record format, and pricing table are implementation details of the shared cost helper. The architecture fixes only that per-feature cost is aggregated across the three main skills, stored in user scope, reported in EUR with a token breakdown, and surfaced in the PR.
- **Why:** The helper can change them without re-deciding anything here.
- **Source:** PAF design choice; no external source.

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
24. Git — Environment variables (`GIT_INDEX_FILE`, `GIT_OBJECT_DIRECTORY`, `GIT_ALTERNATE_OBJECT_DIRECTORIES`). https://git-scm.com/docs/git#_environment_variables
25. git-clone — `--shared` (objects reached through alternates; the warning that pruning the source repository can corrupt a repository that depends on it). https://git-scm.com/docs/git-clone#Documentation/git-clone.txt---shared
