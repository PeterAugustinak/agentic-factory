#!/usr/bin/env python3
"""PAF headless agent runner — starts agents as `claude -p --agent <name>` runs.

A skill that starts an agent through the Agent tool gets its result back in a
later main-thread turn of its own, which re-sends the whole conversation. This
helper starts one or more agents side by side from ONE Bash call and prints all
their reports together, so they come back in the same turn. Every run that does
not end cleanly is labelled for a fallback: the skill re-runs that agent through
the Agent tool, exactly as it would have started it without this helper.

Usage:
  paf-headless.py probe
  paf-headless.py run --session <parent-session-id>   (agents and prompts on stdin)

`probe` prints `HEADLESS=available TIMEOUT_MS=<n>` — `<n>` is the largest Bash
timeout that applies — or `HEADLESS=unavailable — claude not found on PATH`.

`run` reads blocks from stdin, each opened by a line `<<<PAF-AGENT <name>>>>` and
holding that agent's prompt verbatim up to the next such line or the end. It
prints one block per agent, in input order:

  <<<PAF-AGENT <name>: headless>>>
  <the run's report, unchanged>

or, for a run to re-run through the Agent tool, the single line

  <<<PAF-AGENT <name>: fallback — <reason>>>>

Each run gets its own session id, registered under the parent session before it
starts (`paf-report-cost.py`), so its transcript is priced into the parent run —
also when the run is stopped. The runs are stopped before the Bash timeout
`probe` reports, and when this helper is interrupted, so none keeps running.
Exit 0 means every agent is classified in the output; 2 is a usage error.
"""

import argparse
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

# The agents a skill may start headless; each must also be in `PAF_AGENTS` in
# hooks/PreToolUse-agent-guard.py and shipped as agents/<name>.md (a test checks
# both). `full-stack-dev` is deliberately not here: it edits files, so a stopped
# or failed run would leave half-applied edits for its fallback re-run.
HEADLESS_AGENTS = {
    "issue-validator", "implementation-verifier", "senior-engineer-reviewer",
    "code-simplifier", "security-engineer", "test-coverage-reviewer",
    "conformance-reviewer", "quality-assurer",
}

# Claude Code's documented Bash timeout defaults: the ceiling a call may ask for
# (`BASH_MAX_TIMEOUT_MS`) and the timeout of a call that names none
# (`BASH_DEFAULT_TIMEOUT_MS`); the effective maximum is the larger of the two.
DEFAULT_MAX_TIMEOUT_MS = 600_000
DEFAULT_TIMEOUT_MS = 120_000

# Runs are stopped this long before the limit (at most a quarter of it), leaving
# room for the SIGTERM grace and the output.
STOP_MARGIN_S = 30.0
TERM_GRACE_S = 10.0

AGENT_LINE = re.compile(r"^<<<PAF-AGENT ([A-Za-z0-9._-]+)>>>$")
YAML_FENCE = re.compile(r"^```yaml\s*$", re.MULTILINE)

COST_HELPER = Path(__file__).resolve().parent / "paf-report-cost.py"


