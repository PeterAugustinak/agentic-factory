# CLAUDE.md — agentic-factory

Guidance for agents (and humans) working **on** the factory itself. This file must stay under 300 lines.

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
│   └── CLAUDE-template.md    # CLAUDE.md template for projects adopting PAF
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
