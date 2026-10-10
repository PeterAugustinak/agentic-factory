"""Tests for skills/paf-shared/paf-readiness.py.

Two seams. The pure logic — which project instruction files Claude Code loads,
version parsing, reading the Project instructions setting — is imported and
called directly against temporary directory trees. The checks themselves are
exercised by running the shipped script as a SUBPROCESS in a throwaway git
repository with a hermetic PATH: only the externals the script and `paf-vcs`
need, plus stub `gh`/`glab`/`claude` scripts, so no real CLI, network, or the
developer's own config is ever reached.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tests.support import READINESS, load_module

rd = load_module(READINESS, "paf_readiness")

TOOLS = ("bash", "git", "sed", "grep", "tail", "cat")

# `gh`/`glab` stub: `auth status` exits with $STUB_AUTH_RC.
VCS_STUB = '#!/bin/sh\nexit "${STUB_AUTH_RC:-0}"\n'
CLAUDE_STUB = '#!/bin/sh\necho "${STUB_CLAUDE_VERSION:-2.1.296} (Claude Code)"\n'


class Tree:
    """A temporary directory tree with a fake home."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = os.path.realpath(self._tmp.name)
        self.home = self.mkdir("home")

    def mkdir(self, rel):
        path = os.path.join(self.root, rel)
        os.makedirs(path, exist_ok=True)
        return path

    def write(self, rel, text="x\n"):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)
        return path


