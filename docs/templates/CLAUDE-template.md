# CLAUDE.md template

Copy this file to `CLAUDE.md` at the root of any project adopting PAF. Fill in the placeholder values. Keep this file under 200 lines.

---

# CLAUDE.md

## Project overview

<!-- One paragraph: what this project does, its stack, and key entry points. -->
<!-- Example: "Django web application serving [domain]. Entry points: manage.py (CLI), [app]/urls.py (routing). Primary stack: Django [version], PostgreSQL, deployed via AWS CDK." -->

## Factory skills

PAF provides three core slash commands. Full skill documentation lives in the factory repo — do not duplicate it here.

| Command | When to use |
|---------|-------------|
| `/create-issue` | Starting a new feature — discuss the idea and produce a structured GitHub issue |
| `/implement-issue` | Beginning implementation — validate, plan, implement, and verify against an approved issue |
| `/check-out` | Finishing work — review, fix, and post a PR for completed, developer-validated work |

## Project conventions

- **GitHub repo:** `<owner>/<repo>`
- **Default branch:** `master`
- **Feature branches:** `feature/<issue-number>-<short-description>` (the issue number links the branch to its issue and lets the factory attribute cost to the feature)
- **PR target:** `develop`
- **Labels:** <!-- list any standard labels used on issues/PRs -->
- **Merge strategy:** squash merge

## Local development

<!-- Exact commands — not descriptions. Agents run these verbatim. -->

```bash
# Install dependencies
<command>

# Run tests
<command>

# Run linter
<command>

# Apply migrations (if applicable)
<command>
```

## Out of scope for CLAUDE.md

Detailed skill logic, agent prompts, and hook scripts live in the factory repo and are not duplicated here. This file stays under 200 lines and contains only project-specific context.
