# hooks/

Hook scripts executed by the Claude Code harness. Hooks are the **enforcement** layer of PAF's tool-access model (`docs/architecture.md` §3, layer 3) — real, harness-level restrictions, not advisory prompts.

## What belongs here

Executable scripts named after the hook event they handle. A script may be a shell script or a Python script (whatever expresses the logic most robustly); it must be executable (`chmod +x`) and carry an appropriate shebang.

## File naming

`<EventName>-<purpose>.{sh,py}` — PascalCase event name matching a Claude Code hook event, hyphenated purpose. Example: `PreToolUse-agent-guard.py`.

Supported hook events: `PreToolUse`, `PostToolUse`, `Stop`, `SubagentStop`, `Notification`, `SubagentStart`.

## The factory hook

**`PreToolUse-agent-guard.py`** — the single, centralized `PreToolUse` hook, keyed on the payload's `agent_type` field (`docs/architecture.md` §3). It enforces the sub-tool restrictions that frontmatter allowlists cannot express:

- **Main thread** (no `agent_type`) → unrestricted (the orchestrating skill), with one exception: an `Agent` call starting a PAF agent (one shipped in `agents/`, listed in the hook's `PAF_AGENTS`) is denied when its prompt points to an existing file in a temp directory outside the project root. Agent input goes in the prompt, never through a file (`docs/architecture.md` §4, Input delivery); the deny reason goes to the model and tells it to resend the content inline, so the developer gets no prompt. A path merely mentioned in the prompt (one that is not an existing temp file) does not block the call, and calls starting non-PAF agents are not checked.
- **All agents** → no external I/O (`gh`/network) and no git state changes — both skill-owned, and the git pattern skips git's global options so `git -C <dir> commit` is caught too.
- **`code-explorer`, `implementation-planner`** → read-only Bash only (default-deny allowlist, applied to every segment of a compound command, plus denials for output redirection and commands' own write flags such as `find -delete` and `tree -o`).
- **Any agent with Edit/Write** → writes confined to the project root (`CLAUDE_PROJECT_DIR`).
- **Any agent's Read/Grep/Glob** → allowed inside the project root and the session's own saved tool results. For a **PAF agent**, everything else is denied, never asked — including directories added with `--add-dir`/`additionalDirectories`, a Glob pattern with no boundable prefix, an unexpandable `~`, and any target or field the hook cannot place. For **any other agent**, a read reaching outside gets an `ask` decision, a human permission prompt that auto mode's classifier cannot approve silently.

It reads the hook payload as JSON on stdin and prints a `permissionDecision` object (`hookSpecificOutput`) on stdout — `allow` for a vetted call (no prompt), `deny` to block, `ask` to force a prompt — or exits 0 with no output so the normal permission flow proceeds for anything it does not recognize.

## Wiring into settings

The hook is registered in `settings.json` under `hooks.PreToolUse`, matched to the tools it can restrict. The installer places the script and writes this entry; the intended shape (paths resolved by the installer) is:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash|Edit|Write|MultiEdit|Read|Grep|Glob|WebSearch|WebFetch|Agent",
        "hooks": [
          { "type": "command", "command": "python3 ~/.claude/hooks/paf/PreToolUse-agent-guard.py" }
        ]
      }
    ]
  }
}
```

The matcher covers every tool the hook decides on: the ones it may deny or confine (`Bash`, the write tools, and the read tools `Read`/`Grep`/`Glob`), plus `WebSearch`/`WebFetch`, which it allows for an agent without a prompt, and `Agent` — the tool that starts a subagent, as hooks see it — whose prompt it checks when the main thread starts a PAF agent.

## Install target

The installer places hook scripts at `~/.claude/hooks/paf/` and wires them into `~/.claude/settings.json`.

## Reference

See `docs/architecture.md` §3 for the full three-layer enforcement model and the per-category tool scopes this hook backs.
