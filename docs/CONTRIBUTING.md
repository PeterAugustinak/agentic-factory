# Contributing to PAF

## Adding a skill

1. Create a directory under `skills/`: `skills/<skill-name>/`
2. Add `skills/<skill-name>/SKILL.md` following `docs/authoring/skill-definition-format.md`
3. Required frontmatter: `description` (what + when), and `disable-model-invocation: true` — factory skills are explicit-invocation only. Never set `context: fork` (a forked skill runs as a subagent and cannot orchestrate agents).
4. Skills are orchestrators — they invoke agents, enforce human gates, handle VCS I/O, and report cost. No cognitive work in skill files.
5. Document the new skill in `skills/README.md`, and add its human-facing explanation (diagram, flow) in `docs/skills/<skill-name>.md`

Invoke after install: `/skill-name`

## Adding an agent

1. Create `agents/<agent-name>.md`
2. Required frontmatter fields: `name`, `description`, `model`, `tools`
3. Write a focused system prompt: role, expected input, required output (must follow the output contract in `docs/architecture.md` Section 4)
4. Agents are specialists — no orchestration, no external I/O, no VCS API calls
5. Document the new agent in `docs/architecture.md` and update `agents/README.md` if needed

## Adding a hook

1. Create `hooks/<EventName>-<purpose>.{sh,py}` with an appropriate shebang
2. Make it executable: `chmod +x hooks/<EventName>-<purpose>.{sh,py}`
3. The script receives the hook payload as **JSON on stdin** (`tool_name`, `tool_input`, `agent_type`, `cwd`, ...) and `CLAUDE_PROJECT_DIR` in its environment. To block a `PreToolUse` call, print a `permissionDecision: "deny"` object (`hookSpecificOutput`) on stdout, or exit 2. See the Claude Code hook documentation.
4. Update `docs/architecture.md` §3 if the hook changes a tool access scope, and document the hook in `hooks/README.md`

## PR process

- Branch from `develop`: `git checkout -b feature/<issue-number>-<short-description>`
- PR targets `develop`
- Merge to `master` via a release PR from `develop`

## Versioning and the changelog

Bumping `VERSION` and writing the `CHANGELOG.md` entry is a **manual, per-PR discipline**. It is
deliberately not automated inside `check-out`: that skill is project-agnostic, whereas this
versioning scheme is PAF-specific, so building it in would break `check-out` on every other project.

While PAF is pre-1.0, **every PR carries its own version**: bump `VERSION` per the rules in the
[README](../README.md) and add a dated `## [x.y.z] - YYYY-MM-DD` section to `CHANGELOG.md`
describing the change.

From `1.0.0` onward this switches to **one version per release**: feature PRs into `develop` add
their entries under `## [Unreleased]`, and the release PR from `develop` to `master` bumps `VERSION`
and converts that section into a dated one — so several PRs share a version.
