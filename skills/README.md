# skills/

Skill files for PAF. Each skill is a directory containing a `SKILL.md` entrypoint. Skills are orchestrators — they sequence agent invocations, enforce human interception points, and handle external I/O (GitHub API, cost reporting).

## What belongs here

One directory per skill, plus a shared `_shared/` directory (no `SKILL.md`) for cross-skill helpers. Each skill's command comes from its frontmatter `name`, which PAF sets to a `paf:`-prefixed value (e.g. `name: "paf:create-issue"` → `/paf:create-issue`).

## File naming and structure

```
skills/
└── <skill-name>/
    └── SKILL.md        # Required — main instructions and orchestration logic
```

Skill names are lowercase, hyphenated. Examples: `create-issue`, `implement-issue`, `check-out`.

## Install target

The installer places each skill **flat** at `~/.claude/skills/<skill-name>/`, and `_shared/` at `~/.claude/skills/_shared/`. Personal skills are discovered only by a top-level directory under `~/.claude/skills/` — a `paf/` subfolder is not discovered — so the `paf:` prefix comes from each skill's frontmatter `name`, not the path.

## Skills in this factory

| Skill | Command | Purpose |
|-------|---------|---------|
| `create-issue` | `/paf:create-issue` | Produce a structured GitHub issue from a feature idea |
| `implement-issue` | `/paf:implement-issue` | Plan and implement a feature from an approved issue |
| `check-out` | `/paf:check-out` | Review, fix, and post a PR for completed work |
