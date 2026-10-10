#!/usr/bin/env python3
"""PAF repository readiness check — the deterministic half of `/paf:init`.

Runs every environment check in one call and prints one line per check:

  CHECK <name> <ok|warn|fail|skip> <message>
  REMEDY <name> <exact fix>                    (for every check that is warn or fail)

followed by machine-readable summary lines:

  LAUNCH_DIR=<dir>   GIT_ROOT=<dir|none>   INSTRUCTIONS_MODE=<value>
  INSTRUCTIONS_LOADED=<abs paths ;-separated|none>
  AGENTS_HIDDEN=<abs paths ;-separated|none>
  VERDICT=ready|not-ready

`VERDICT` covers the environment only — the problems `/paf:init` cannot fix
itself (any `fail` outside the `instructions` check). Whether the instructions
file loads, and what it covers, is the skill's half: it reads the files named in
INSTRUCTIONS_LOADED and compares them to the content checklist by meaning. The
script always exits 0; a usage error is the only non-zero exit. A `--base` value
outside [A-Za-z0-9._/-] or starting with `-` is a usage error: it comes from a
repository file and must never reach a shell or a version-control option.

Checks:
  git-repo        the launch directory is inside a git repository
  origin          `paf-vcs provider` — the origin host is exactly github.com or gitlab.com
  vcs-cli         `paf-vcs auth-status` — the matching gh/glab is installed and authenticated
  python3         `python3` is on PATH
  claude-version  `claude --version` >= 2.1.277 (reads AGENTS.md natively); < 2.1.281 warns
  base-branch     `--base` exists locally or on origin (skip when not given)
  launch-root     Claude Code was launched from the git root
  instructions    which project instructions files Claude Code loads, and any hidden AGENTS.md

Which file loads follows https://code.claude.com/docs/en/memory#agents-md: a
CLAUDE.md, .claude/CLAUDE.md or CLAUDE.local.md in the launch directory or any
directory above it hides AGENTS.md under the default `Project instructions`
value; `@path` imports are followed up to four hops. Only AGENTS.md files at or
below the repository root count as hidden (one in a parent directory is a note). That value is read from `pluginConfigs` in the user's settings.json — the
only settings file Claude Code reads it from besides `--settings` and managed
settings, which this script cannot see.

The launch directory is the cwd of the Claude Code process (`$CLAUDE_PID`, set
in the Bash tool's environment): the Bash tool's own cwd can drift during a
session. This is verified empirically, not documented, so when it cannot be
read the script falls back to its own cwd and says the result is unverified.

Usage:
  paf-readiness.py [--base <branch>] [--launch-dir <dir>]
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

PAF_VCS = Path(__file__).resolve().parent / "paf-vcs"

MIN_VERSION = (2, 1, 277)        # reads AGENTS.md natively
FULL_AGENTS_VERSION = (2, 1, 281)  # before it, Bedrock / telemetry-disabled sessions skip AGENTS.md

CLAUDE_NAMES = ("CLAUDE.md", os.path.join(".claude", "CLAUDE.md"), "CLAUDE.local.md")
AGENTS_NAMES = ("AGENTS.md", os.path.join(".claude", "AGENTS.md"))

DEFAULT_MODE = "claude-md-or-agents-md"
MAX_IMPORT_HOPS = 4
BASE_RE = re.compile(r"^[A-Za-z0-9._/][A-Za-z0-9._/-]*$")
# The instructions check is the skill's half, so its failure does not make the environment not-ready.
NON_ENV = frozenset({"instructions"})
MODES = (DEFAULT_MODE, "claude-md-and-agents-md", "claude-md", "managed-only")
# The built-in plugin's ID; `agents-md@builtin` is its name before v2.1.285.
PLUGIN_IDS = ("cc-plugin-agents-md@builtin", "agents-md@builtin")

TIMEOUT = 30


def _one_line(text: str) -> str:
    return re.sub(r"[\x00-\x1f\x7f\s]+", " ", str(text)).strip()


def _run(cmd, cwd=None):
    """Run a command; return (returncode, stdout, stderr). Never raises."""
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", str(exc)
    return proc.returncode, proc.stdout, proc.stderr


# --- launch directory --------------------------------------------------------

def detect_launch_dir():
    """Return (directory, verified). Verified only when read from $CLAUDE_PID."""
    pid = os.environ.get("CLAUDE_PID", "")
    if pid.isdigit():
        try:
            return os.readlink(f"/proc/{pid}/cwd"), True      # Linux
        except OSError:
            pass
        if shutil.which("lsof"):                                 # macOS / BSD
            rc, out, _ = _run(["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"])
            if rc == 0:
                for line in out.splitlines():
                    if line.startswith("n") and len(line) > 1:
                        return line[1:], True
    return os.getcwd(), False


# --- Claude Code version and Project instructions mode ----------------------

def parse_version(text):
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(g) for g in match.groups()) if match else None


def fmt_version(version):
    return ".".join(str(n) for n in version)


def read_mode(config_dir):
    """The Project instructions value from <config_dir>/settings.json, else the default."""
    try:
        with open(os.path.join(config_dir, "settings.json")) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return DEFAULT_MODE
    configs = data.get("pluginConfigs") if isinstance(data, dict) else None
    if not isinstance(configs, dict):
        return DEFAULT_MODE
    for plugin_id in PLUGIN_IDS:
        entry = configs.get(plugin_id)
        options = entry.get("options") if isinstance(entry, dict) else None
        value = options.get("instructionFiles") if isinstance(options, dict) else None
        if value in MODES:
            return value
    return DEFAULT_MODE


# --- which instruction files load -------------------------------------------

def _ancestors(start):
    """start and every directory above it, filesystem root first."""
    path = os.path.realpath(start)
    chain = [path]
    while os.path.dirname(path) != path:
        path = os.path.dirname(path)
        chain.append(path)
    return list(reversed(chain))


_FENCE = re.compile(r"^\s*(```|~~~)")
_CODE_SPAN = re.compile(r"`[^`]*`")
_IMPORT = re.compile(r"(?<![\w@])@(\S+)")
_TRAILING = ".,;:!?)]}>'\""


def imports(path):
    """Absolute real paths a memory file imports with `@path` (fences and code spans skipped)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return set()
    base = os.path.dirname(path)
    found, in_fence = set(), False
    for line in lines:
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for target in _IMPORT.findall(_CODE_SPAN.sub("", line)):
            target = os.path.expanduser(target.rstrip(_TRAILING))
            found.add(os.path.realpath(os.path.join(base, target)))
    return found


