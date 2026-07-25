# CLAUDE.md content checklist

`CLAUDE.md` at the root of your project is the **single source of project context** for PAF. It is
loaded automatically into the main thread and into every agent, so PAF's skills read their
project-specific values from it and nowhere else — never from an operator's memory, another project,
or a prior session. If a value a step needs is missing, the skill **STOPs and asks you** rather than
inventing one.

This is a checklist of the **content areas** your `CLAUDE.md` must cover — not a format. Keep your
project's existing structure, headings, and voice; PAF reads meaning, not layout. Keep the file under
200 lines: project-specific context only, no skill logic, agent prompts, or hook scripts.

---

## Required content areas

### Project overview

What the project does, its stack, and its key entry points. Grounds every agent that reads the file.

### Branch strategy

The feature-branch naming convention. **It must embed the issue number** — that is how the factory
links a branch to its issue and attributes cost to the feature.

> Example: `feature/<issue-number>-<short-description>`

Used by `/paf:implement-issue` (creates the branch) and `/paf:check-out` (derives the issue number
back out of it).

### Base branch

The branch feature branches start from and that MRs/PRs target — `develop`, `main`, whatever your
project uses. Used by `/paf:implement-issue` and `/paf:check-out`.

### Labels and merge strategy

Any standard labels applied to issues and MRs/PRs, and how branches are merged (squash, merge
commit, rebase).

### Environment setup

How to get a working development environment — the container to start, the virtualenv to activate,
the dependencies to install, or an explicit statement that none is needed. Agents run commands in
whatever environment this describes, so if tests only pass inside docker, say so here.

### How to run tests

The **exact command**, not a description. Agents run it verbatim.

### Code standards / lint command

The **exact command** that checks code standards — linter, formatter check, type checker, syntax
gate. Run by `implementation-verifier` alongside the tests.

### Full pre-merge validation command

The **exact command** that runs the whole test + lint suite in one go — the safety net a scoped run
cannot see. `/paf:check-out` runs it once before opening the MR/PR and **STOPs the run if this is
not defined**, so this area is not optional.

A single script (e.g. `./scripts/pre-merge.sh`) is recommended over a chain of commands: it is one
value to keep current, and it stays correct as the suite grows.

---

## One possible format

The layout below is **an illustration, not a requirement** — any structure that covers the areas
above works just as well.

```markdown
## Project overview

Django web application serving [domain]. Entry points: manage.py (CLI), [app]/urls.py (routing).
Primary stack: Django [version], PostgreSQL, deployed via AWS CDK.

## Project conventions

- **Feature branches:** `feature/<issue-number>-<short-description>`
- **Base branch (MR/PR target):** `develop`
- **Labels:** enhancement, bug, documentation
- **Merge strategy:** squash merge

## Local development

# Environment
docker compose up -d

# Run tests
docker compose exec web pytest

# Code standards
docker compose exec web ruff check .

# Full pre-merge validation
./scripts/pre-merge.sh
```
