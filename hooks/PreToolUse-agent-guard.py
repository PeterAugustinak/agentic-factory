#!/usr/bin/env python3
"""Centralized PreToolUse hook — the single allow+deny authority for PAF
(architecture.md §3, layer 3).

Keyed on the `agent_type` field of the PreToolUse payload, it returns an explicit
permission decision for every call it recognizes, so vetted factory calls run
WITHOUT a permission prompt and forbidden ones are blocked:

- ALLOW — the main thread unconditionally (the trusted orchestrator owns all I/O
  and git state, §2), plus each agent's legitimate tool set: read-only Bash,
  build/test Bash, project-scoped writes, and web lookups (gated by each agent's
  `tools:` allowlist). These skip the permission prompt.
- DENY  — agents doing external I/O (gh/curl/wget/ssh/...), agents changing git
  state (add/commit/push/...), read-only agents running non-read-only Bash, and
  any write outside the project root. All skill-owned or unsafe (§2).
- DEFER — anything unrecognized: emit nothing, so Claude Code's normal permission
  flow (and prompt) applies. Keeps a human safety net for novel calls.

Reads the hook payload as JSON on stdin; emits a PreToolUse decision as JSON on
stdout (allow/deny) or nothing (defer); always exits 0.
"""

import json
import os
import re
import sys

# The sole home of the read-only-vs-build/test Bash distinction: code-explorer,
# implementation-planner, and implementation-verifier all declare identical
# `tools: Read, Bash`, so frontmatter cannot express which need read-only Bash and
# which need build/test Bash. Adding a new read-only Bash agent means one line here.
READ_ONLY_AGENTS = {"code-explorer", "implementation-planner"}

# Read-only Bash allowlist for the read-only agents (matched on the command name).
READ_ONLY_COMMANDS = {
    "grep", "egrep", "fgrep", "rg", "ag", "find", "cat", "ls", "head", "tail",
    "wc", "tree", "file", "stat", "pwd", "echo", "which", "git",
}

# External I/O — denied for every agent (skill-owned).
EXTERNAL_IO = re.compile(r"(?:^|[^\w])(gh|glab|paf-vcs|curl|wget|nc|ncat|ssh|scp|telnet|ftp)(?:[^\w]|$)")

# Git state changes — denied for every agent (skill owns git state).
GIT_MUTATE = re.compile(
    r"(?:^|[^\w])git\s+(add|commit|push|pull|fetch|clone|checkout|switch|branch|"
    r"reset|merge|rebase|tag|stash|clean|rm|mv|apply|cherry-pick|restore)(?:[^\w]|$)"
)


def _emit(decision: str, reason: str) -> None:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": decision,
                "permissionDecisionReason": reason,
            }
        },
        sys.stdout,
    )
    sys.exit(0)


def allow(reason: str) -> None:
    _emit("allow", reason)


def deny(reason: str) -> None:
    _emit("deny", reason)


def defer() -> None:
    sys.exit(0)  # emit nothing — Claude Code's normal permission flow (and prompt) applies


def command_name(cmd: str) -> str:
    """First real command word, skipping leading `VAR=value` env assignments."""
    tokens = cmd.strip().split()
    i = 0
    while i < len(tokens) and re.match(r"^\w+=", tokens[i]):
        i += 1
    return os.path.basename(tokens[i].strip("\"'")) if i < len(tokens) else ""


def within_project(path: str, project: str) -> bool:
    if not path:
        return False
    resolved = os.path.realpath(path if os.path.isabs(path) else os.path.join(project, path))
    return resolved == project or resolved.startswith(project + os.sep)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        defer()  # malformed payload is not ours to judge

    if not isinstance(data, dict):
        defer()  # valid JSON but not an object (null/list/string) is not ours to judge

    agent = data.get("agent_type") or ""
    tool = data.get("tool_name") or ""
    tool_input = data.get("tool_input") or {}
    project = os.path.realpath(
        os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    )

    # --- Main thread (the orchestrating skill): owns all I/O and git state. ---
    # Allowed unconditionally, not gated on a command family: gating on the first
    # word made compound/piped/cd-prefixed commands fall through to a prompt (#22).
    # Per the Claude Code hooks documentation, `agent_type` is OMITTED ENTIRELY for
    # the main thread and present with a real name only for a subagent/--agent run,
    # so main-thread identity is the ABSENCE of the key — not a falsy value — and a
    # key present but empty/null fails safe into the restricted agent branch below.
    if "agent_type" not in data:
        allow("Main thread (orchestrating skill) is unrestricted (architecture.md §3).")

    # --- Agents: restricted; allow only their legitimate calls. ---
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
            allow(f"{agent} read-only command '{name}'.")
        allow(f"{agent} may run build/test Bash (non-I/O, non-git-state).")

    if tool in ("WebSearch", "WebFetch"):
        # Web access is gated upstream by the agent's `tools:` allowlist (architecture.md
        # §3 layer 2, harness-level): an agent without WebSearch/WebFetch cannot invoke them,
        # so any call reaching the hook is already web-authorized. Allowing it here just skips
        # the permission prompt.
        allow("Web lookup allowed; web access is gated by the agent's tools: allowlist.")

    if tool in ("Edit", "Write", "MultiEdit"):
        path = tool_input.get("file_path") or tool_input.get("path") or ""
        if not path:
            defer()
        if within_project(path, project):
            allow("Write confined to the project root.")
        deny(f"Writes must stay within the project root ({project}); target resolves outside it.")

    defer()  # anything else — normal permission flow


if __name__ == "__main__":
    main()
