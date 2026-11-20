"""Tests for skills/paf-shared/paf-headless.py.

The helper starts `claude` processes and signals them, so it runs as a subprocess
against a stub `claude` placed first on a temporary `PATH`. The stub logs its argv,
stdin and pid per agent, and behaves as the per-agent mode in its environment
says. `HOME` and `CLAUDE_CONFIG_DIR` point at temporary directories holding the
agent files, so no real config, ledger or session is touched.
"""

import json
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from tests.support import HEADLESS, load_module

STUB = textwrap.dedent(r'''
    #!{python}
    import json, os, signal, sys, time
    args = sys.argv[1:]
    agent = args[args.index("--agent") + 1]
    log = os.path.join(os.environ["STUB_LOG"], agent + ".json")
    prompt = sys.stdin.read()
    with open(log, "w") as fh:
        json.dump({{"argv": args, "stdin": prompt, "pid": os.getpid()}}, fh)
    mode = os.environ.get("STUB_MODE_" + agent.replace("-", "_"), "ok")
    report = "```yaml\nagent: \"%s\"\nstatus: \"success\"\nsummary: |\n  ok\nissues: []\n```" % agent
    result = {{"type": "result", "is_error": False, "result": report, "permission_denials": []}}
    if mode == "hang":
        time.sleep(120)
    elif mode == "trap":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        time.sleep(120)
    elif mode == "grandchild":
        import subprocess
        child = subprocess.Popen(["sleep", "120"])
        with open(os.path.join(os.environ["STUB_LOG"], "grandchild.pid"), "w") as fh:
            fh.write(str(child.pid))
        time.sleep(120)
    elif mode == "big":
        result["result"] = "x" * 300000 + "\n" + report
        print(json.dumps(result))
    elif mode == "exit1":
        sys.exit(1)
    elif mode == "badjson":
        print("not json")
    elif mode == "iserror":
        result["is_error"] = True
        print(json.dumps(result))
    elif mode == "denied":
        result["permission_denials"] = [{{"tool_name": "Read", "tool_input": {{"file_path": "/etc/x"}}}}]
        print(json.dumps(result))
    elif mode == "noyaml":
        result["result"] = "no report here"
        print(json.dumps(result))
    else:
        print(json.dumps(result))
''').lstrip()

AGENT_FILE = "---\nname: {name}\ndescription: x\nmodel: sonnet\ntools: {tools}\n---\n\nBody.\n"


class HeadlessTestCase(unittest.TestCase):
    SESSION = "parent-session-1"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(os.path.realpath(tmp.name))
        self.bin = self.root / "bin"
        self.log = self.root / "log"
        self.home = self.root / "home"
        self.config = self.root / "config"
        self.work = self.root / "work"
        for d in (self.bin, self.log, self.home, self.config / "agents" / "paf", self.work):
            d.mkdir(parents=True)
        stub = self.bin / "claude"
        stub.write_text(STUB.format(python=sys.executable))
        stub.chmod(0o755)
        for name, tools in (("code-simplifier", "Read"), ("security-engineer", "Read"),
                            ("implementation-verifier", "Read, Bash"),
                            ("issue-validator", "Read, Grep, Glob, WebSearch, WebFetch"),
                            ("quality-assurer", "Read")):
            (self.config / "agents" / "paf" / f"{name}.md").write_text(AGENT_FILE.format(name=name, tools=tools))
        self.env = {
            "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}",
            "HOME": str(self.home),
            "CLAUDE_CONFIG_DIR": str(self.config),
            "STUB_LOG": str(self.log),
        }

    def block(self, *agents):
        return "".join(f"<<<PAF-AGENT {a}>>>\nReview prompt for {a}.\n" for a in agents)

    def run_helper(self, stdin, *args, env=None, cwd=None):
        return subprocess.run(
            [sys.executable, str(HEADLESS), *(args or ("run", "--session", self.SESSION))],
            input=stdin, capture_output=True, text=True, env={**self.env, **(env or {})},
            cwd=cwd or self.work, timeout=60,
        )

    def stub_log(self, agent):
        return json.loads((self.log / f"{agent}.json").read_text())

    def wait_for_log(self, agent, seconds=15):
        path = self.log / f"{agent}.json"
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if path.exists() and path.read_text():
                return self.stub_log(agent)
            time.sleep(0.1)
        self.fail(f"stub for {agent} never started")

    def assert_gone(self, pid, seconds=15):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.2)
        self.fail(f"process {pid} is still running")


