# hooks/

Hook scripts executed by the Claude Code harness. Hooks are the **enforcement** layer of PAF's tool-access model (`docs/architecture.md` §3, layer 3) — real, harness-level restrictions, not advisory prompts.

## What belongs here

Executable scripts named after the hook event they handle. A script may be a shell script or a Python script (whatever expresses the logic most robustly); it must be executable (`chmod +x`) and carry an appropriate shebang.

## File naming

`<EventName>-<purpose>.{sh,py}` — PascalCase event name matching a Claude Code hook event, hyphenated purpose. Example: `PreToolUse-agent-guard.py`.

Supported hook events: `PreToolUse`, `PostToolUse`, `Stop`, `SubagentStop`, `Notification`, `SubagentStart`.

## The factory hook

**`PreToolUse-agent-guard.py`** — the single, centralized `PreToolUse` hook, keyed on the payload's `agent_type` field (`docs/architecture.md` §3). It enforces the sub-tool restrictions that frontmatter allowlists cannot express:

- **Main thread** (no `agent_type`) → unrestricted (the orchestrating skill).
- **Agents that are not PAF's** (an `agent_type` not in the script's `PAF_AGENTS` set — Claude Code's built-ins, the user's own) → no decision; the normal permission flow applies, as if PAF were not installed.
- **All PAF agents** → no external I/O (`gh`/network) and no git state changes — both skill-owned, and the git pattern skips git's global options so `git -C <dir> commit` is caught too.
- **`code-explorer`, `implementation-planner`** → read-only Bash only (default-deny allowlist, applied to every segment of a compound command, plus denials for output redirection and commands' own write flags such as `find -delete` and `tree -o`).
- **Any agent with Edit/Write** → writes confined to the project root (`CLAUDE_PROJECT_DIR`).
- **Any agent's Read/Grep/Glob** → allowed inside the project root and the session's own saved tool results, plus an agent `Read` (only `Read`) of PAF's review input folder, `~/.claude/paf/review-input/`, where the code reviewers' shared input file lives; anything reaching outside them gets an `ask` decision, a human permission prompt that auto mode's classifier cannot approve silently.

It reads the hook payload as JSON on stdin and prints a `permissionDecision` object (`hookSpecificOutput`) on stdout — `allow` for a vetted call (no prompt), `deny` to block, `ask` to force a prompt — or exits 0 with no output so the normal permission flow proceeds for anything it does not recognize.

## Registration

The hook is **not** in `settings.json`, which would run it in every session of every project. The frontmatter `hooks` field of each PAF skill (`skills/paf-*/SKILL.md`) and each PAF agent (`agents/*.md`) registers it with the same block, so it runs only where PAF runs: for the main thread once a PAF skill was invoked in the session, and for a PAF agent's own calls (`docs/architecture.md` §3, "Where the hook runs"):

```yaml
hooks:
  PreToolUse:
    - matcher: "Bash|Edit|Write|MultiEdit|Read|Grep|Glob|WebSearch|WebFetch|Task"
      hooks:
        - type: command
          command: 'python3 "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/hooks/paf/PreToolUse-agent-guard.py"'
```

The command is run by the shell, which resolves the Claude config directory (`CLAUDE_CONFIG_DIR`, else `~/.claude`) to the installed script. A new skill or agent copies this block, and a new agent also adds its name to `PAF_AGENTS` in the script.

The matcher covers every tool the hook decides on: the ones it may deny or confine (`Bash`, the write tools, and the read tools `Read`/`Grep`/`Glob`), plus `WebSearch`/`WebFetch`, which it allows for an agent without a prompt, and `Task`, which it sees and leaves to the normal permission flow.

## Install target

The installer places hook scripts at `~/.claude/hooks/paf/`. It writes nothing to `~/.claude/settings.json`, and on upgrade removes the hook entry an earlier version wrote there.

## Reference

See `docs/architecture.md` §3 for the full three-layer enforcement model and the per-category tool scopes this hook backs.
