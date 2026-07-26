# PAF - personal agentic factory

Personal Agentic Factory (PAF) — a structured, installable, skill-driven AI development framework. It replaces ad-hoc prompting with a repeatable pipeline of specialized agents and skills that takes a feature idea from an issue to a reviewed, merged MR/PR.

## How it works

A set of skills orchestrate specialized agents through a structured development pipeline — from discussing a feature idea, through planning and implementation, to a reviewed and posted MR/PR. Human interception points are enforced at every critical transition; the developer approves before work begins, before execution starts, and before the MR/PR is posted.

The factory accelerates and structures the work; it does not replace human judgement.

## Getting started

Install PAF on any machine with a single command — no cloning required:

```bash
curl -sSL https://raw.githubusercontent.com/PeterAugustinak/agentic-factory/develop/scripts/install.sh | bash
```

This installs the skills, agents, and hook into your Claude Code config (`~/.claude/`) and wires the hook into `settings.json`. Re-running upgrades in place. Requires `git` and `python3` to install, plus an authenticated `gh` (GitHub) or `glab` (GitLab) CLI — whichever matches the target project's `origin` remote — to run the skills. After install, start a new Claude Code session and invoke:

- `/paf:create-issue` — turn a discussed idea into a structured issue
- `/paf:implement-issue` — validate, plan, implement, verify, and review against an approved issue
- `/paf:check-out` — confirm, validate, and open an MR/PR for completed work

To remove PAF (skills, agents, hook, and the hook entry in `settings.json` — nothing else):

```bash
curl -sSL https://raw.githubusercontent.com/PeterAugustinak/agentic-factory/develop/scripts/uninstall.sh | bash
```

## Versioning

PAF carries a semantic version in the `VERSION` file at the repo root, and every change is
recorded in [CHANGELOG.md](CHANGELOG.md).

| Bump | When |
|------|------|
| PATCH | Bug fix |
| MINOR | Backward-compatible feature or enhancement |
| MAJOR | Breaking change — an install-layout or skill-interface change requiring re-configuration |

PAF is pre-1.0: the interface is not yet stable, and `1.0.0` will mark the first release that
declares it so. The bump rules above apply from now on regardless, which is a deliberate choice —
[semver](https://semver.org) leaves `0.y.z` unconstrained.

The installer records the installed version and reports whether a run was a new installation, an
upgrade, or a reinstall. To check what you have installed at any time:

```bash
cat ~/.claude/paf/VERSION
```

## Repository layout

| Directory | Contents |
|-----------|----------|
| `agents/` | Agent definition files (one per agent) |
| `skills/` | Skill files (one directory per skill) |
| `hooks/` | Hook scripts for tool-restriction enforcement |
| `scripts/` | Installer and utility scripts |
| `docs/` | Architecture, contributing guidelines, and project templates |

See [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) for how to add skills, agents, and hooks.
