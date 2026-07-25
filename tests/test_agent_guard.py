"""Tests for hooks/PreToolUse-agent-guard.py.

Two layers:

- The pure helpers (`command_name`, `within_project`) and the two deny regexes
  (`EXTERNAL_IO`, `GIT_MUTATE`) are imported and called directly.
- The allow/deny/defer decision is driven end to end by running the hook as a
  SUBPROCESS with a crafted payload on stdin. The hook is deliberately structured
  as a top-to-bottom, first-match-wins, emit-and-exit `main()` — auditable at a
  glance — and is not refactored into a testable `decide()` just to suit the
  tests, so the process boundary is the seam.

  Note the hook ALWAYS exits 0, whatever it decides (it emits nothing to defer).
  Assertions therefore read the emitted stdout JSON, never the exit code.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

from tests.support import AGENT_GUARD, load_module

guard = load_module(AGENT_GUARD, "agent_guard")


class CommandNameTests(unittest.TestCase):
    def test_plain_command(self):
        self.assertEqual(guard.command_name("grep foo"), "grep")

    def test_skips_leading_env_assignments(self):
        self.assertEqual(guard.command_name("FOO=1 BAR=2 grep foo"), "grep")

    def test_takes_basename_of_a_path(self):
        self.assertEqual(guard.command_name("/usr/bin/find . -name x"), "find")

    def test_strips_surrounding_quotes(self):
        self.assertEqual(guard.command_name("'ls' -la"), "ls")

    def test_leading_whitespace(self):
        self.assertEqual(guard.command_name("   cat file"), "cat")

    def test_empty_command(self):
        self.assertEqual(guard.command_name(""), "")

    def test_only_env_assignments(self):
        self.assertEqual(guard.command_name("FOO=1 BAR=2"), "")


class WithinProjectTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = os.path.realpath(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_relative_path_resolves_inside(self):
        self.assertTrue(guard.within_project("sub/file.txt", self.project))

    def test_absolute_path_inside(self):
        self.assertTrue(guard.within_project(os.path.join(self.project, "a.txt"), self.project))

    def test_project_root_itself(self):
        self.assertTrue(guard.within_project(self.project, self.project))

    def test_absolute_path_outside(self):
        self.assertFalse(guard.within_project("/etc/passwd", self.project))

    def test_traversal_escaping_the_project(self):
        self.assertFalse(guard.within_project("../outside.txt", self.project))

    def test_sibling_with_shared_prefix_is_outside(self):
        # `<project>-evil` must not count as inside `<project>` — the check appends
        # a separator precisely to rule this out.
        self.assertFalse(guard.within_project(self.project + "-evil/x", self.project))

    def test_empty_path(self):
        self.assertFalse(guard.within_project("", self.project))

    def test_symlink_inside_project_pointing_outside_is_rejected(self):
        # within_project() resolves symlinks via os.path.realpath(), so a link
        # that physically sits inside the project but resolves to a target
        # outside it must be treated as outside — the check has to see the
        # resolved target, not the link's own location.
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        outside_target = os.path.join(os.path.realpath(outside.name), "secret.txt")
        with open(outside_target, "w") as f:
            f.write("secret")
        link_path = os.path.join(self.project, "escape_link")
        os.symlink(outside_target, link_path)
        self.assertFalse(guard.within_project(link_path, self.project))


class ExternalIoRegexTests(unittest.TestCase):
    def test_matches_gh(self):
        self.assertTrue(guard.EXTERNAL_IO.search("gh issue view 38"))

    def test_matches_curl(self):
        self.assertTrue(guard.EXTERNAL_IO.search("curl -sSL https://example.com"))

    def test_matches_paf_vcs(self):
        self.assertTrue(guard.EXTERNAL_IO.search("paf-vcs view-issue 38"))

    def test_matches_absolute_path_to_curl(self):
        self.assertTrue(guard.EXTERNAL_IO.search("/usr/bin/curl https://example.com"))

    def test_matches_inside_a_pipeline(self):
        self.assertTrue(guard.EXTERNAL_IO.search("cat x | wget -i -"))

    def test_does_not_match_a_longer_word(self):
        self.assertFalse(guard.EXTERNAL_IO.search("github-actions --help"))

    def test_does_not_match_an_unrelated_command(self):
        self.assertFalse(guard.EXTERNAL_IO.search("grep -r foo ."))


class GitMutateRegexTests(unittest.TestCase):
    def test_matches_commit(self):
        self.assertTrue(guard.GIT_MUTATE.search("git commit -m 'x'"))

    def test_matches_push(self):
        self.assertTrue(guard.GIT_MUTATE.search("git push origin main"))

    def test_matches_checkout(self):
        self.assertTrue(guard.GIT_MUTATE.search("git checkout -b feature/1-x"))

    def test_matches_inside_a_compound_command(self):
        self.assertTrue(guard.GIT_MUTATE.search("cd /tmp && git add ."))

    def test_does_not_match_git_log(self):
        self.assertFalse(guard.GIT_MUTATE.search("git log --oneline -5"))

    def test_does_not_match_git_status(self):
        self.assertFalse(guard.GIT_MUTATE.search("git status --short"))

    def test_does_not_match_git_diff(self):
        self.assertFalse(guard.GIT_MUTATE.search("git diff develop"))


class HookDecisionTests(unittest.TestCase):
    """Drives the hook as a subprocess and asserts on its emitted decision."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = os.path.realpath(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def run_hook(self, payload):
        """Return the emitted permissionDecision, or None when the hook defers.

        The environment is built explicitly rather than inherited so an ambient
        CLAUDE_PROJECT_DIR from the real session cannot leak into the assertions.
        """
        env = {
            "PATH": os.environ.get("PATH", ""),
            "CLAUDE_PROJECT_DIR": self.project,
        }
        stdin = payload if isinstance(payload, str) else json.dumps(payload)
        proc = subprocess.run(
            [sys.executable, str(AGENT_GUARD)],
            input=stdin,
            capture_output=True,
            text=True,
            env=env,
        )
        out = proc.stdout.strip()
        if not out:
            return None  # defer — the hook emits nothing
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"]

    # --- main thread ---------------------------------------------------------

    def test_main_thread_is_allowed(self):
        # Main-thread identity is the ABSENCE of agent_type, not a falsy value.
        self.assertEqual(
            self.run_hook({"tool_name": "Bash", "tool_input": {"command": "gh issue view 1"}}),
            "allow",
        )

    def test_main_thread_compound_command_is_allowed(self):
        self.assertEqual(
            self.run_hook({"tool_name": "Bash", "tool_input": {"command": "cd /tmp && git commit -m x"}}),
            "allow",
        )

    def test_empty_agent_type_falls_into_the_restricted_branch(self):
        # A key present but empty must fail safe as an agent, not as main thread.
        self.assertEqual(
            self.run_hook({
                "agent_type": "",
                "tool_name": "Bash",
                "tool_input": {"command": "gh issue view 1"},
            }),
            "deny",
        )

    # --- agents: Bash --------------------------------------------------------

    def test_agent_external_io_is_denied(self):
        self.assertEqual(
            self.run_hook({
                "agent_type": "full-stack-dev",
                "tool_name": "Bash",
                "tool_input": {"command": "curl https://example.com"},
            }),
            "deny",
        )

    def test_agent_git_mutation_is_denied(self):
        self.assertEqual(
            self.run_hook({
                "agent_type": "full-stack-dev",
                "tool_name": "Bash",
                "tool_input": {"command": "git commit -m 'x'"},
            }),
            "deny",
        )

    def test_read_only_agent_allowed_read_only_command(self):
        self.assertEqual(
            self.run_hook({
                "agent_type": "code-explorer",
                "tool_name": "Bash",
                "tool_input": {"command": "grep -r foo ."},
            }),
            "allow",
        )

    def test_read_only_agent_denied_non_read_only_command(self):
        self.assertEqual(
            self.run_hook({
                "agent_type": "code-explorer",
                "tool_name": "Bash",
                "tool_input": {"command": "python3 script.py"},
            }),
            "deny",
        )

    def test_read_only_agent_denied_empty_command(self):
        self.assertEqual(
            self.run_hook({
                "agent_type": "implementation-planner",
                "tool_name": "Bash",
                "tool_input": {"command": ""},
            }),
            "deny",
        )

    def test_build_agent_allowed_build_command(self):
        self.assertEqual(
            self.run_hook({
                "agent_type": "implementation-verifier",
                "tool_name": "Bash",
                "tool_input": {"command": "python3 -m unittest"},
            }),
            "allow",
        )

    # --- agents: web ---------------------------------------------------------

    def test_agent_web_fetch_is_allowed(self):
        self.assertEqual(
            self.run_hook({
                "agent_type": "issue-validator",
                "tool_name": "WebFetch",
                "tool_input": {"url": "https://code.claude.com/docs"},
            }),
            "allow",
        )

    def test_agent_web_search_is_allowed(self):
        self.assertEqual(
            self.run_hook({
                "agent_type": "issue-validator",
                "tool_name": "WebSearch",
                "tool_input": {"query": "claude code hooks"},
            }),
            "allow",
        )

    # --- agents: writes ------------------------------------------------------

    def test_agent_write_inside_project_is_allowed(self):
        self.assertEqual(
            self.run_hook({
                "agent_type": "full-stack-dev",
                "tool_name": "Write",
                "tool_input": {"file_path": os.path.join(self.project, "a.py")},
            }),
            "allow",
        )

    def test_agent_write_outside_project_is_denied(self):
        self.assertEqual(
            self.run_hook({
                "agent_type": "full-stack-dev",
                "tool_name": "Edit",
                "tool_input": {"file_path": "/etc/passwd"},
            }),
            "deny",
        )

    def test_agent_write_without_a_path_defers(self):
        self.assertIsNone(
            self.run_hook({
                "agent_type": "full-stack-dev",
                "tool_name": "Write",
                "tool_input": {},
            })
        )

    # --- defers --------------------------------------------------------------

    def test_unrecognised_tool_defers(self):
        self.assertIsNone(
            self.run_hook({
                "agent_type": "full-stack-dev",
                "tool_name": "Read",
                "tool_input": {"file_path": "/etc/passwd"},
            })
        )

    def test_malformed_json_defers(self):
        self.assertIsNone(self.run_hook("{not json"))

    def test_non_object_json_defers(self):
        self.assertIsNone(self.run_hook("[1, 2, 3]"))


if __name__ == "__main__":
    unittest.main()