class ProbeTests(HeadlessTestCase):
    def probe(self, **env):
        return self.run_helper("", "probe", env=env).stdout.strip()

    def test_available_with_the_default_limit(self):
        self.assertEqual(self.probe(), "HEADLESS=available TIMEOUT_MS=600000")

    def test_the_larger_of_the_two_env_values_applies(self):
        self.assertEqual(self.probe(BASH_MAX_TIMEOUT_MS="900000"), "HEADLESS=available TIMEOUT_MS=900000")
        self.assertEqual(self.probe(BASH_MAX_TIMEOUT_MS="60000", BASH_DEFAULT_TIMEOUT_MS="300000"),
                         "HEADLESS=available TIMEOUT_MS=300000")

    def test_malformed_values_count_as_unset(self):
        self.assertEqual(self.probe(BASH_MAX_TIMEOUT_MS="ten", BASH_DEFAULT_TIMEOUT_MS="-5"),
                         "HEADLESS=available TIMEOUT_MS=600000")

    def test_unavailable_without_claude_on_path(self):
        out = self.run_helper("", "probe", env={"PATH": "/usr/bin:/bin"}).stdout.strip()
        self.assertEqual(out, "HEADLESS=unavailable — claude not found on PATH")


class RunTests(HeadlessTestCase):
    def test_parallel_runs_return_in_input_order(self):
        proc = self.run_helper(self.block("security-engineer", "code-simplifier"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = proc.stdout.splitlines()
        self.assertEqual(lines[0], "<<<PAF-AGENT security-engineer: headless>>>")
        second = lines.index("<<<PAF-AGENT code-simplifier: headless>>>")
        self.assertIn('agent: "security-engineer"', "\n".join(lines[:second]))
        self.assertIn('agent: "code-simplifier"', "\n".join(lines[second:]))

    def test_argv_carries_the_agent_permissions_and_its_tools(self):
        self.run_helper(self.block("implementation-verifier"))
        argv = self.stub_log("implementation-verifier")["argv"]
        self.assertEqual(argv[:4], ["-p", "--agent", "implementation-verifier", "--output-format"])
        self.assertIn("json", argv)
        for flag, value in (("--permission-mode", "dontAsk"), ("--permission-prompts", "none"),
                            ("--allowedTools", "Read,Bash")):
            self.assertEqual(argv[argv.index(flag) + 1], value)
        self.assertNotIn("--append-system-prompt", argv)  # not a git repository

    def test_each_run_gets_a_registered_session_id(self):
        self.run_helper(self.block("code-simplifier", "security-engineer"))
        ids = [self.stub_log(a)["argv"][self.stub_log(a)["argv"].index("--session-id") + 1]
               for a in ("code-simplifier", "security-engineer")]
        children = (self.home / ".claude" / "paf" / "costs" / ".marks" / f"{self.SESSION}.children")
        self.assertEqual(sorted(children.read_text().split()), sorted(ids))
        self.assertNotEqual(ids[0], ids[1])

    def test_the_prompt_reaches_stdin_verbatim(self):
        prompt = 'Line one with "quotes" and $HOME and `ticks`.\n\n  indented line\nlast'
        self.run_helper(f"<<<PAF-AGENT quality-assurer>>>\n{prompt}\n")
        self.assertEqual(self.stub_log("quality-assurer")["stdin"], prompt)

    def test_a_git_repository_gets_the_git_status_snapshot(self):
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.work, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-q",
                        "--allow-empty", "-m", "first"], cwd=self.work, check=True)
        subprocess.run(["git", "config", "user.name", "tester"], cwd=self.work, check=True)
        self.run_helper(self.block("code-simplifier"))
        argv = self.stub_log("code-simplifier")["argv"]
        snapshot = argv[argv.index("--append-system-prompt") + 1]
        self.assertTrue(snapshot.startswith("# gitStatus\n"))
        self.assertIn("Current branch: main", snapshot)
        self.assertIn("Status:\n(clean)", snapshot)
        self.assertIn("first", snapshot)
        self.assertIn("Git user: tester", snapshot)
        # A dirty status keeps the first line's leading space.
        (self.work / "f.txt").write_text("x")
        subprocess.run(["git", "add", "f.txt"], cwd=self.work, check=True)
        (self.work / "f.txt").write_text("y")
        self.run_helper(self.block("code-simplifier"))
        argv = self.stub_log("code-simplifier")["argv"]
        self.assertIn("Status:\nAM f.txt", argv[argv.index("--append-system-prompt") + 1])

    def fallback(self, mode, agent="code-simplifier", **env):
        proc = self.run_helper(self.block(agent), env={f"STUB_MODE_{agent.replace('-', '_')}": mode, **env})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout.strip()

    def test_failures_fall_back_without_printing_the_output(self):
        for mode, reason in (("exit1", "exit 1"), ("badjson", "output is not JSON"),
                             ("iserror", "is_error result"), ("denied", "permission denied (Read)"),
                             ("noyaml", "no yaml block")):
            with self.subTest(mode=mode):
                self.assertEqual(self.fallback(mode), f"<<<PAF-AGENT code-simplifier: fallback — {reason}>>>")

    def test_one_failure_does_not_affect_the_others(self):
        proc = self.run_helper(self.block("code-simplifier", "security-engineer"),
                               env={"STUB_MODE_code_simplifier": "exit1"})
        self.assertIn("<<<PAF-AGENT code-simplifier: fallback — exit 1>>>", proc.stdout)
        self.assertIn("<<<PAF-AGENT security-engineer: headless>>>", proc.stdout)

    def test_no_claude_on_path_falls_back(self):
        proc = self.run_helper(self.block("code-simplifier"), env={"PATH": "/usr/bin:/bin"})
        self.assertEqual(proc.stdout.strip(), "<<<PAF-AGENT code-simplifier: fallback — claude not found on PATH>>>")

    def test_unreadable_agent_tools_fall_back(self):
        (self.config / "agents" / "paf" / "code-simplifier.md").unlink()
        self.assertEqual(self.fallback("ok"), "<<<PAF-AGENT code-simplifier: fallback — agent tools unreadable>>>")

    def test_a_run_past_the_limit_is_stopped_and_falls_back(self):
        start = time.monotonic()
        out = self.fallback("hang", BASH_MAX_TIMEOUT_MS="2000", BASH_DEFAULT_TIMEOUT_MS="1000")
        self.assertLess(time.monotonic() - start, 2.0 + 5)
        self.assertEqual(out, "<<<PAF-AGENT code-simplifier: fallback — stopped before the Bash time limit>>>")
        self.assert_gone(self.stub_log("code-simplifier")["pid"])

    def test_a_run_that_ignores_sigterm_is_killed_after_the_grace(self):
        out = self.fallback("trap", BASH_MAX_TIMEOUT_MS="2000", BASH_DEFAULT_TIMEOUT_MS="1000")
        self.assertIn("stopped before the Bash time limit", out)
        self.assert_gone(self.stub_log("code-simplifier")["pid"])

    def test_a_stop_also_kills_the_processes_an_agent_started(self):
        self.fallback("grandchild", BASH_MAX_TIMEOUT_MS="2000", BASH_DEFAULT_TIMEOUT_MS="1000")
        self.assert_gone(int((self.log / "grandchild.pid").read_text()))

    def test_a_large_prompt_and_report_do_not_block(self):
        prompt = "p" * 300000
        proc = self.run_helper(f"<<<PAF-AGENT code-simplifier>>>\n{prompt}\n",
                               env={"STUB_MODE_code_simplifier": "big"})
        self.assertEqual(self.stub_log("code-simplifier")["stdin"], prompt)
        self.assertIn("<<<PAF-AGENT code-simplifier: headless>>>", proc.stdout)
        self.assertGreater(len(proc.stdout), 300000)

    def test_only_the_runs_still_going_at_the_limit_are_stopped(self):
        proc = self.run_helper(self.block("code-simplifier", "security-engineer"),
                               env={"STUB_MODE_code_simplifier": "hang",
                                    "BASH_MAX_TIMEOUT_MS": "2000", "BASH_DEFAULT_TIMEOUT_MS": "1000"})
        self.assertIn("<<<PAF-AGENT code-simplifier: fallback — stopped before the Bash time limit>>>", proc.stdout)
        self.assertIn("<<<PAF-AGENT security-engineer: headless>>>", proc.stdout)


