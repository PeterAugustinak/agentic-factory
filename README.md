# PAF - personal agentic factory

Personal Agentic Factory (PAF) — a structured, installable development framework for my personal projects. It replaces ad-hoc prompting with a repeatable pipeline of specialized agents and skills that takes a feature idea from a GitHub issue to a reviewed, merged PR.

## How it works

A set of skills orchestrate specialized agents through a structured development pipeline — from discussing a feature idea, through planning and implementation, to a reviewed and posted PR. Human interception points are enforced at every critical transition; the developer approves before work begins, before execution starts, and before the PR is posted.

The factory accelerates and structures the work; it does not replace human judgement.

## Getting started

Install PAF on any machine with a single command:

```bash
curl -sSL <install-url> | bash
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
