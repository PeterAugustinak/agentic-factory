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
- **All agents** → no external I/O (`gh`/network) and no git state changes — both skill-owned.
- **`code-explorer`, `implementation-planner`** → read-only Bash only (default-deny allowlist).
- **Any agent with Edit/Write** → writes confined to the project root (`CLAUDE_PROJECT_DIR`).

It reads the hook payload as JSON on stdin and, to block, prints a `permissionDecision: "deny"` object (`hookSpecificOutput`) on stdout; otherwise it exits 0 with no output so the normal permission flow proceeds.

## Wiring into settings

The hook is registered in `settings.json` under `hooks.PreToolUse`, matched to the tools it can restrict. The installer places the script and writes this entry; the intended shape (paths resolved by the installer) is:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash|Edit|Write|MultiEdit",
        "hooks": [
          { "type": "command", "command": "python3 ~/.claude/hooks/paf/PreToolUse-agent-guard.py" }
        ]
      }
    ]
  }
}
```

The matcher limits the hook to the tools whose *use* it may deny; read-only tools (`Read`, `WebSearch`, `WebFetch`) are governed by the agents' frontmatter allowlists and need no hook.

## Install target

The installer places hook scripts at `~/.claude/hooks/paf/` and wires them into `~/.claude/settings.json`.

## Reference

See `docs/architecture.md` §3 for the full three-layer enforcement model and the per-category tool scopes this hook backs.
