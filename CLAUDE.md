# CLAUDE.md — agentic-factory

Guidance for agents (and humans) working **on** the factory itself. This file must stay under 200 lines.

## Project overview

PAF (Personal Agentic Factory) is a set of Claude Code skills, agents, and hooks that take a feature
from idea to merge request. It is not an application — it is installed into a user's `~/.claude`
config by `scripts/install.sh`. Entry points: the three skills in `skills/` (`/paf:create-issue`,
`/paf:implement-issue`, `/paf:check-out`), the specialist agents in `agents/`, and the single
`PreToolUse` hook in `hooks/`.

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
├── hooks/          # Hook scripts (PreToolUse enforcement, etc.)
├── scripts/        # Installer and utility scripts (not installed)
│   ├── install.sh            # Installer — copies PAF into ~/.claude
│   ├── uninstall.sh          # Removes an installed PAF
│   └── pre-merge.sh          # Full pre-merge validation gate
├── tests/          # Stdlib unittest suite for the deterministic scripts (not installed)
├── docs/
│   ├── architecture.md       # Single source of truth for all design decisions
│   ├── CONTRIBUTING.md       # How to add skills, agents, and hooks
│   ├── authoring/            # How to author a component (agent/skill definition formats)
│   ├── skills/               # Per-skill documentation (diagram + how it works)
│   └── templates/            # CLAUDE-template.md — CLAUDE.md content checklist for adopting projects
├── CLAUDE.md       # This file
└── README.md       # Project overview and install command
```

## Quick reference

**Adding a skill:** `skills/<name>/SKILL.md` — orchestrator only, explicit invocation, must report cost. See `docs/CONTRIBUTING.md`.

**Adding an agent:** `agents/<name>.md` — specialist only, no orchestration. Output must follow the contract in `docs/architecture.md` Section 4. See `docs/CONTRIBUTING.md`.

**Adding a hook:** `hooks/<EventName>-<purpose>.sh` — must be executable. Update `docs/architecture.md` Section 3 if tool scope changes. See `docs/CONTRIBUTING.md`.

## Project conventions

- **Feature branches:** `feature/<issue-number>-<short-description>` (the issue number links the branch to its issue and lets the factory attribute cost to the feature)
- **Base branch (MR/PR target):** `develop`
- **Labels:** `enhancement`, `bug`, `documentation`
- **Merge strategy:** squash merge

## Local development

**Environment:** none to set up. PAF runs on the **Python 3 and Bash standard libraries only** — zero
third-party dependencies is a hard principle, so there is nothing to install and no virtualenv or
container to enter. `git` and the `gh` CLI are needed for VCS operations.

```bash
# Run tests (from the repository root)
python3 -m unittest

# Code standards — syntax gate (no third-party linter by design)
python3 -m py_compile <file.py>
bash -n <file.sh>

# Full pre-merge validation (whole syntax + test suite; run once by /paf:check-out before opening the PR)
./scripts/pre-merge.sh
```

## Key constraints

- Skills are explicit-invocation only — no auto-trigger phrase matching
- Agents never orchestrate other agents — skills own sequencing
- `docs/architecture.md` is the single source of truth — do not re-decide what it already decided
- Zero third-party dependencies — Python 3 / Bash standard library only
- This file must stay under 200 lines
