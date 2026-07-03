# PAF Agent Definition Format

This document defines the authoring format every PAF agent file follows. It operationalizes [`architecture.md`](architecture.md): the architecture decides *what* each agent is (model, tool scope, role, output contract); this document fixes *how* that is written into a file so all ten agents read identically.

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
| `name` | Yes | The agent name, matching `architecture.md` §1 (e.g. `code-explorer`). Received by hooks as `agent_type`.(2) |
| `description` | Yes | One sentence stating what the agent does. PAF agents are invoked **explicitly by name** from skills, so this is documentation, not an auto-delegation trigger. |
| `model` | No (defaults to `inherit`) | The alias from `architecture.md` §1: `haiku` or `sonnet`. Aliases are used, not full model IDs, so the factory tracks model upgrades automatically.(3) |
| `tools` | No (inherits all if omitted) | The **allowlist** from `architecture.md` §3, comma-separated. Only listed tools are available; every other tool — including all MCP tools — is denied.(4) |

### Why the allowlist (`tools`) form, not the denylist

`architecture.md` §3 gives each agent an "Allowed" and a "Blocked" column. PAF encodes the **Allowed** column as the `tools` allowlist because the allowlist is default-deny: only what is listed is available, everything else is blocked.(4) This matches the architecture's intent exactly and is more robust than a denylist (a denylist must enumerate every tool to block and silently admits any tool added to Claude Code later). The "Blocked" column therefore needs no encoding — it is the complement of the allowlist, and is preserved in each file's **Constraints** section as documentation.

Sub-tool restrictions the allowlist cannot express (read-only Bash; writes confined to the project; no `gh`) are enforced by the centralized `PreToolUse` hook, per `architecture.md` §3 — not in frontmatter.

### Fields deliberately not used

PAF agents set none of the other supported frontmatter fields (`disallowedTools`, `permissionMode`, `maxTurns`, `color`, `isolation`, `mcpServers`, `hooks`, `effort`, etc.).(2) Reasons:

- `disallowedTools` — unnecessary; the `tools` allowlist already denies everything unlisted.
- `permissionMode`, `isolation`, `maxTurns`, `effort`, `color` — operational knobs orthogonal to an agent's definition; left at their defaults so behaviour stays predictable and controlled by the skill and the global hook.
- `hooks` (per-agent) — PAF uses a single global `PreToolUse` hook keyed on `agent_type` (`architecture.md` §3), not per-agent hooks.

---

## Body (system prompt)

The markdown body after the frontmatter becomes the agent's system prompt. A subagent receives **only this body plus basic environment details** — not the main Claude Code system prompt, and not `architecture.md`.(5) Project context arrives separately because `CLAUDE.md` auto-loads into every agent (`architecture.md` §6). Everything else the agent needs must be in this body.

Every PAF agent body has the same five sections, in this order:

1. **`## Role`** — one paragraph: what this agent is and the single responsibility it owns (from `architecture.md` §1).
2. **`## Input`** — what the caller passes in the invocation prompt, described by *what is received*, never by *who sends it* (a skill, or a developer invoking the agent directly). The agent does not fetch its own work; it is handed context.
3. **`## Task`** — the concrete steps the agent performs.
4. **`## Constraints`** — boundaries: the tool scope in plain language (mirroring the "Blocked" column and any hook-enforced sub-tool limits), and the universal rules — agents never orchestrate other agents, never call `gh`, never change git state.
5. **`## Output`** — the output contract (below), reproduced with only the `agent:` value substituted (see below).

---

## Output contract

This is the **canonical copy** of the output contract. It is identical to `architecture.md` §4. Because Claude Code does not expand `@path` imports inside an agent body — the body is delivered as a raw system prompt, verified empirically (an agent given `@file` syntax in its body sees the literal string, never the file's content)(5) — the contract block cannot be referenced from a shared file at runtime. Each agent file therefore reproduces the block below, with a **single per-file substitution**: the `agent:` value is set to that agent's own name (e.g. `agent: "code-explorer"`) instead of the `"<agent-name>"` placeholder. Everything else — every other field, comment, ordering, and the surrounding instruction — is copied exactly. If the contract ever changes, it changes here and in `architecture.md` §4, and the agent files are updated to match.

Every agent body's **`## Output`** section contains exactly this instruction and block (with `agent:` set to the file's own name):

> Your final message must be **exactly one fenced ` ```yaml ` block** conforming to the schema below — no prose before or after it. Every field is always present; collections are `[]` when not applicable.
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

Field usage differs by agent category (`architecture.md` §4): builders populate `artifacts`; reviewers populate `issues`; analysis agents populate `summary`. Each agent's **Output** section names which field carries its primary payload, but always emits the full schema.

---

## Sources

1. Subagents — Choose the subagent scope (recursive scan; identity is the `name` field). https://code.claude.com/docs/en/sub-agents#choose-the-subagent-scope
2. Subagents — Supported frontmatter fields (`name`, `description` required; `name` received by hooks as `agent_type`; full field list). https://code.claude.com/docs/en/sub-agents#supported-frontmatter-fields
3. Subagents — Choose a model (`haiku`/`sonnet`/`opus`/full ID/`inherit`). https://code.claude.com/docs/en/sub-agents#choose-a-model
4. Subagents — Control subagent capabilities (`tools` allowlist denies everything unlisted, including MCP). https://code.claude.com/docs/en/sub-agents#control-subagent-capabilities
5. Subagents — Write subagent files (the body is the system prompt; a subagent receives only this prompt plus environment details). https://code.claude.com/docs/en/sub-agents#write-subagent-files