class AgentToolsTests(unittest.TestCase):
    """agent_tools() and classify() on their own, and the helper against the shipped agents."""

    @classmethod
    def setUpClass(cls):
        cls.mod = load_module(HEADLESS, "paf_headless_under_test")

    def tools(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            agents = Path(tmp) / "agents" / "paf"
            agents.mkdir(parents=True)
            (agents / "x.md").write_text(text)
            old = os.environ.get("CLAUDE_CONFIG_DIR")
            os.environ["CLAUDE_CONFIG_DIR"] = tmp
            try:
                return self.mod.agent_tools("x")
            finally:
                if old is None:
                    del os.environ["CLAUDE_CONFIG_DIR"]
                else:
                    os.environ["CLAUDE_CONFIG_DIR"] = old

    def test_unreadable_tools_lines_give_none(self):
        for text in ("no frontmatter\ntools: Read\n", "---\nname: x\n---\n", "---\ntools:\n---\n",
                     "---\nname: x\n---\ntools: Read\n", "---\ntools: Bash(a, b), Read\n---\n", ""):
            with self.subTest(text=text):
                self.assertIsNone(self.tools(text))

    def test_tools_are_comma_joined(self):
        self.assertEqual(self.tools("---\ntools: Read, Grep ,Glob\n---\n"), "Read,Grep,Glob")

    def test_every_headless_agent_is_a_shipped_paf_agent_with_tools(self):
        guard = load_module(HEADLESS.parents[2] / "hooks" / "PreToolUse-agent-guard.py", "guard_for_headless")
        for name in self.mod.HEADLESS_AGENTS:
            with self.subTest(agent=name):
                self.assertIn(name, guard.PAF_AGENTS)
                text = (HEADLESS.parents[2] / "agents" / f"{name}.md").read_text()
                self.assertIsNotNone(self.tools(text))

    def test_classify_edge_cases(self):
        yaml_report = "```yaml\nagent: x\n```"
        def run(payload):
            return self.mod.classify(0, json.dumps(payload), False)
        self.assertEqual(run([1]), (None, "output is not JSON"))
        self.assertEqual(run({"result": yaml_report, "permission_denials": ["junk"]}),
                         (None, "permission denied (?)"))
        self.assertEqual(run({"result": yaml_report, "permission_denials": [{}]}),
                         (None, "permission denied (?)"))
        self.assertEqual(run({"result": yaml_report}), (yaml_report, None))


class InterruptTests(HeadlessTestCase):
    def start(self, argv):
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, text=True, cwd=self.work,
                                env={**self.env, "STUB_MODE_code_simplifier": "hang"})
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        return proc

    def test_a_signal_to_the_helper_stops_its_runs(self):
        for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            with self.subTest(signal=signum):
                proc = self.start([sys.executable, str(HEADLESS), "run", "--session", self.SESSION])
                proc.stdin.write(self.block("code-simplifier"))
                proc.stdin.close()
                pid = self.wait_for_log("code-simplifier")["pid"]
                proc.send_signal(signum)
                proc.wait(timeout=20)
                self.assert_gone(pid)
                (self.log / "code-simplifier.json").unlink()

    def test_killing_the_parent_shell_stops_its_runs(self):
        stdin = self.root / "in.txt"
        stdin.write_text(self.block("code-simplifier"))
        shell = self.start(["bash", "-c", f'"{sys.executable}" "{HEADLESS}" run --session {self.SESSION} < "{stdin}"'])
        shell.stdin.close()
        pid = self.wait_for_log("code-simplifier")["pid"]
        shell.kill()
        shell.wait(timeout=5)
        self.assert_gone(pid)


class UsageTests(HeadlessTestCase):
    def test_rejected_input(self):
        for stdin in ("", "text before any block\n", "<<<PAF-AGENT full-stack-dev>>>\nx\n",
                      "<<<PAF-AGENT unknown-agent>>>\nx\n", "<<<PAF-AGENT code-simplifier>>>\n\n"):
            with self.subTest(stdin=stdin):
                proc = self.run_helper(stdin)
                self.assertEqual(proc.returncode, 2)
                self.assertTrue(proc.stderr.startswith("ERROR:"))
                self.assertEqual(proc.stdout, "")

    def test_rejected_session(self):
        proc = self.run_helper(self.block("code-simplifier"), "run", "--session", "../x")
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
