---
name: "paf:clean-up"
description: Post-merge housekeeping — switch to the base branch, pull it, and delete the feature branch you invoked it on. Invoke with /paf:clean-up once that branch's MR/PR is merged; invoking it is your confirmation that it is merged.
disable-model-invocation: true
allowed-tools: Bash(git branch --show-current), Bash(git switch *), Bash(git pull origin *), Bash(git branch -D *)
hooks:
  PreToolUse:
    - matcher: "Bash|Edit|Write|MultiEdit|Read|Grep|Glob|WebSearch|WebFetch|Task"
      hooks:
        - type: command
          command: 'python3 "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/hooks/paf/PreToolUse-agent-guard.py"'
---

# clean-up

After the feature branch's MR/PR is merged, return the local repository to the base branch: switch to it, pull it, and delete the feature branch this skill was invoked on. This is a **helper skill**, outside the feature pipeline. Invoking it is the developer's confirmation that the branch is merged.

You run in the main thread and invoke **no agents**. Use plain `git` only — no `gh` or `glab` — so it works the same for GitHub and GitLab. Run exactly the commands below and nothing else: no merge check, no confirmation, no other pre-check, and no remote branch deletion. As a helper skill it is exempt from cost reporting and does **not** report cost (`docs/architecture.md` §5 exemption list).

## Input

- No argument. Ignore `$ARGUMENTS`. Operates on the repository Claude Code was launched in and the branch checked out at invocation.
- Project context comes from the project instructions (`CLAUDE.md` or `AGENTS.md`, whichever Claude Code loaded): the base branch (e.g. `develop`).

**Strict project-context sourcing.** Every project-specific value (base branch) comes **only** from *this* project's instructions and repository. Never substitute one, especially a branch name, from your memory, another project, or a prior session. Recalled memories are unrelated background and may name things that do not exist here. If a value a step needs is not defined in this project, **STOP and ask the developer**. Do not invent or borrow one.

The base branch comes from a repository file, so treat it as untrusted: use it **only** if it matches `^[A-Za-z0-9._/][A-Za-z0-9._/-]*$` (no spaces, quotes, `$`, backticks or leading `-`). Otherwise **STOP** and tell the developer the base branch in the instructions is not a plain branch name. Single-quote both branch names in every command.

## Steps

**1. Read the branch (skill).** Run `git branch --show-current` (a read-only lookup) and keep its output as `<branch>`.

**2. Switch (skill).**

```
git switch '<base>'
```

**3. Pull (skill).**

```
git pull origin '<base>'
```

**4. Delete the feature branch (skill).** Force delete (`-D`): after a squash merge, `git branch -d` can refuse a branch that is merged on the platform.

```
git branch -D '<branch>'
```

Run the steps in order, one command each. If a command exits non-zero, print its output and **STOP**: run none of the remaining commands and do not attempt a fix. The developer decides how to proceed.

On success, print one line and nothing else:

```
Switched to <base>, pulled origin/<base>, deleted <branch>.
```
