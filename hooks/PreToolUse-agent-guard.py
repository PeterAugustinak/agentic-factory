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
import shlex
import sys

# The sole home of the read-only-vs-build/test Bash distinction: code-explorer,
# implementation-planner, and implementation-verifier all declare identical
# `tools: Read, Bash`, so frontmatter cannot express which need read-only Bash and
# which need build/test Bash. Adding a new read-only Bash agent means one line here.
READ_ONLY_AGENTS = {"code-explorer", "implementation-planner"}

# Read-only Bash allowlist for the read-only agents. Matched on the command name of
# EVERY segment of a compound command, not just the first (#41).
READ_ONLY_COMMANDS = {
    "grep", "egrep", "fgrep", "rg", "ag", "find", "cat", "ls", "head", "tail",
    "wc", "tree", "file", "stat", "pwd", "echo", "which", "git",
}

# The shell metacharacters handed to `shlex` as punctuation, so it returns them as their
# own tokens instead of gluing them into words. This is `shlex`'s own default set plus the
# BACKTICK, which `shlex` otherwise treats as an ordinary word character — leaving
# `` cat `rm -rf /tmp/x` `` looking like a single `cat` invocation (#41).
PUNCTUATION_CHARS = "();<>|&`"

# A token made ENTIRELY of punctuation is a segment boundary unless it is a redirection
# operator (below). Deliberately a property, not a list of known operators: `shlex` merges
# runs of punctuation into one token, so an enumeration silently misses every operator it
# does not name — `|&`, `<(`, `;;` and `>(` each lex as ONE token that equals no entry in
# such a list, and all four then failed to split a segment (#41). Under this rule an
# operator nobody anticipated splits the segment, and whatever follows it must clear the
# allowlist on its own — unknown syntax fails safe.

# Output redirection: `>`, `>>`, `>|`, `<>`, `2>`, `>&`, `2>&`, `&>`, `&>>`. A read-only
# command writing through one of these (`echo pwned > /tmp/pwned.txt`) is a write, whatever
# the command name says.
REDIRECT_OUT = re.compile(r"^(?:\d*(?:>>?\|?|>&|<>)|&>>?)$")

# Input redirection: `<`, `0<`, `<&`. Reading is read-only, so these neither split a
# segment nor need their target checked. `<<`/`<<<` are deliberately NOT here: they fall
# through to the boundary rule, so a here-doc's body is checked rather than trusted.
REDIRECT_IN = re.compile(r"^\d*<&?$")

# Write flags carried by commands that are otherwise read-only — the file is the command's
# OWN argument, so no shell redirection appears for the rule above to catch. find(1)
# documents its actions (which run a command or delete), and tree(1) `-o` writes its
# listing to a file (#41).
COMMAND_WRITE_FLAGS = {
    "find": {"-delete", "-exec", "-execdir", "-ok", "-okdir",
             "-fprint", "-fprint0", "-fprintf", "-fls"},
    "tree": {"-o"},
}

# Leading `VAR=value` env assignments, which precede the real command word.
ENV_ASSIGNMENT = re.compile(r"^\w+=")

# External I/O — denied for every agent (skill-owned).
EXTERNAL_IO = re.compile(r"(?:^|[^\w])(gh|glab|paf-vcs|curl|wget|nc|ncat|ssh|scp|telnet|ftp)(?:[^\w]|$)")

# Git's global options may sit between `git` and its subcommand (`git -C /tmp commit`,
# `git --no-pager push`), which an adjacency-only pattern misses (#41). This skips a run
# of them first. Options that take a SEPARATE argument are named explicitly: git's option
# parser accepts `--work-tree /tmp` as readily as `--work-tree=/tmp`, and matching only the
# `=` form left the space-separated one a bypass. An argument may be quoted and so contain
# a space (`git -C "/tmp/my repo" commit`), which `\S+` alone could not span.
GIT_ARG = r"(?:\"[^\"]*\"|'[^']*'|\S+)"
GIT_OPT_WITH_ARG = (
    r"(?:-[cC]|--(?:git-dir|work-tree|namespace|exec-path|super-prefix|config-env|"
    r"attr-source|list-cmds))"
)
GIT_GLOBAL_OPT = r"(?:" + GIT_OPT_WITH_ARG + r"(?:=|\s+)" + GIT_ARG + r"|--?[A-Za-z][\w-]*(?:=\S+)?)"