class ResolveInstructionsTests(Tree, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.proj = self.mkdir("proj")

    def resolve(self, mode=rd.DEFAULT_MODE, version=(2, 1, 296), launch=None, git_root=None, config_dir=None):
        return rd.resolve_instructions(launch or self.proj, config_dir or os.path.join(self.home, ".claude"),
                                       mode, version, git_root)

    def test_agents_only_loads_agents(self):
        agents = self.write("proj/AGENTS.md")
        r = self.resolve()
        self.assertEqual(r["loaded"], [agents])
        self.assertEqual(r["hidden"], [])

    def test_claude_only_loads_claude(self):
        claude = self.write("proj/CLAUDE.md")
        self.assertEqual(self.resolve()["loaded"], [claude])

    def test_nothing_loads_nothing(self):
        r = self.resolve()
        self.assertEqual((r["loaded"], r["hidden"]), ([], []))

    def test_each_hider_hides_agents(self):
        for hider in ("proj/CLAUDE.md", "proj/.claude/CLAUDE.md", "proj/CLAUDE.local.md", "CLAUDE.md"):
            with self.subTest(hider=hider):
                self.setUp()
                agents = self.write("proj/AGENTS.md")
                hider_path = self.write(hider)
                r = self.resolve()
                self.assertEqual(r["loaded"], [hider_path])
                self.assertEqual(r["hidden"], [agents])

    def test_dot_claude_agents_is_found(self):
        agents = self.write("proj/.claude/AGENTS.md")
        self.assertEqual(self.resolve()["loaded"], [agents])

    def test_user_memory_does_not_hide_agents(self):
        # Launching inside the home directory walks past ~/.claude/CLAUDE.md, which does not count.
        self.write("home/.claude/CLAUDE.md")
        agents = self.write("home/proj/AGENTS.md")
        r = self.resolve(launch=os.path.join(self.home, "proj"))
        self.assertEqual(r["loaded"], [agents])
        self.assertEqual(r["hidden"], [])

    def test_import_includes_agents(self):
        agents = self.write("proj/AGENTS.md")
        for text in ("@AGENTS.md\n", "See @./AGENTS.md for details\n"):
            with self.subTest(text=text):
                claude = self.write("proj/CLAUDE.md", text)
                r = self.resolve()
                self.assertEqual(r["loaded"], [claude])
                self.assertEqual(r["hidden"], [])

    def test_import_survives_trailing_punctuation(self):
        self.write("proj/AGENTS.md")
        for text in ("See @AGENTS.md.\n", "(see @AGENTS.md)\n", "Read @./AGENTS.md, then act\n"):
            with self.subTest(text=text):
                self.write("proj/CLAUDE.md", text)
                self.assertEqual(self.resolve()["hidden"], [])

    def test_import_is_followed_transitively_up_to_four_hops(self):
        self.write("proj/AGENTS.md")
        for here, nxt in (("CLAUDE.md", "a.md"), ("a.md", "b.md"), ("b.md", "c.md"), ("c.md", "AGENTS.md")):
            self.write(f"proj/{here}", f"@{nxt}\n")       # CLAUDE.md -> AGENTS.md is 4 hops
        self.assertEqual(self.resolve()["hidden"], [])
        self.write("proj/c.md", "@d.md\n")                # now 5 hops
        self.write("proj/d.md", "@AGENTS.md\n")
        self.assertEqual(len(self.resolve()["hidden"]), 1)

    def test_import_of_dot_claude_agents_and_home_expansion(self):
        agents = self.write("proj/.claude/AGENTS.md")
        self.write("proj/CLAUDE.md", "@.claude/AGENTS.md\n")
        self.assertEqual(self.resolve()["hidden"], [])
        os.unlink(agents)
        agents = self.write("home/shared/AGENTS.md")
        self.write("proj/CLAUDE.md", "@~/shared/AGENTS.md\n")
        with mock.patch.dict(os.environ, {"HOME": self.home}):
            self.assertEqual(rd.imports(os.path.join(self.proj, "CLAUDE.md")), {agents})

    def test_parent_agents_hidden_by_child_claude(self):
        parent_agents = self.write("AGENTS.md")
        self.write("proj/CLAUDE.md")
        r = self.resolve()
        self.assertEqual(r["hidden"], [parent_agents])          # no git root known: all counted
        r = self.resolve(git_root=self.proj)
        self.assertEqual((r["hidden"], r["outside"]), ([], [parent_agents]))

    def test_user_memory_follows_config_dir(self):
        cfg = self.mkdir("cfg")
        self.write("cfg/CLAUDE.md")
        agents = self.write("cfg/proj/AGENTS.md")
        r = self.resolve(launch=os.path.join(cfg, "proj"), config_dir=cfg)
        self.assertEqual((r["loaded"], r["hidden"]), ([agents], []))

    def test_import_in_code_is_not_an_import(self):
        agents = self.write("proj/AGENTS.md")
        for text in ("Mention `@AGENTS.md` literally\n", "```\n@AGENTS.md\n```\n", "mail me@AGENTS.md\n"):
            with self.subTest(text=text):
                self.write("proj/CLAUDE.md", text)
                self.assertEqual(self.resolve()["hidden"], [agents])

    def test_symlinked_claude_includes_agents(self):
        agents = self.write("proj/AGENTS.md")
        os.symlink("AGENTS.md", os.path.join(self.proj, "CLAUDE.md"))
        self.assertEqual(self.resolve()["hidden"], [])

    def test_modes(self):
        agents = self.write("proj/AGENTS.md")
        claude = self.write("proj/CLAUDE.md")
        self.assertEqual(self.resolve("claude-md-and-agents-md")["loaded"], [claude, agents])
        self.assertEqual(self.resolve("claude-md-and-agents-md")["hidden"], [])
        self.assertEqual(self.resolve("claude-md")["loaded"], [claude])
        self.assertEqual(self.resolve("managed-only")["loaded"], [])
        self.assertEqual(self.resolve("managed-only")["hidden"], [agents])

    def test_claude_md_mode_hides_agents_only_project(self):
        agents = self.write("proj/AGENTS.md")
        r = self.resolve("claude-md")
        self.assertEqual((r["loaded"], r["hidden"]), ([], [agents]))

    def test_old_version_reads_claude_md_only(self):
        agents = self.write("proj/AGENTS.md")
        r = self.resolve(version=(2, 1, 276))
        self.assertEqual((r["loaded"], r["hidden"]), ([], [agents]))
        self.assertEqual(self.resolve(version=(2, 1, 277))["loaded"], [agents])


class DetectLaunchDirTests(Tree, unittest.TestCase):
    def setUp(self):
        super().setUp()
        if not (os.path.isdir("/proc/self") or shutil.which("lsof")):
            self.skipTest("neither /proc nor lsof available")

    def detect(self, pid):
        with mock.patch.dict(os.environ, {"CLAUDE_PID": str(pid)}):
            return rd.detect_launch_dir()

    def test_reads_the_cwd_of_the_pid(self):
        sub = self.mkdir("sub")
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], cwd=sub)
        self.addCleanup(child.wait)
        self.addCleanup(child.kill)
        directory, verified = self.detect(child.pid)
        self.assertEqual((os.path.realpath(directory), verified), (sub, True))

    def test_own_pid(self):
        directory, verified = self.detect(os.getpid())
        self.assertEqual((os.path.realpath(directory), verified), (os.path.realpath(os.getcwd()), True))

    def test_unusable_pid_falls_back_unverified(self):
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        for pid in ("not-a-number", "", str(dead.pid)):
            with self.subTest(pid=pid):
                self.assertEqual(self.detect(pid), (os.getcwd(), False))