def _env_ms(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


def timeout_limit_ms() -> int:
    """The largest Bash timeout that applies (a malformed value counts as unset)."""
    return max(_env_ms("BASH_MAX_TIMEOUT_MS", DEFAULT_MAX_TIMEOUT_MS),
               _env_ms("BASH_DEFAULT_TIMEOUT_MS", DEFAULT_TIMEOUT_MS))


def cmd_probe(_args) -> int:
    if shutil.which("claude") is None:
        print("HEADLESS=unavailable — claude not found on PATH")
    else:
        print(f"HEADLESS=available TIMEOUT_MS={timeout_limit_ms()}")
    return 0


def parse_input(text: str):
    """[(agent, prompt)] from the stdin blocks; raises ValueError on bad input."""
    runs, current = [], None
    for line in text.splitlines(keepends=True):
        match = AGENT_LINE.match(line.rstrip("\r\n"))
        if match:
            current = [match.group(1), []]
            runs.append(current)
        elif current is None:
            if line.strip():
                raise ValueError("input must start with a <<<PAF-AGENT <name>>>> line")
        else:
            current[1].append(line)
    if not runs:
        raise ValueError("no <<<PAF-AGENT <name>>>> block on stdin")
    result = []
    for name, lines in runs:
        if name not in HEADLESS_AGENTS:
            raise ValueError(f"agent {name!r} is not one the factory starts headless")
        prompt = "".join(lines).strip("\n")
        if not prompt.strip():
            raise ValueError(f"empty prompt for agent {name!r}")
        result.append((name, prompt))
    return result


def agent_tools(name: str):
    """The agent's frontmatter `tools`, comma-joined, from the installed agent file
    `--agent` loads; None when it cannot be read."""
    config = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    path = Path(config) / "agents" / "paf" / f"{name}.md"
    try:
        lines = path.read_text().splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith("tools:"):
            if "(" in line:
                return None  # a scoped entry such as Bash(a, b) cannot be split on commas
            tools = [t.strip() for t in line[len("tools:"):].split(",") if t.strip()]
            return ",".join(tools) if tools else None
    return None


def _git(*args) -> str:
    try:
        proc = subprocess.run(["git", *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout.rstrip() if proc.returncode == 0 else ""


def git_status_block() -> str:
    """The git status snapshot an Agent-tool subagent starts with, which a `-p`
    run as a custom agent does not get: the same fields, built from git. Empty
    outside a git repository; a field git cannot give is left out."""
    if _git("rev-parse", "--is-inside-work-tree") != "true":
        return ""
    parts = ["# gitStatus\nThis is the git status at the start of the conversation. Note that this "
             "status is a snapshot in time, and will not update during the conversation."]
    branch = _git("branch", "--show-current")
    if branch:
        parts.append(f"Current branch: {branch}")
    main = _git("symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if main:
        parts.append(f"Main branch (you will usually use this for PRs): {main.split('/', 1)[-1]}")
    user = _git("config", "user.name")
    if user:
        parts.append(f"Git user: {user}")
    parts.append("Status:\n" + (_git("status", "--short") or "(clean)"))
    commits = _git("log", "--oneline", "-n", "5")
    if commits:
        parts.append("Recent commits:\n" + commits)
    return "\n\n".join(parts)


def load_cost_helper():
    spec = importlib.util.spec_from_file_location("paf_report_cost", str(COST_HELPER))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def classify(proc_returncode, stdout: str, stopped: bool):
    """(report, None) for a clean run, (None, reason) for a fallback."""
    if stopped:
        return None, "stopped before the Bash time limit"
    if proc_returncode != 0:
        return None, f"exit {proc_returncode}"
    try:
        data = json.loads(stdout)
    except ValueError:
        return None, "output is not JSON"
    if not isinstance(data, dict):
        return None, "output is not JSON"
    denials = data.get("permission_denials") or []
    if denials:
        names = sorted({str(d.get("tool_name", "?")) if isinstance(d, dict) else "?" for d in denials})
        return None, f"permission denied ({', '.join(names)})"
    if data.get("is_error"):
        return None, "is_error result"
    report = data.get("result")
    if not isinstance(report, str) or not YAML_FENCE.search(report):
        return None, "no yaml block"
    return report, None


class Run:
    """One agent's headless process, its prompt and output pipes, and its outcome."""

    def __init__(self, name: str, prompt: str):
        self.name = name
        self.prompt = prompt
        self.proc = None      # None: never started
        self.reason = None    # why the run is a fallback; None while it may still be clean
        self.out = []
        self.threads = []
        self.stopped = False  # stopped by this helper at the deadline

    def start(self, cmd):
        # In this helper's own process group, so a signal to the whole group (an
        # interrupt that kills the call's process group) reaches the run too; the
        # helper stops a run's process tree itself (`_tree`).
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True)
        # Prompt and output go through threads, so a large prompt or report can
        # never deadlock a run on a full pipe.
        self.threads = [threading.Thread(target=self._feed, daemon=True),
                        threading.Thread(target=self._drain, daemon=True)]
        for t in self.threads:
            t.start()

    def _feed(self):
        try:
            self.proc.stdin.write(self.prompt)
            self.proc.stdin.close()
        except OSError:
            pass

    def _drain(self):
        self.out.append(self.proc.stdout.read())

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None


def _tree(roots):
    """`roots` plus every live descendant process, from one `ps` listing. Taken
    before a run is signalled: once it dies, its children are re-parented and the
    link to them is lost."""
    try:
        listing = subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True,
                                 text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        listing = ""
    children = {}
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            children.setdefault(int(parts[1]), []).append(int(parts[0]))
    found, todo = set(), list(roots)
    while todo:
        pid = todo.pop()
        if pid not in found:
            found.add(pid)
            todo.extend(children.get(pid, []))
    return found


def _signal_pids(pids, signum):
    for pid in pids:
        try:
            os.kill(pid, signum)
        except OSError:
            pass


class Runs:
    """The started runs, stoppable from the main loop, a signal handler, or the
    parent watcher alike."""

    def __init__(self):
        self.runs = []
        # Re-entrant: a signal handler may run stop_all() while the main loop holds it.
        self.lock = threading.RLock()

    def stop_all(self):
        with self.lock:
            live = [r.proc for r in self.runs if r.running()]
            if not live:
                return
            # Each run's whole process tree (an agent's Bash commands included).
            tree = _tree(p.pid for p in live)
            _signal_pids(tree, signal.SIGTERM)
            deadline = time.monotonic() + TERM_GRACE_S
            for p in live:
                try:
                    p.wait(timeout=max(0.0, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    pass
            # SIGKILL whatever of the tree outlived the grace, its leader included.
            _signal_pids(tree | _tree(p.pid for p in live if p.poll() is None), signal.SIGKILL)
            for p in live:
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass


def cmd_run(args) -> int:
    try:
        parsed = parse_input(sys.stdin.read())
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    cost = load_cost_helper()
    if not cost.is_safe(args.session):
        print(f"ERROR: invalid --session value {args.session!r}", file=sys.stderr)
        return 2

    claude = shutil.which("claude")
    started = Runs()
    budget_s = timeout_limit_ms() / 1000.0
    deadline = time.monotonic() + budget_s - min(STOP_MARGIN_S, budget_s / 4)

    def on_signal(signum, _frame):
        started.stop_all()
        sys.exit(128 + signum)

    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, on_signal)

    parent = os.getppid()

    def watch_parent():
        # The shell that ran this helper was killed: stop the runs and leave.
        while True:
            time.sleep(1.0)
            if os.getppid() != parent:
                started.stop_all()
                os._exit(1)

    threading.Thread(target=watch_parent, daemon=True).start()

    runs = [Run(name, prompt) for name, prompt in parsed]
    started.runs = runs
    try:
        git_status = git_status_block() if claude is not None else ""
        for run in runs:
            if claude is None:
                run.reason = "claude not found on PATH"
                continue
            tools = agent_tools(run.name)
            if tools is None:
                run.reason = "agent tools unreadable"
                continue
            child = str(uuid.uuid4())
            cost.register_child(args.session, child)
            cmd = [claude, "-p", "--agent", run.name, "--output-format", "json",
                   "--session-id", child, "--permission-mode", "dontAsk",
                   "--permission-prompts", "none", "--allowedTools", tools]
            if git_status:
                cmd += ["--append-system-prompt", git_status]
            with started.lock:
                run.start(cmd)

        while any(r.running() for r in runs):
            if time.monotonic() >= deadline:
                for r in runs:
                    r.stopped = r.running()
                started.stop_all()
                break
            time.sleep(0.2)
    finally:
        # An exception must not leave runs going: the skill would re-start them.
        started.stop_all()

    # One shared budget for the pipes to drain, however many runs there are.
    join_end = time.monotonic() + 5
    out = []
    for run in runs:
        for t in run.threads:
            t.join(timeout=max(0.0, join_end - time.monotonic()))
        if run.proc is not None:
            report, run.reason = classify(run.proc.returncode, "".join(run.out), run.stopped)
        else:
            report = None
        if report is None:
            out.append(f"<<<PAF-AGENT {run.name}: fallback — {run.reason}>>>")
        else:
            out.append(f"<<<PAF-AGENT {run.name}: headless>>>")
            out.append(report.rstrip("\n"))
    print("\n".join(out))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Start PAF agents as headless claude -p runs.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("probe", help="report whether headless runs are available, and the Bash timeout limit")
    run = sub.add_parser("run", help="start the agents on stdin side by side and print their reports")
    run.add_argument("--session", required=True, help="the parent session id, to price the runs into its run")
    args = parser.parse_args()
    return cmd_probe(args) if args.command == "probe" else cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