def reachable(paths):
    """Real paths of `paths` plus everything they import, up to MAX_IMPORT_HOPS hops."""
    seen = {os.path.realpath(p) for p in paths}
    frontier = set(seen)
    for _ in range(MAX_IMPORT_HOPS):
        frontier = {t for p in frontier for t in imports(p)} - seen
        seen |= frontier
    return seen


def resolve_instructions(launch, config_dir, mode, version, git_root=None):
    """Which project instruction files Claude Code loads when launched in `launch`.

    Returns a dict: claude (CLAUDE-type files found), agents (AGENTS files found),
    loaded (files read as project instructions), hidden (AGENTS files at or below
    `git_root` that are neither loaded nor imported/symlinked by a loaded file;
    every such file when `git_root` is None), outside (the same, above `git_root`).
    All paths are absolute.
    """
    user_memory = os.path.join(os.path.realpath(config_dir), "CLAUDE.md")
    claude, agents = [], []
    for directory in _ancestors(launch):
        for name in CLAUDE_NAMES:
            path = os.path.join(directory, name)
            if path != user_memory and os.path.isfile(path):
                claude.append(path)
        for name in AGENTS_NAMES:
            path = os.path.join(directory, name)
            if os.path.isfile(path):
                agents.append(path)

    supported = version is None or version >= MIN_VERSION
    if mode == "managed-only":
        loaded = []
    elif not supported or mode == "claude-md":
        loaded = list(claude)
    elif mode == "claude-md-and-agents-md":
        loaded = claude + agents
    else:
        loaded = list(claude) if claude else list(agents)

    seen = reachable(loaded)
    unseen = [a for a in agents if a not in loaded and os.path.realpath(a) not in seen]
    root = os.path.realpath(git_root) if git_root else None
    inside = [a for a in unseen if root is None or os.path.realpath(a).startswith(root + os.sep)]
    return {"claude": claude, "agents": agents, "loaded": loaded, "hidden": inside,
            "outside": [a for a in unseen if a not in inside]}