class VersionAndModeTests(Tree, unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(rd.parse_version("2.1.296 (Claude Code)\n"), (2, 1, 296))
        self.assertIsNone(rd.parse_version("claude: command not found"))
        self.assertIsNone(rd.parse_version(""))

    def settings(self, data):
        self.write("home/.claude/settings.json", data)
        return rd.read_mode(os.path.join(self.home, ".claude"))

    def test_mode_default_without_settings(self):
        self.assertEqual(rd.read_mode(os.path.join(self.home, ".claude")), rd.DEFAULT_MODE)

    def test_mode_from_either_plugin_id(self):
        for plugin_id in rd.PLUGIN_IDS:
            with self.subTest(plugin_id=plugin_id):
                text = '{"pluginConfigs": {"%s": {"options": {"instructionFiles": "claude-md"}}}}' % plugin_id
                self.assertEqual(self.settings(text), "claude-md")

    def test_mode_malformed_falls_back_to_default(self):
        for text in ("not json", "[]", '{"pluginConfigs": []}',
                     '{"pluginConfigs": {"cc-plugin-agents-md@builtin": {"options": {"instructionFiles": "bogus"}}}}'):
            with self.subTest(text=text):
                self.assertEqual(self.settings(text), rd.DEFAULT_MODE)


class ReadinessRunTests(Tree, unittest.TestCase):
    """The shipped script, end to end, in a hermetic sandbox."""

    def setUp(self):
        super().setUp()
        self.tools = self.mkdir("tools")
        self.stubs = self.mkdir("stubs")
        self.repo = self.mkdir("repo")
        for tool in TOOLS:
            real = shutil.which(tool)
            if real is None:
                self.skipTest(f"{tool} not found on PATH")
            os.symlink(real, os.path.join(self.tools, tool))
        os.symlink(sys.executable, os.path.join(self.tools, "python3"))
        if shutil.which("lsof"):                      # macOS reads the launch dir through lsof
            os.symlink(shutil.which("lsof"), os.path.join(self.tools, "lsof"))
        for name, body in (("gh", VCS_STUB), ("glab", VCS_STUB), ("claude", CLAUDE_STUB)):
            path = os.path.join(self.stubs, name)
            with open(path, "w") as fh:
                fh.write(body)
            os.chmod(path, 0o755)
        self.stub_env = {}
        self.git("init", "-q", "-b", "develop")
        self.git("-c", "user.name=t", "-c", "user.email=t@example.com",
                 "commit", "-q", "--allow-empty", "-m", "init")
        self.git("remote", "add", "origin", "https://github.com/o/r.git")
        self.write("repo/CLAUDE.md", "# project\n")

    def env(self):
        env = {
            "PATH": f"{self.stubs}{os.pathsep}{self.tools}",
            "HOME": self.home,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CEILING_DIRECTORIES": self.root,
        }
        env.update(self.stub_env)
        return env

    def git(self, *args):
        subprocess.run(["git", "-C", self.repo, *args], env={**self.env(), "PATH": self.tools},
                       check=True, capture_output=True)

    def run_check(self, *args, launch=None, use_launch=True):
        argv = [sys.executable, str(READINESS), *args]
        if use_launch:
            argv += ["--launch-dir", launch or self.repo]
        proc = subprocess.run(argv, cwd=self.repo, env=self.env(), capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def status(self, out, name):
        for line in out.splitlines():
            parts = line.split(" ", 3)
            if parts[:2] == ["CHECK", name]:
                return parts[2]
        self.fail(f"no CHECK {name} line in:\n{out}")

    def test_ready_repo(self):
        out = self.run_check("--base", "develop")
        for name in ("git-repo", "origin", "vcs-cli", "python3", "claude-version",
                     "base-branch", "launch-root", "instructions"):
            self.assertEqual(self.status(out, name), "ok", f"{name}:\n{out}")
        self.assertIn("VERDICT=ready", out)
        self.assertIn(f"INSTRUCTIONS_LOADED={os.path.join(self.repo, 'CLAUDE.md')}", out)
        self.assertNotIn("REMEDY", out)

    def test_unauthenticated_gitlab_cli(self):
        self.git("remote", "set-url", "origin", "git@gitlab.com:o/r.git")
        self.stub_env["STUB_AUTH_RC"] = "1"
        out = self.run_check("--base", "develop")
        self.assertEqual(self.status(out, "origin"), "ok")
        self.assertEqual(self.status(out, "vcs-cli"), "fail")
        self.assertIn("REMEDY vcs-cli 'glab' is not authenticated", out)
        self.assertIn("VERDICT=not-ready", out)

    def test_unsupported_host(self):
        self.git("remote", "set-url", "origin", "https://git.example.com/o/r.git")
        out = self.run_check("--base", "develop")
        self.assertEqual(self.status(out, "origin"), "fail")
        self.assertEqual(self.status(out, "vcs-cli"), "skip")
        self.assertIn("VERDICT=not-ready", out)

    def test_missing_cli(self):
        os.unlink(os.path.join(self.stubs, "gh"))
        out = self.run_check("--base", "develop")
        self.assertEqual(self.status(out, "vcs-cli"), "fail")
        self.assertIn("required but not installed", out)

    def test_claude_versions(self):
        cases = {"2.1.276": "fail", "2.1.277": "warn", "2.1.281": "ok", "garbage": "warn"}
        for version, expected in cases.items():
            with self.subTest(version=version):
                self.stub_env["STUB_CLAUDE_VERSION"] = version
                out = self.run_check("--base", "develop")
                self.assertEqual(self.status(out, "claude-version"), expected)
                self.assertIn("VERDICT=" + ("not-ready" if expected == "fail" else "ready"), out)

    def test_claude_missing_warns(self):
        os.unlink(os.path.join(self.stubs, "claude"))
        self.assertEqual(self.status(self.run_check("--base", "develop"), "claude-version"), "warn")

    def test_base_branch(self):
        out = self.run_check()
        self.assertEqual(self.status(out, "base-branch"), "skip")
        self.assertIn("VERDICT=ready", out)
        out = self.run_check("--base", "main")
        self.assertEqual(self.status(out, "base-branch"), "fail")
        self.assertIn("VERDICT=not-ready", out)

    def test_base_branch_on_origin_only(self):
        self.git("update-ref", "refs/remotes/origin/release", "HEAD")
        self.assertEqual(self.status(self.run_check("--base", "release"), "base-branch"), "ok")

    def test_hostile_or_empty_base_is_a_usage_error(self):
        marker = os.path.join(self.root, "pwned")
        for value in (f"--output={marker}", "", " ", "main$(touch x)", "a b", "`id`", "a;b", "-x"):
            with self.subTest(base=value):
                proc = subprocess.run([sys.executable, str(READINESS), f"--base={value}",
                                       "--launch-dir", self.repo], cwd=self.repo, env=self.env(),
                                      capture_output=True, text=True)
                self.assertNotEqual(proc.returncode, 0)
                self.assertNotIn("VERDICT", proc.stdout)
        self.assertFalse(os.path.exists(marker))

    def test_ordinary_base_names_are_accepted(self):
        for value in ("develop", "release/1.2", "feature/77-x_y.z"):
            with self.subTest(base=value):
                self.assertIn("CHECK base-branch", self.run_check(f"--base={value}"))

    def test_python3_missing(self):
        os.unlink(os.path.join(self.tools, "python3"))
        out = self.run_check("--base", "develop")
        self.assertEqual(self.status(out, "python3"), "fail")
        self.assertIn("VERDICT=not-ready", out)

    def test_lookalike_hosts_are_unsupported(self):
        for url in ("https://github.com.evil.example/o/r.git", "https://notgithub.com/o/r.git",
                    "git@gitlab.com.evil.example:o/r.git", "https://evilgitlab.com/o/r.git"):
            with self.subTest(url=url):
                self.git("remote", "set-url", "origin", url)
                self.assertEqual(self.status(self.run_check("--base", "develop"), "origin"), "fail")

    def test_unsupported_host_remedy_states_the_fix(self):
        self.git("remote", "set-url", "origin", "https://git.example.com/o/r.git")
        out = self.run_check("--base", "develop")
        self.assertIn("REMEDY origin unsupported VCS host", out)
        self.assertIn("Point origin at a github.com or gitlab.com repository", out)

    def test_skip_has_no_remedy(self):
        out = self.run_check()
        self.assertEqual(self.status(out, "base-branch"), "skip")
        self.assertNotIn("REMEDY base-branch", out)

    def test_summary_lines(self):
        out = self.run_check("--base", "develop")
        self.assertIn(f"LAUNCH_DIR={self.repo}", out)
        self.assertIn(f"GIT_ROOT={self.repo}", out)
        self.assertIn("AGENTS_HIDDEN=none", out)
        self.assertIn("INSTRUCTIONS_MODE=claude-md-or-agents-md", out)
        out = self.run_check(launch=self.mkdir("outside"))
        self.assertIn("GIT_ROOT=none", out)

    def test_agents_only_but_claude_md_mode_remedy_does_not_say_create_another(self):
        os.unlink(os.path.join(self.repo, "CLAUDE.md"))
        self.write("repo/AGENTS.md")
        cfg = self.mkdir("cfg")
        self.write("cfg/settings.json",
                   '{"pluginConfigs": {"cc-plugin-agents-md@builtin": '
                   '{"options": {"instructionFiles": "claude-md"}}}}')
        self.stub_env["CLAUDE_CONFIG_DIR"] = cfg
        out = self.run_check("--base", "develop")
        self.assertEqual(self.status(out, "instructions"), "fail")
        self.assertIn("an AGENTS.md exists but no project instructions file loads it", out)
        self.assertIn("containing the line `@AGENTS.md`", out)
        self.assertIn("Do not create another AGENTS.md", out)

    def test_agents_above_git_root_is_a_note_not_hidden(self):
        self.write("AGENTS.md")
        out = self.run_check("--base", "develop")
        self.assertEqual(self.status(out, "instructions"), "ok")
        self.assertIn("AGENTS_HIDDEN=none", out)
        self.assertIn("not loaded, above the git root", out)

    def test_launch_dir_from_claude_pid(self):
        sub = self.mkdir("repo/sub")
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], cwd=sub)
        self.addCleanup(child.wait)
        self.addCleanup(child.kill)
        self.stub_env["CLAUDE_PID"] = str(child.pid)
        out = self.run_check("--base", "develop", use_launch=False)
        self.assertIn(f"LAUNCH_DIR={sub}", out)
        self.assertEqual(self.status(out, "launch-root"), "fail")

    def test_launched_from_subdirectory(self):
        sub = self.mkdir("repo/sub")
        out = self.run_check("--base", "develop", launch=sub)
        self.assertEqual(self.status(out, "launch-root"), "fail")
        self.assertIn(f"REMEDY launch-root Quit and restart Claude Code from {self.repo}", out)

    def test_unverified_launch_dir_warns(self):
        self.stub_env["CLAUDE_PID"] = ""
        out = self.run_check("--base", "develop", use_launch=False)
        self.assertEqual(self.status(out, "launch-root"), "warn")
        self.assertIn("VERDICT=ready", out)

    def test_not_a_git_repo(self):
        outside = self.mkdir("outside")
        out = self.run_check(launch=outside)
        self.assertEqual(self.status(out, "git-repo"), "fail")
        for name in ("origin", "vcs-cli", "base-branch", "launch-root"):
            self.assertEqual(self.status(out, name), "skip")
        # The instructions check still runs.
        self.assertEqual(self.status(out, "instructions"), "fail")
        self.assertIn("VERDICT=not-ready", out)

    def test_hidden_agents_is_reported_not_env_failure(self):
        agents = self.write("repo/AGENTS.md")
        out = self.run_check("--base", "develop")
        self.assertEqual(self.status(out, "instructions"), "warn")
        self.assertIn(f"AGENTS_HIDDEN={agents}", out)
        self.assertIn("VERDICT=ready", out)

    def test_no_instructions_file(self):
        os.unlink(os.path.join(self.repo, "CLAUDE.md"))
        out = self.run_check("--base", "develop")
        self.assertEqual(self.status(out, "instructions"), "fail")
        self.assertIn("INSTRUCTIONS_LOADED=none", out)
        self.assertIn("VERDICT=ready", out)

    def test_mode_from_config_dir(self):
        cfg = self.mkdir("cfg")
        self.write("cfg/settings.json",
                   '{"pluginConfigs": {"cc-plugin-agents-md@builtin": '
                   '{"options": {"instructionFiles": "managed-only"}}}}')
        self.stub_env["CLAUDE_CONFIG_DIR"] = cfg
        out = self.run_check("--base", "develop")
        self.assertIn("INSTRUCTIONS_MODE=managed-only", out)
        self.assertEqual(self.status(out, "instructions"), "fail")
        self.assertIn("REMEDY instructions Set Project instructions back", out)


if __name__ == "__main__":
    unittest.main()
