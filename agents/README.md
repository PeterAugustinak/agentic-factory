# agents/

Agent definition files for PAF. Each file defines one specialist agent: its model, allowed tools, and system prompt.

## What belongs here

One `.md` file per agent, containing YAML frontmatter and a system prompt. Agents are specialists — they own cognitive work (synthesis, building, review, verification) but do not orchestrate other agents.

## File naming

`<agent-name>.md` — lowercase, hyphenated. Examples: `issue-writer.md`, `full-stack-dev.md`.

The agent's identity is determined by its `name` frontmatter field, not the filename — keep them consistent.

## Install target

The installer places agent files at `~/.claude/agents/paf/`.

## Agents in this factory

The `.md` files in this directory are the current set — each one is self-describing (model, tool
scope, role). `docs/architecture.md` §1 records the decisions on how an agent is *shaped* (model selection,
categories) and deliberately keeps no roster; how to write one, output contract included, is in
`docs/authoring/agent-definition-format.md`.

One agent is advisory: `convention-suggester` only suggests rules for the project instructions, so a
caller continues when it fails or returns malformed output (`docs/architecture.md` §5, Malformed-contract
escalation).

`issue-writer` and `issue-validator` never settle an open choice. A crucial one — it changes the Goal or
the acceptance criteria (in an issue without them, the outcomes its body states) — is reported for the developer (`Undecided:` / `Uncovered:`); any other is left
for `/paf:implement-issue` to settle in plan mode (`### Open decisions` in the issue / an `Open decision:`
warning).
