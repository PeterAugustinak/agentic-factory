# skills/

Skill files for PAF. Each skill is a directory containing a `SKILL.md` entrypoint. Skills are orchestrators — they sequence agent invocations, enforce human interception points, and handle external I/O (GitHub API, cost reporting).

## What belongs here

One directory per skill. The directory name becomes the slash command (e.g. `skills/create-issue/` → `/create-issue`).

## File naming and structure

```
skills/
└── <skill-name>/
    └── SKILL.md        # Required — main instructions and orchestration logic
```

Skill names are lowercase, hyphenated. Examples: `create-issue`, `implement-issue`, `check-out`.

## Install target

The installer places skill directories at `~/.claude/skills/paf/<skill-name>/`.

## Skills in this factory

| Skill | Command | Purpose |
|-------|---------|---------|
| `create-issue` | `/create-issue` | Produce a structured GitHub issue from a feature idea |
| `implement-issue` | `/implement-issue` | Plan and implement a feature from an approved issue |
| `check-out` | `/check-out` | Review, fix, and post a PR for completed work |
