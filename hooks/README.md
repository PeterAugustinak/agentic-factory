# hooks/

Hook shell scripts executed by the Claude Code harness. Hooks enforce tool access restrictions at the harness level — they are the enforcement layer, not advisory prompts.

## What belongs here

Shell scripts named after the hook event they handle. Each script must be executable (`chmod +x`).

## File naming

`<EventName>-<purpose>.sh` — PascalCase event name matching Claude Code hook events, hyphenated purpose. Examples:

- `PreToolUse-restrict-tools.sh`
- `PostToolUse-report-cost.sh`

Supported hook events: `PreToolUse`, `PostToolUse`, `Stop`, `SubagentStop`, `Notification`.

## Install target

The installer places hook scripts at `~/.claude/hooks/paf/` and wires them into `~/.claude/settings.json`.

## Hooks in this factory

See `docs/architecture.md` Section 3 for the tool access scope each hook enforces.