# --- the checks --------------------------------------------------------------

class Report:
    def __init__(self):
        self.lines, self.env_fail = [], False

    def add(self, name, status, message, remedy=None):
        """Record a check. A warn/fail without an explicit remedy uses its message as the fix."""
        self.lines.append(f"CHECK {name} {status} {_one_line(message)}")
        if status in ("warn", "fail"):
            self.lines.append(f"REMEDY {name} {_one_line(remedy or message)}")
        if status == "fail" and name not in NON_ENV:
            self.env_fail = True


def _vcs_error(stderr):
    return _one_line(re.sub(r"^Error:\s*", "", stderr.strip())) or "paf-vcs failed"


def check_vcs(report, git_root):
    rc, out, err = _run(["bash", str(PAF_VCS), "provider"], cwd=git_root)
    if rc != 0:
        msg = _vcs_error(err)
        report.add("origin", "fail", msg,
                    f"{msg} Point origin at a github.com or gitlab.com repository "
                    "(`git remote set-url origin <url>`).")
        report.add("vcs-cli", "skip", "origin remote not usable")
        return
    provider = out.strip()
    report.add("origin", "ok", f"origin host is supported (provider: {provider})")
    rc, out, err = _run(["bash", str(PAF_VCS), "auth-status"], cwd=git_root)
    if rc == 0:
        report.add("vcs-cli", "ok", f"{provider} is installed and authenticated")
    else:
        report.add("vcs-cli", "fail", _vcs_error(err))


def check_version(report):
    rc, out, err = _run(["claude", "--version"])
    version = parse_version(out) if rc == 0 else None
    if version is None:
        report.add("claude-version", "warn", "could not run `claude --version`",
                   "Confirm Claude Code is v2.1.277 or later (`claude --version`).")
    elif version < MIN_VERSION:
        report.add("claude-version", "fail",
                   f"Claude Code {fmt_version(version)} cannot read AGENTS.md",
                   f"Upgrade Claude Code to v{fmt_version(MIN_VERSION)} or later (`claude update`).")
    elif version < FULL_AGENTS_VERSION:
        report.add("claude-version", "warn",
                   f"Claude Code {fmt_version(version)}: Amazon Bedrock and telemetry-disabled "
                   "sessions read CLAUDE.md only",
                   f"Upgrade Claude Code to v{fmt_version(FULL_AGENTS_VERSION)} or later (`claude update`).")
    else:
        report.add("claude-version", "ok", f"Claude Code {fmt_version(version)}")
    return version


def check_base(report, git_root, base):
    if base is None:
        report.add("base-branch", "skip", "no base branch given")
        return
    for ref in (f"refs/heads/{base}", f"refs/remotes/origin/{base}"):
        rc, _, _ = _run(["git", "-C", git_root, "rev-parse", "--verify", "--quiet", ref])
        if rc == 0:
            report.add("base-branch", "ok", f"base branch {base} exists")
            return
    report.add("base-branch", "fail", f"base branch {base} does not exist locally or on origin",
               f"Create and push the base branch {base}, or correct it in the project instructions.")


def check_launch_root(report, launch, verified, git_root):
    same = launch == os.path.realpath(git_root)   # `launch` is already a real path
    if not verified:
        report.add("launch-root", "warn",
                   f"launch directory unverified ($CLAUDE_PID unavailable); assumed {launch}",
                   f"Make sure Claude Code was started from {git_root}.")
    elif same:
        report.add("launch-root", "ok", "Claude Code was launched from the git root")
    else:
        report.add("launch-root", "fail", f"Claude Code was launched from {launch}, not the git root",
                   f"Quit and restart Claude Code from {git_root}.")


