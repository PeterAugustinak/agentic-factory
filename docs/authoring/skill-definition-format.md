# PAF Skill Definition Format

This document defines the authoring format every PAF skill follows. It operationalizes [`architecture.md`](../architecture.md): the architecture decides *what* the skills do (orchestration, human gates, I/O ownership, loop/escalation, cost reporting); this document fixes *how* a skill is written as a `SKILL.md` so all three read consistently. It is the skill-side counterpart to [`agent-definition-format.md`](agent-definition-format.md).

Every choice is grounded in the official Claude Code skills documentation, the Agent Skills open standard, and Anthropic's own skill examples; sources are listed at the end. Nothing is guessed.

---

## File location and naming

- One directory per skill, with a required `SKILL.md` entrypoint: `skills/<skill-name>/SKILL.md`.(1)
- `SKILL.md` is **case-sensitive** and must be spelled exactly; `skill.md` will not load.(4)
- The directory name is **kebab-case** and becomes the slash command: `skills/create-issue/` → `/create-issue`.(1)
- Do **not** place a `README.md` inside a skill folder. Human-facing documentation lives in `docs/` (see [Progressive disclosure](#progressive-disclosure)).(4)
- The installer places skills under the PAF namespace in `~/.claude/skills/` (see `skills/README.md`). The command-name-from-directory rule and any namespace prefix behaviour is an installer (M6) concern; the source files here are authored as `skills/<name>/SKILL.md`.

---

## Frontmatter

A PAF skill's frontmatter uses these fields, in this order:

| Field | Use in PAF |
|---|---|
| `name` | The skill's display name in listings; kept identical to the directory/command name for clarity.(2) |
| `description` | One or two sentences: **what** the skill does and **when** to use it. The effective `description` (+ `when_to_use`) is truncated at 1,536 characters in the skill listing, so lead with the key use case.(2) |
| `disable-model-invocation` | **Always `true` for PAF skills.** This is the native mechanism that makes a skill **explicit-invocation only** — only the developer can invoke it via `/name`; Claude never auto-triggers it.(3) |
| `argument-hint` | For skills that take an argument, shown during autocomplete. **Always quote it** — e.g. `argument-hint: "[issue-number]"`. Unquoted `[issue-number]` is a YAML *flow sequence* (a list), not a string; Claude Code's lenient parser accepts it, but a strict schema validator rejects it as `invalid type: sequence, expected a string`.(2) |
| `allowed-tools` | Optional. Pre-approves the specific `gh`/`git`/test Bash commands the skill runs, so the developer is not prompted for each one. Does **not** restrict tools — it only removes approval prompts.(6) |

### Why `disable-model-invocation: true` on every PAF skill

PAF skills are **explicit-invocation only** — the three-skill split *is* the human-control architecture (`architecture.md` §2), and each skill has real side effects (posts issues, writes code, opens PRs). Claude must never decide to run one on its own. `disable-model-invocation: true` enforces exactly this natively: the developer can invoke with `/name`, Claude cannot auto-load it, and the description is kept out of automatic context.(3) This replaces the non-existent `invocation: explicit` field that earlier drafts guessed at.

### Fields deliberately not used

- **`context: fork` (and `agent`)** — **must not be used.** A forked skill runs as a *subagent*. Even though a subagent can now spawn its own subagents (Claude Code v2.1.172), it still **cannot run the human-gate tools** — `AskUserQuestion` and plan mode are main-thread-only.(5) A PAF skill is a human-gated orchestrator, so it must run **inline in the main thread**; forking would make the developer gates impossible. PAF skills therefore always run inline (default context).
- **`when_to_use`, `paths`** — auto-invocation aids; irrelevant because PAF skills are never auto-invoked.
- **`model`, `effort`, `hooks`, `disallowed-tools`** — left at defaults; the main thread is intentionally unrestricted (tool enforcement targets agents via the central hook, `architecture.md` §3), and per-skill model/effort tuning is not needed.

---

## Body (the orchestration instructions)

The markdown body is the skill's instructions. It enters the conversation as a single message when invoked and **stays in context for the rest of the session**, so it is written as standing instructions and kept concise — every line is a recurring token cost.(7)

PAF skill bodies are **imperative and step-numbered** — the architecture requires it: sequencing is prompt-based, not harness-enforced, so a skill must give explicit, ordered commands, not suggestions (`architecture.md` §2). Each body follows this shape:

1. **Purpose** — one line: what this run produces.
2. **Preconditions & arguments** — what must be true to start; how the argument (e.g. `$issue`, via the `arguments` frontmatter / `$ARGUMENTS`) is used.(8)
3. **Numbered steps** — the orchestration, one step per architecture-diagram box, each explicitly tagged as either:
   - **skill step** — external I/O the main thread performs (`gh`, git, running tests, appending to the cost ledger). All I/O is skill-owned (`architecture.md` §2).
   - **agent step** — an explicit, **by-name** invocation of a specialist agent (`@agent-<name>` / Agent tool), passing the required context and then parsing the returned output contract.(9)
   - **human gate** — a pause for developer input (plan-approval, or `AskUserQuestion`).
4. **Output-contract handling** — after every agent step, extract the **last** ` ```yaml ` block, validate it against the schema and enums (`architecture.md` §4), and **STOP and escalate** on any malformed/missing output.
5. **Loop & escalation** — retry caps and STOP behaviour exactly as `architecture.md` §5 fixes them.
6. **Cost & time** — append this run's cost + wall-clock to the per-feature ledger, and (at end of run) report the total (`architecture.md` §5).

Keep `SKILL.md` **under 500 lines**; move anything longer into supporting files.(7)

---

## Progressive disclosure — three tiers

A skill's material is split by *who reads it and when*:

- **`skills/<name>/SKILL.md`** — the operational instructions. Loaded into context when the skill is invoked.(1)
- **`skills/<name>/references/*.md`** — detailed machine-facing reference the skill loads **on demand** (e.g. the exact cost-ledger record format, contract-parsing edge cases). Referenced from `SKILL.md` by relative path so Claude knows what each file is and when to read it. Keeps `SKILL.md` lean.(10)
- **`docs/<skill-name>.md`** — human-facing explanation: the orchestration diagram, how the skill works, which agents it uses. **Never loaded by Claude**; it is documentation for the developer. Per-skill docs live here, not inside the skill folder (`architecture.md` decision; issue #5).

Shared, side-effectful `gh`/`git` sequences that recur across skills are factored into **`scripts/`** at the repo root and invoked via Bash — not duplicated in each `SKILL.md` and not pushed into agents (`architecture.md` §2).

**`skills/_shared/` — cross-skill runtime material.** Reference docs and helper scripts that *every* skill needs at run time (the output-contract parsing rules, the cost-reporting helper, the pricing table) live once in `skills/_shared/` and are reached from any skill via `${CLAUDE_SKILL_DIR}/../_shared/…`. This keeps them DRY and installed alongside the skills (reachable at run time), which `scripts/` — reserved for the installer and dev utilities — is not. `_shared/` has no `SKILL.md`, so Claude Code does not load it as a skill.

---

## Dynamic context and arguments

Two native mechanisms are available; use them deliberately:

- **Argument substitution** — `$ARGUMENTS`, `$0`/`$ARGUMENTS[0]`, or a named `$issue` declared via the `arguments` frontmatter. Used to thread the issue number through `implement-issue`.(8)
- **Shell injection** — `` !`<command>` `` runs a command and inlines its output *before* Claude sees the body.(11) Useful for pulling read-only context (e.g. the issue body) up front. **Caution:** injection always runs and has no error handling, so anything that can fail or needs validation (posting, branching, test runs, contract parsing) must be an explicit **skill step** using tools, not an injected command. Injection is for read-only priming only.

---

## Sources

1. Skills — Where skills live / each skill is a directory with `SKILL.md`. https://code.claude.com/docs/en/skills#where-skills-live
2. Skills — Frontmatter reference (`name`, `description`, `argument-hint`, `arguments`; 1,536-char listing cap). https://code.claude.com/docs/en/skills#frontmatter-reference
3. Skills — Control who invokes a skill (`disable-model-invocation`). https://code.claude.com/docs/en/skills#control-who-invokes-a-skill
4. Anthropic Skills repository — SKILL.md authoring conventions (case-sensitive filename, kebab-case, no README in skill folder). https://github.com/anthropics/skills
5. Subagents — Available tools (`AskUserQuestion` and other UI/session tools are main-thread-only, unavailable to subagents) and Spawn nested subagents (a subagent may spawn subagents up to depth 5, as of v2.1.172): https://code.claude.com/docs/en/sub-agents#available-tools — with Skills — Run skills in a subagent (`context: fork` runs as a subagent): https://code.claude.com/docs/en/skills#run-skills-in-a-subagent
6. Skills — Pre-approve tools for a skill (`allowed-tools` grants permission, does not restrict). https://code.claude.com/docs/en/skills#pre-approve-tools-for-a-skill
7. Skills — Skill content lifecycle / keep the body concise / keep SKILL.md under 500 lines. https://code.claude.com/docs/en/skills#skill-content-lifecycle
8. Skills — Pass arguments to skills (`$ARGUMENTS`, `$N`, named `arguments`). https://code.claude.com/docs/en/skills#pass-arguments-to-skills
9. Sub-agents — Invoke subagents explicitly. https://code.claude.com/docs/en/sub-agents#invoke-subagents-explicitly
10. Skills — Add supporting files (progressive disclosure via referenced files). https://code.claude.com/docs/en/skills#add-supporting-files
11. Skills — Inject dynamic context (`` !`command` `` preprocessing). https://code.claude.com/docs/en/skills#inject-dynamic-context
12. Anthropic's Complete Guide to Claude Skills Building. https://www.kdnuggets.com/anthropics-complete-guide-to-claude-skills-building