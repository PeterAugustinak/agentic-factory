#!/usr/bin/env python3
"""Centralized PreToolUse hook — the single, global tool-restriction enforcer for
PAF agents (architecture.md §3, layer 3).

It enforces the sub-tool restrictions that frontmatter allowlists cannot express,
keyed on the `agent_type` field of the PreToolUse payload:

- **Main thread (no `agent_type`)** — the orchestrating skill is running:
  unrestricted (exit 0).
- **All agents** — no external I/O (`gh`, `curl`, `wget`, `ssh`, ...) and no git
  state changes (`add`/`commit`/`push`/...); both are skill-owned (§2).
- **`code-explorer`, `implementation-planner`** — read-only Bash only
  (default-deny allowlist on the command name).
- **Any agent with Edit/Write** — writes confined to the project root
  (`CLAUDE_PROJECT_DIR`).

Reads the hook payload as JSON on stdin. To block, prints a PreToolUse `deny`
decision as JSON on stdout and exits 0; otherwise exits 0 with no output so the
normal permission flow proceeds.
"""

import json
import os
import re
import sys

READ_ONLY_AGENTS = {"code-explorer", "implementation-planner"}

# Default-deny allowlist for the read-only agents (matched on the command name).
READ_ONLY_COMMANDS = {
    "grep", "egrep", "fgrep", "rg", "ag", "find", "cat", "ls", "head", "tail",
    "wc", "tree", "file", "stat", "pwd", "echo", "which", "git",
}

# External I/O — blocked for every agent (skill-owned).
EXTERNAL_IO = re.compile(r"(?:^|[^\w])(gh|curl|wget|nc|ncat|ssh|scp|telnet|ftp)(?:[^\w]|$)")

# Git state changes / network — blocked for every agent (skill owns git state).
GIT_MUTATE = re.compile(
    r"(?:^|[^\w])git\s+(add|commit|push|pull|fetch|clone|checkout|switch|branch|"
    r"reset|merge|rebase|tag|stash|clean|rm|mv|apply|cherry-pick|restore)(?:[^\w]|$)"
)


def deny(reason: str) -> None:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        },
        sys.stdout,
    )
    sys.exit(0)


def command_name(cmd: str) -> str:
    """First real command word, skipping leading `VAR=value` env assignments."""
    tokens = cmd.strip().split()
    i = 0
    while i < len(tokens) and re.match(r"^\w+=", tokens[i]):
        i += 1
    return os.path.basename(tokens[i]) if i < len(tokens) else ""


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)  # malformed payload is not ours to judge — let normal flow run

    agent = data.get("agent_type") or ""
    if not agent:
        sys.exit(0)  # main thread (the skill) — intentionally unrestricted

    tool = data.get("tool_name") or ""
    tool_input = data.get("tool_input") or {}
    project = os.path.realpath(
        os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    )

    if tool == "Bash":
        cmd = tool_input.get("command") or ""
        if EXTERNAL_IO.search(cmd):
            deny("Agents may not perform external I/O (gh/network); it is skill-owned (architecture.md §2).")
        if GIT_MUTATE.search(cmd):
            deny("Agents never change git state; the skill owns branch/commit/push (architecture.md §2).")
        if agent in READ_ONLY_AGENTS:
            name = command_name(cmd)
            if name not in READ_ONLY_COMMANDS:
                deny(
                    f"{agent} may run read-only commands only "
                    f"(grep, find, git log/diff, cat, ls, ...); got: {name or '(empty)'}"
                )
        sys.exit(0)

    if tool in ("Edit", "Write", "MultiEdit"):
        path = tool_input.get("file_path") or tool_input.get("path") or ""
        if not path:
            sys.exit(0)
        resolved = os.path.realpath(path if os.path.isabs(path) else os.path.join(project, path))
        if resolved == project or resolved.startswith(project + os.sep):
            sys.exit(0)
        deny(f"Writes must stay within the project root ({project}); target resolves outside it: {resolved}")

    sys.exit(0)


if __name__ == "__main__":
    main()