def check_instructions(report, launch, config_dir, mode, version, git_root):
    result = resolve_instructions(launch, config_dir, mode, version, git_root)
    if not result["loaded"]:
        if mode == "managed-only":
            msg = "no project instructions file loads"
            remedy = "Set Project instructions back to claude-md-or-agents-md in /config."
        elif result["agents"]:
            msg = "an AGENTS.md exists but no project instructions file loads it"
            remedy = ("Create a CLAUDE.md at the git root containing the line `@AGENTS.md`, or set "
                      "Project instructions to claude-md-or-agents-md in /config, or upgrade Claude "
                      f"Code to v{fmt_version(MIN_VERSION)} or later. Do not create another AGENTS.md.")
        else:
            msg = "no project instructions file loads"
            remedy = "Create a project instructions file (AGENTS.md or CLAUDE.md) at the git root."
        report.add("instructions", "fail", msg, remedy)
    elif result["hidden"]:
        hiders = ", ".join(result["claude"]) or "the Project instructions setting"
        report.add("instructions", "warn",
                   f"AGENTS.md is not loaded: hidden by {hiders}",
                   "Add an `@AGENTS.md` import to CLAUDE.md, or set Project instructions to "
                   "claude-md-and-agents-md in /config.")
    else:
        note = ("; note: not loaded, above the git root: " + "; ".join(result["outside"])
                if result["outside"] else "")
        report.add("instructions", "ok", "loaded: " + "; ".join(result["loaded"]) + note)
    return result


def _skip_all(report, names):
    for name in names:
        report.add(name, "skip", "not a git repository")


def run(base, launch, verified):
    """`launch` is a real path."""
    report = Report()
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")

    rc, out, err = _run(["git", "-C", launch, "rev-parse", "--show-toplevel"])
    git_root = out.strip() if rc == 0 and out.strip() else None
    if git_root:
        report.add("git-repo", "ok", f"git repository at {git_root}")
        check_vcs(report, git_root)
    else:
        report.add("git-repo", "fail", f"{launch} is not inside a git repository",
                   "Run /paf:init from inside the project's git repository.")
        _skip_all(report, ("origin", "vcs-cli"))

    if shutil.which("python3"):
        report.add("python3", "ok", "python3 is on PATH")
    else:
        report.add("python3", "fail", "python3 not found", "Install Python 3 and put `python3` on PATH.")

    version = check_version(report)

    if git_root:
        check_base(report, git_root, base)
        check_launch_root(report, launch, verified, git_root)
    else:
        _skip_all(report, ("base-branch", "launch-root"))

    mode = read_mode(config_dir)
    result = check_instructions(report, launch, config_dir, mode, version, git_root)

    lines = report.lines + [
        f"LAUNCH_DIR={launch}",
        f"GIT_ROOT={git_root or 'none'}",
        f"INSTRUCTIONS_MODE={mode} (from {os.path.join(config_dir, 'settings.json')}; "
        "--settings and managed settings not inspected)",
        "INSTRUCTIONS_LOADED=" + (";".join(result["loaded"]) or "none"),
        "AGENTS_HIDDEN=" + (";".join(result["hidden"]) or "none"),
        "VERDICT=" + ("not-ready" if report.env_fail else "ready"),
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="PAF repository readiness check.")
    parser.add_argument("--base", help="the base branch named in the project instructions")
    parser.add_argument("--launch-dir", help="override the detected Claude Code launch directory")
    args = parser.parse_args()
    if args.base is not None and not BASE_RE.match(args.base):
        parser.error("--base must be a branch name made of letters, digits, '.', '_', '/' and '-', "
                     "not starting with '-'")
    launch, verified = (args.launch_dir, True) if args.launch_dir else detect_launch_dir()
    print(run(args.base, os.path.realpath(launch), verified))


if __name__ == "__main__":
    main()
