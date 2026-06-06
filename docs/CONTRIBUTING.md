# Contributing to PAF

## Adding a skill

1. Create a directory under `skills/`: `skills/<skill-name>/`
2. Add `skills/<skill-name>/SKILL.md` with YAML frontmatter and orchestration instructions
3. Required frontmatter fields: `description` (when to invoke), `invocation: explicit` (factory skills are always explicit-invocation only)
4. Skills are orchestrators — they invoke agents, enforce human gates, handle GitHub I/O, and report cost. No cognitive work in skill files.
5. Document the new skill in `skills/README.md`

Invoke after install: `/skill-name`

## Adding an agent

1. Create `agents/<agent-name>.md`
2. Required frontmatter fields: `name`, `description`, `model`, `tools`
3. Write a focused system prompt: role, expected input, required output (must follow the output contract in `docs/architecture.md` Section 4)
4. Agents are specialists — no orchestration, no external I/O, no GitHub API calls
5. Document the new agent in `docs/architecture.md` and update `agents/README.md` if needed

## Adding a hook

1. Create `hooks/<EventName>-<purpose>.sh`
2. Make it executable: `chmod +x hooks/<EventName>-<purpose>.sh`
3. The script receives tool call context via environment variables — see Claude Code hook documentation
4. Update `docs/architecture.md` Section 3 if the hook changes a tool access scope

## PR process

- Branch from `develop`: `git checkout -b feature/<short-description>`
- PR targets `develop`
- Merge to `master` via a release PR from `develop`
