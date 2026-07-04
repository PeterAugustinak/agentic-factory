# CLAUDE.md — agentic-factory

Guidance for agents (and humans) working **on** the factory itself. This file must stay under 300 lines.

## No guessing — verify everything

Contributing to this project — implementing the current issues or any future enhancement — **must not rely on guesses**. Every architecture decision and implementation choice MUST be verified against an actual source:

- Prefer official **Anthropic / Claude Code documentation** (code.claude.com/docs, docs.anthropic.com).
- Otherwise, a current **industry standard or established best practice**, cited explicitly.

If something is genuinely undocumented, say so and verify it empirically before deciding — never present a guess as a recommendation. Decisions captured in issues and in `docs/architecture.md` carry their source so they stay auditable; keep it that way.

## Repository layout

```
agentic-factory/
├── agents/         # Agent definition files (.md), one per agent
├── skills/         # Skill directories, one per skill (skills/<name>/SKILL.md)
├── hooks/          # Hook shell scripts (PreToolUse, PostToolUse, etc.)
├── scripts/        # Installer and utility scripts (not installed)
├── docs/
│   ├── architecture.md       # Single source of truth for all design decisions
│   ├── CONTRIBUTING.md       # How to add skills, agents, and hooks
│   ├── authoring/            # How to author a component (agent/skill definition formats)
│   ├── skills/               # Per-skill documentation (diagram + how it works)
│   └── templates/            # CLAUDE-template.md — CLAUDE.md template for adopting projects
├── CLAUDE.md       # This file
└── README.md       # Project overview and install command
```

## Quick reference

**Adding a skill:** `skills/<name>/SKILL.md` — orchestrator only, explicit invocation, must report cost. See `docs/CONTRIBUTING.md`.

**Adding an agent:** `agents/<name>.md` — specialist only, no orchestration. Output must follow the contract in `docs/architecture.md` Section 4. See `docs/CONTRIBUTING.md`.

**Adding a hook:** `hooks/<EventName>-<purpose>.sh` — must be executable. Update `docs/architecture.md` Section 3 if tool scope changes. See `docs/CONTRIBUTING.md`.

## Key constraints

- Skills are explicit-invocation only — no auto-trigger phrase matching
- Agents never orchestrate other agents — skills own sequencing
- `docs/architecture.md` is the single source of truth — do not re-decide what it already decided
- This file must stay under 300 lines
