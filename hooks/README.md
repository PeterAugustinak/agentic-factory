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
- **Any agent's Read/Grep/Glob** → allowed inside the project root and the session's own saved tool results, plus an agent `Read` (only `Read`) of PAF's review input folder, `~/.claude/paf/review-input/`, where the code reviewers' shared input file and the convention suggester's input file live; anything reaching outside them gets an `ask` decision, a human permission prompt that auto mode's classifier cannot approve silently.

It reads the hook payload as JSON on stdin and prints a `permissionDecision` object (`hookSpecificOutput`) on stdout — `allow` for a vetted call (no prompt), `deny` to block, `ask` to force a prompt — or exits 0 with no output so the normal permission flow proceeds for anything it does not recognize.

## How the rules are applied

The details behind the rules above, as `PreToolUse-agent-guard.py` implements them. Why each rule exists, and the risks accepted with it, is in `docs/architecture.md` §3.

- **Identity.** The main thread is the *absence* of `agent_type` from the payload. A key that is present but empty, null, or unknown is never the main thread: it falls to the agent branch and gets no decision as not PAF's. The main thread gets `allow` for every call, `WebSearch`/`WebFetch` included.
- **Agent sets.** `PAF_AGENTS` names every PAF agent; `READ_ONLY_AGENTS` names the agents whose Bash is read-only. A new agent adds a line to `PAF_AGENTS`; one that uses Bash for exploration only also adds a line to `READ_ONLY_AGENTS`.
- **Read-only Bash.** Only commands on the read-only allowlist (`READ_ONLY_COMMANDS`, e.g. `grep`, `find`, `git log`, `git diff`, `cat`, `ls`) pass, and every segment of a compound command must clear it:
  - The command is lexed quote-aware, so a `|` inside a `grep` pattern is data, not a boundary.
  - A segment ends at any token made entirely of shell punctuation that is not a redirection operator — a property, not a list: the lexer returns a run of punctuation as one token, so `|&`, `<(`, `>(`, and `;;` split the segment too, and whatever follows must clear the allowlist on its own. The body of a `$(...)` or backtick substitution falls under the same rule.
  - A newline is split before lexing, since the lexer counts it as whitespace and would otherwise let the next command pose as arguments to the current one.
  - Output redirection to anywhere but `/dev/null` is denied (`echo pwned > /tmp/pwned.txt` is a write however read-only `echo` is). A file-descriptor target is accepted only when the operator itself carries `&`: `>&1` duplicates a descriptor, but `> 1` writes a file named `1`.
  - A command's own write flags are denied where the file is the command's argument rather than a shell redirection (`COMMAND_WRITE_FLAGS`: `find -delete`/`-exec`/`-fprint*` and its other actions, `tree -o`).
  - A command that cannot be lexed at all (unbalanced quoting) is denied.
- **External I/O and git state.** Denied for every PAF agent: `gh`, `glab`, the `paf-vcs` adapter, network commands, and git-state changes. The git-state pattern skips a run of git's documented global options before matching the subcommand, so `git -C /tmp commit` and `git --no-pager push` are caught; options that take a **separate** argument are named explicitly, because git accepts `--work-tree /tmp` as readily as `--work-tree=/tmp`, and an argument may be quoted and contain a space. Both patterns also run against an escape-normalized reconstruction of the command (`escape_normalized()`), built from the same `shlex` lexing the read-only allowlist uses, so a command name split by backslash-escaping or quote concatenation (`g\it commit`, `c\url`) is caught. A token that itself contains whitespace is re-quoted before rejoining (`_requote()`), so a quoted multi-word argument stays one argument and `g\it -C "/tmp/my repo" commit -m x` is caught too.
- **Web lookups.** `WebSearch`/`WebFetch` are allowed for any PAF agent whose call reaches the hook, with no agent-name check: only an agent that lists them in `tools:` can make the call.
- **Build/test Bash.** A PAF agent not in `READ_ONLY_AGENTS` may run any Bash that is neither external I/O nor a git-state change, with no output-redirection or write-path check.
- **Writes.** The project root is the resolved `CLAUDE_PROJECT_DIR`, falling back to the payload's `cwd` when the variable is unset. An `Edit`/`Write`/`MultiEdit` whose target resolves outside it is denied.
- **Reads.** Relative paths, and an absent `Grep`/`Glob` `path`, resolve against the payload's `cwd`, as the tools resolve them, with `~` expanded first. A `Glob` pattern is bounded by its literal prefix (`/etc/*`, `/*` and `../*` reach outside); it gets `ask` when no prefix can bound it — a `..` after its first wildcard, or a brace/extglob alternative that starts absolute or home-relative (`{/etc,/tmp}/*`). A field the hook cannot interpret (an unexpandable `~`) gets `ask`, never a crash. `Grep`'s `glob` parameter is not checked. Case-variant paths on a case-insensitive filesystem get `ask`. The session's `tool-results/` directory is found by walking up from `transcript_path` to the directory named `session_id`; the review input folder is located from `HOME`. Those two checks run only after the root check fails, so they cannot disturb an in-root read.

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

See `docs/architecture.md` §3 for why: the three-layer enforcement model, the per-category tool scopes this hook backs, and the risks accepted with each rule.