# Git state changes — denied for every agent (skill owns git state). The subcommand may
# itself be quoted (`git "commit" -m x`), so a lone quote before it is tolerated. A few
# read-only forms of listed subcommands (`git config --get`, `git remote -v`) are denied
# with them: deny is the safe direction, and the read-only agents keep `git log`/`diff`/
# `show`. `archive`, `bundle` and `format-patch` are here because they WRITE FILES, the
# same reason `tree -o` is denied above — not because they change the repository.
GIT_MUTATE = re.compile(
    r"(?:^|[^\w])git\s+(?:" + GIT_GLOBAL_OPT + r"\s+)*[\"']?"
    r"(add|am|apply|archive|bisect|branch|bundle|checkout|cherry-pick|clean|clone|commit|"
    r"config|fetch|filter-branch|format-patch|gc|init|merge|mv|notes|prune|pull|push|"
    r"rebase|reflog|remote|repack|replace|reset|restore|revert|rm|sparse-checkout|stash|"
    r"submodule|switch|tag|update-index|update-ref|worktree)(?:[^\w]|$)"
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


def _name_from_tokens(tokens: list) -> str:
    """First real command word of an already-tokenized command."""
    i = 0
    while i < len(tokens) and ENV_ASSIGNMENT.match(tokens[i]):
        i += 1
    return os.path.basename(tokens[i].strip("\"'")) if i < len(tokens) else ""


def command_name(cmd: str) -> str:
    """First real command word, skipping leading `VAR=value` env assignments."""
    return _name_from_tokens(cmd.strip().split())


def _is_separator(token: str) -> bool:
    """Whether a token ends the current command and starts a new one."""
    if not token or not set(token) <= set(PUNCTUATION_CHARS):
        return False
    return not (REDIRECT_OUT.match(token) or REDIRECT_IN.match(token))


def shell_segments(cmd: str):
    """Split a (possibly compound) command into one token list per shell segment.

    Lexed with `shlex` rather than a regex split because it is QUOTE-AWARE: the `|` in
    `grep -E 'foo|bar' .` is part of the pattern, not a segment boundary. Returns None
    when the command cannot be lexed at all (unbalanced quoting), which the caller must
    treat as a violation — a command the guard cannot read is not one it can clear.

    A newline separates two commands exactly as `;` does, but `shlex` counts it as
    whitespace and never emits it, so lines are split BEFORE lexing (#41). A trailing
    backslash continues one command across lines rather than ending it, so those are
    folded away first.
    """
    segments, current = [], []
    for line in re.sub(r"\\\n", " ", cmd).splitlines():
        lexer = shlex.shlex(line, posix=True, punctuation_chars=PUNCTUATION_CHARS)
        lexer.whitespace_split = True
        try:
            tokens = list(lexer)
        except ValueError:
            return None

        for token in tokens:
            if _is_separator(token):
                segments.append(current)
                current = []
            else:
                current.append(token)
        segments.append(current)
        current = []
    return [segment for segment in segments if segment]


def _redirect_violation(tokens: list) -> str:
    """Why a segment's redirections are not read-only, or "" when they are."""
    for i, token in enumerate(tokens):
        if not REDIRECT_OUT.match(token):
            continue
        target = tokens[i + 1] if i + 1 < len(tokens) else ""
        if target == "/dev/null":
            continue
        # A digit or `-` is a file descriptor to duplicate or close ONLY when the operator
        # itself carries `&`: `2>&1` duplicates, `> 1` writes a file literally named `1`.
        if "&" in token and (target.isdigit() or target == "-"):
            continue
        return f"redirects output to '{target or '(nothing)'}'"
    return ""


def read_only_violation(cmd: str) -> str:
    """Why `cmd` is not read-only, or "" when every segment of it is.

    The allowlist alone is not enough: it is applied per SEGMENT (so nothing hides behind
    a shell operator), alongside two checks that no command name can express — output
    redirection, and a command's own write flags (#41).
    """
    segments = shell_segments(cmd)
    if segments is None:
        return "unbalanced quoting — the command could not be parsed"
    if not segments:
        return "got: (empty)"

    for tokens in segments:
        violation = _redirect_violation(tokens)
        if violation:
            return violation
        name = _name_from_tokens(tokens)
        if name not in READ_ONLY_COMMANDS:
            return f"got: {name or '(empty)'}"
        write_flags = COMMAND_WRITE_FLAGS.get(name, ())
        used = [token for token in tokens if token in write_flags]
        if used:
            return f"{name} carries the file-writing flag {used[0]}, which is not read-only"
    return ""


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
            violation = read_only_violation(cmd)
            if violation:
                deny(
                    f"{agent} may run read-only commands only "
                    f"(grep, find, git log/diff, cat, ls, ...); {violation}"
                )
            allow(f"{agent} read-only command '{command_name(cmd)}'.")
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
