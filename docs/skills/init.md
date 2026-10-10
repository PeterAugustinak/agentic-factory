# init

Human-facing documentation for the `init` skill. The operational definition is [`skills/paf-init/SKILL.md`](../../skills/paf-init/SKILL.md). This file explains how the skill works and is not loaded by Claude at run time.

## Purpose

Make PAF work in the current repository. `init` checks the environment PAF needs and the content of the project instructions file. With the developer's agreement, it fixes the file. It runs **before** the main skills, the first time PAF is used in a repository, much like Claude Code's own `/init`. It is not part of the feature pipeline.

It is **idempotent**. On a ready repository it prints `PAF ready` and changes nothing, so it also works as a health check at any time.

## When and how to invoke

Launch Claude Code from the repository's git root, then run:

```
/paf:init
```

It takes no argument. The installer ends with the same hint: *"Using PAF in a repo for the first time? Run /paf:init there first."*

## How it works

`init` runs entirely in the main thread and invokes **no agents** (see [`architecture.md` §2](../architecture.md#main-thread-readiness-check-init) for why).

1. **Environment check.** [`paf-readiness.py`](../../skills/paf-shared/paf-readiness.py) runs every deterministic check in one call:
   - inside a git repository;
   - the `origin` host is exactly `github.com` or `gitlab.com`, and the matching `gh`/`glab` is installed and authenticated. Both come from `paf-vcs provider` / `paf-vcs auth-status`, so the rule is the same one every skill uses;
   - `python3` is on PATH;
   - Claude Code is v2.1.277 or later, the version that reads `AGENTS.md` natively. Below v2.1.281 it warns that Amazon Bedrock and telemetry-disabled sessions read `CLAUDE.md` only;
   - the base branch named in the instructions exists, locally or on `origin`. The name comes from a repository file, so the skill passes it single-quoted and only if it is a plain branch name (letters, digits, `.`, `_`, `/`, `-`, no leading `-`); the script rejects anything else with a usage error;
   - Claude Code was launched from the git root;
   - which project instructions files Claude Code loads, and whether an `AGENTS.md` is hidden.
2. **Instructions check.** The skill reads the loaded files, any hidden `AGENTS.md` (it holds the project's real instructions, so its gaps are fixed there), and the content checklist ([`project-instructions-template.md`](../../skills/paf-init/project-instructions-template.md)). It follows `@path` imports only when they resolve inside the git root (anything else needs the developer's confirmation). It compares them **by meaning, not text**. For every required area that is missing or unusable (for example a test command described in words, or no base branch), it reports the exact text to add.
3. **Report.** Everything ok → `PAF ready`, and nothing is written. Otherwise `PAF not ready`, with every finding and its exact fix. Environment problems the skill cannot fix get a clear remedy (install or authenticate the CLI, move to a supported host, upgrade Claude Code, restart from the git root). The instructions check still runs. A `skip` or a `warn` is only a note and never blocks readiness. When an `AGENTS.md` exists but nothing loads it (the `claude-md` setting, or an old Claude Code), the fix is a `CLAUDE.md` containing `@AGENTS.md`, not a second `AGENTS.md`.
4. **Fix gate.** If the instructions file has findings, one question: **fix the main instructions file**, **add a local `CLAUDE.local.md`**, or **don't fix**. A fourth option, **delete `CLAUDE.md`**, is offered only for a hidden `AGENTS.md` whose sole hider is a root `CLAUDE.md` that holds nothing but a pointer to `AGENTS.md`, and only on Claude Code v2.1.281 or later; older versions can fail to read `AGENTS.md` directly ([memory docs](https://code.claude.com/docs/en/memory#agents-md)). Every fix option applies all content findings. The skill reports findings without announcing a fix before you choose.
5. **Fill values.** Values the repository shows (base branch, test/lint/pre-merge commands, labels) are detected. The skill asks only for the rest and never invents one.
6. **Write.**
   - Main file: missing items are folded into the file's existing sections. A new section is created only where none fits.
   - Local option: `CLAUDE.local.md` starts with `@AGENTS.md` when the project uses `AGENTS.md`, and is added to `.gitignore`.
   - No file at all: a new `AGENTS.md` following the checklist's format.
   - Hidden `AGENTS.md`: an `@AGENTS.md` line in `CLAUDE.md`, or, with the delete option, `CLAUDE.md` removed (`rm`, never `git rm`).
   - Before any write the skill checks the target is not a symlink leaving the git root. `Write`/`Edit` are deliberately not pre-approved in `allowed-tools`: their permission prompt is a second gate after the fix gate.
7. **Show.** The diff is printed and the check re-runs, with `--base` taken from the file just written. Nothing is committed. Restart Claude Code so the new instructions load.

`init` does not report cost. It is on the exemption list in [`architecture.md` §5](../architecture.md#cost-reporting), because it has no issue to attribute cost to.

## Which instructions file loads

This follows [the Claude Code memory docs](https://code.claude.com/docs/en/memory#agents-md):
- Under the default **Project instructions** value, a `CLAUDE.md`, `.claude/CLAUDE.md` or `CLAUDE.local.md` in the launch directory **or any directory above it** hides `AGENTS.md`. The user memory (`~/.claude/CLAUDE.md`, or `$CLAUDE_CONFIG_DIR/CLAUDE.md`) does not.
- An `@AGENTS.md` import (followed up to four hops, trailing punctuation ignored), or a `CLAUDE.md` symlinked to `AGENTS.md`, includes it again.
- Only an `AGENTS.md` at or below the git root counts as hidden. One in a parent directory is reported as a note.
- The setting itself is read from `pluginConfigs` in `~/.claude/settings.json` (`$CLAUDE_CONFIG_DIR` if set). A `--settings` file or managed settings can also set it, and the script cannot see those.

The launch directory is read from the Claude Code process (`$CLAUDE_PID`), because the Bash tool's working directory can drift during a session. This was verified empirically, not taken from the docs. When it cannot be read, the check falls back to the current directory and says so.

## Orchestration

```text
/paf:init
     |
     v
+----------------------------------------------+
| [skill] paf-readiness.py: environment checks |
|         + which instructions files load      |
+----------------------------------------------+
     |
     v
+----------------------------------------------+
| [skill] compare loaded file(s) with the      |
|         content checklist, by meaning        |
+----------------------------------------------+
     |
     v
  all ok? --yes--> print "PAF ready" (nothing written)
     | no
     v
  print "PAF not ready" + findings with exact fixes
     |
  instructions findings? --no--> stop
     | yes
     v
+----------------------------------------------+
| [human gate] fix main / local CLAUDE.local.md|
|   / delete CLAUDE.md (pointer-only, hidden   |
|   AGENTS.md) / don't fix                     |
+----------------------------------------------+
     | fix or delete             | don't fix -> stop
     v
  [skill] detect values; ask only undetectable ones
     |
     v
  [skill] write, print diff, re-run check (no commit)
```

## Related files

- [`skills/paf-init/SKILL.md`](../../skills/paf-init/SKILL.md): the skill.
- [`skills/paf-init/project-instructions-template.md`](../../skills/paf-init/project-instructions-template.md): the content checklist.
- [`skills/paf-shared/paf-readiness.py`](../../skills/paf-shared/paf-readiness.py): the environment check.
- [`skills/paf-shared/paf-vcs`](../../skills/paf-shared/paf-vcs): host and CLI rules.
