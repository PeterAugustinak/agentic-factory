# PAF Agent Definition Format

This document defines the authoring format every PAF agent file follows. It operationalizes [`architecture.md`](../architecture.md): the architecture decides *what* each agent is (model, tool scope, role, output contract); this document fixes *how* that is written into a file so all agent files read identically.

Every choice here is grounded in the official Claude Code subagents documentation; sources are listed at the end. Nothing is guessed — where a behaviour was not fully documented, it was verified empirically and the result is recorded.

---

## File location and naming

- One file per agent: `agents/<agent-name>.md`.
- The agent's identity comes from the `name` frontmatter field, not the filename, but PAF keeps them identical for clarity.(1)
- `name` uses lowercase letters and hyphens only.(2)
- The installer places these files at `~/.claude/agents/paf/`. Claude Code scans `~/.claude/agents/` recursively, and the subfolder does not change how an agent is identified or invoked — identity is the `name` field.(1)

---

## Frontmatter

A PAF agent file begins with YAML frontmatter using exactly these fields, in this order:

| Field | Required | Value in PAF |
|---|---|---|
| `name` | Yes | The agent name, matching the file name (e.g. `issue-writer`). Received by hooks as `agent_type`.(2) |
| `description` | Yes | One sentence stating what the agent does. PAF agents are invoked **explicitly by name** from skills, so this is documentation, not an auto-delegation trigger. |
| `model` | No (defaults to `inherit`) | The alias from `architecture.md` §1: `haiku`, `sonnet`, or `opus`. Aliases are used, not full model IDs, so the factory tracks model upgrades automatically.(3) |
| `tools` | No (inherits all if omitted) | The **allowlist** derived per `architecture.md` §3 (Scoping an agent), comma-separated. Only listed tools are available; every other tool — including all MCP tools — is denied.(4) |
| `hooks` | Yes, in PAF | The identical block every PAF agent carries, registering the centralized `PreToolUse` hook for this agent's own tool calls (`hooks/README.md`, `architecture.md` §3). It holds no policy, only the path to the one hook script; the agent's `name` must also be in that script's `PAF_AGENTS` set.(2) |

### Why the allowlist (`tools`) form, not the denylist

`architecture.md` §3 (Scoping an agent) derives the tools each agent is allowed from its category. PAF encodes them as the `tools` allowlist because the allowlist is default-deny: only what is listed is available, everything else is blocked.(4) This matches the architecture's intent exactly and is more robust than a denylist (a denylist must enumerate every tool to block and silently admits any tool added to Claude Code later). The blocked tools therefore need no encoding — they are the complement of the allowlist, and are preserved in each file's **Constraints** section as documentation.

Sub-tool restrictions the allowlist cannot express (writes confined to the project; no `gh`; no git-state changes) are enforced by the centralized `PreToolUse` hook, per `architecture.md` §3 — not in frontmatter.

### Fields deliberately not used

PAF agents set none of the other supported frontmatter fields (`disallowedTools`, `permissionMode`, `maxTurns`, `color`, `isolation`, `mcpServers`, `effort`, etc.).(2) Reasons:

- `disallowedTools` — unnecessary; the `tools` allowlist already denies everything unlisted. (If both fields are set, `disallowedTools` is applied first, then `tools` resolves against the remainder.(4))
- `permissionMode`, `isolation`, `maxTurns`, `effort`, `color` — operational knobs orthogonal to an agent's definition; left at their defaults so behaviour stays predictable and controlled by the skill and the centralized hook.
- No per-agent hook *policy*: the `hooks` field only registers the one centralized `PreToolUse` script keyed on `agent_type` (`architecture.md` §3); no agent carries hook logic of its own.

---

## Body (system prompt)

The markdown body after the frontmatter becomes the agent's system prompt. A subagent receives **only this body plus basic environment details** — not the main Claude Code system prompt, and not `architecture.md`.(5) Project context arrives separately because the project instructions (`CLAUDE.md` or `AGENTS.md`) auto-load into every agent (`architecture.md` §6). Everything else the agent needs must be in this body.

Every PAF agent body has the same five sections, in this order:

1. **`## Role`** — one paragraph: what this agent is and the single responsibility it owns (from `architecture.md` §1).
2. **`## Input`** — what the caller passes in the invocation prompt, described by *what is received*, never by *who sends it* (a skill, or a developer invoking the agent directly). The agent does not fetch its own work; it is handed context.
3. **`## Task`** — the concrete steps the agent performs.
4. **`## Constraints`** — boundaries: the tool scope in plain language (the complement of the `tools` allowlist, plus any hook-enforced sub-tool limits), and the universal rules — agents never orchestrate other agents, never call `gh`, never change git state.
5. **`## Output`** — the output contract (below), reproduced as described below.

---

## Output contract

This is the **canonical copy** of the output contract. `skills/paf-shared/output-contract.md` holds the same schema with the rules a skill parses it by; the decisions behind it are in `architecture.md` §4. Because Claude Code does not expand `@path` imports inside an agent body — the body is delivered as a raw system prompt, verified empirically (an agent given `@file` syntax in its body sees the literal string, never the file's content)(5) — the contract block cannot be referenced from a shared file at runtime. Each agent file therefore reproduces the block below. The opening instruction sentence and the schema's fields and their ordering are copied exactly; the `agent:` value is set to that agent's own name (e.g. `agent: "issue-writer"`) instead of the `"<agent-name>"` placeholder; and an agent may add its own payload sentence after the opening sentence (e.g. "Your primary payload is …") and adapt the schema comments to its own output. If the contract ever changes, it changes here and in `skills/paf-shared/output-contract.md`, and the agent files are updated to match.

Every agent body's **`## Output`** section contains exactly this instruction and block (with `agent:` set to the file's own name):

> Your report must be **exactly one fenced ` ```yaml ` block** conforming to the schema below, closed by a ` ``` ` line as its very last line — no prose before or after it. Every field is always present; collections are `[]` when not applicable.
>
> ```yaml
> agent: "<agent-name>"            # required — all agents
> status: "success"               # required — one of: success | failure | needs_retry
> summary: |                       # required — all agents (block scalar)
>   one paragraph: what was done or what failed
> artifacts:                       # always present; [] when none
>   - path: "<relative file path>"
>     action: "created"           # one of: created | modified | deleted
> issues:                          # always present; [] when none
>   - severity: "error"           # one of: error | warning
>     message: "<description>"
>     location: "<file:line, or omitted if not applicable>"
> ```

Each agent's **Output** section names which field carries its primary payload, but always emits the full schema. `summary` carries the agent's primary **textual deliverable** — a short paragraph for most agents, the complete document for a synthesis agent; `artifacts` carries **files** only, so an agent with no write access reports its product in `summary`. Field usage by agent category (the reasons are in `architecture.md` §4, Field usage by agent category):

- **Builder** → `artifacts` is the primary payload; `issues` usually `[]`.
- **Review / validation** → `issues` is the primary payload; `artifacts` is `[]`. `status` is `success` on completion regardless of what was found. The one exception is a **final gate** review (a spec-conformance check that the skill treats as a STOP point): it sets `status: failure` when the work does not meet the criteria, and states this in its own Output section.
- **Synthesis** → the produced document is the `summary` payload; no write access, so `artifacts` is `[]`.
- **Verification** → `status` plus `issues` (the failures) are the primary payload.

---

## Sources

1. Subagents — Choose the subagent scope (recursive scan; identity is the `name` field). https://code.claude.com/docs/en/sub-agents#choose-the-subagent-scope
2. Subagents — Supported frontmatter fields (`name`, `description` required; `name` received by hooks as `agent_type`; full field list). https://code.claude.com/docs/en/sub-agents#supported-frontmatter-fields
3. Subagents — Choose a model (`haiku`/`sonnet`/`opus`/full ID/`inherit`). https://code.claude.com/docs/en/sub-agents#choose-a-model
4. Subagents — Control subagent capabilities (`tools` allowlist denies everything unlisted, including MCP). https://code.claude.com/docs/en/sub-agents#control-subagent-capabilities
5. Subagents — Write subagent files (the body is the system prompt; a subagent receives only this prompt plus environment details). https://code.claude.com/docs/en/sub-agents#write-subagent-files
