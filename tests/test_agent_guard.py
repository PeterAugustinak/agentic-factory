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


class ShellSegmentsTests(unittest.TestCase):
    """Splitting a compound command into the pieces that actually run."""

    def test_single_command_is_one_segment(self):
        self.assertEqual(guard.shell_segments("grep -r foo ."), [["grep", "-r", "foo", "."]])

    def test_splits_on_operators(self):
        self.assertEqual(
            guard.shell_segments("cat x && python3 evil.py"),
            [["cat", "x"], ["python3", "evil.py"]],
        )

    def test_splits_on_semicolon_and_pipe(self):
        self.assertEqual(
            guard.shell_segments("grep foo . ; rm -rf /tmp/x | wc -l"),
            [["grep", "foo", "."], ["rm", "-rf", "/tmp/x"], ["wc", "-l"]],
        )

    def test_quoted_pipe_is_not_a_boundary(self):
        # The whole point of lexing with shlex: `|` inside a grep pattern is data.
        self.assertEqual(guard.shell_segments("grep -E 'foo|bar' ."), [["grep", "-E", "foo|bar", "."]])

    def test_command_substitution_becomes_its_own_segment(self):
        self.assertIn(["rm", "-rf", "/tmp/x"], guard.shell_segments("echo $(rm -rf /tmp/x)"))

    def test_newline_separates_commands(self):
        # shlex counts a newline as whitespace and never emits it as a token, so lines
        # are split before lexing — otherwise the second command hides as arguments to
        # the first.
        self.assertEqual(
            guard.shell_segments("grep foo .\npython3 evil.py"),
            [["grep", "foo", "."], ["python3", "evil.py"]],
        )

    def test_backslash_line_continuation_does_not_separate(self):
        self.assertEqual(
            guard.shell_segments("grep foo \\\n  bar.txt"), [["grep", "foo", "bar.txt"]]
        )

    def test_backtick_substitution_becomes_its_own_segment(self):
        # A backtick is an ordinary word character to shlex unless it is declared
        # punctuation, which is why PUNCTUATION_CHARS extends shlex's default set.
        self.assertIn(["rm", "-rf", "/tmp/x"], guard.shell_segments("cat `rm -rf /tmp/x`"))

    def test_merged_punctuation_operators_separate(self):
        # shlex returns a RUN of punctuation as one token, so `|&` and `<(` each arrive as
        # a single token that equals no named operator — the boundary rule is a property
        # of the token, not membership of a list.
        for command in ("grep x . |& python3 evil.py", "cat <(python3 evil.py)"):
            with self.subTest(command=command):
                self.assertIn(["python3", "evil.py"], guard.shell_segments(command))

    def test_input_redirection_does_not_separate(self):
        # Reading is read-only, so `<` stays inside its segment rather than starting one.
        self.assertEqual(guard.shell_segments("wc -l < file"), [["wc", "-l", "<", "file"]])

    def test_heredoc_operator_separates(self):
        # `<<` is deliberately not an input redirect: the body is checked, not trusted.
        self.assertEqual(guard.shell_segments("cat <<EOF"), [["cat"], ["EOF"]])

    def test_redirection_target_stays_in_the_segment(self):
        self.assertEqual(
            guard.shell_segments("echo pwned > /tmp/pwned.txt"),
            [["echo", "pwned", ">", "/tmp/pwned.txt"]],
        )

    def test_empty_command_has_no_segments(self):
        self.assertEqual(guard.shell_segments("   "), [])

    def test_unbalanced_quoting_returns_none(self):
        # Unparsable is not clearable — the caller must treat None as a violation.
        self.assertIsNone(guard.shell_segments("grep 'unbalanced"))


class ReadOnlyViolationTests(unittest.TestCase):
    """The read-only gate. Every payload in #41 is a regression test here."""

    def assertClean(self, cmd):
        self.assertEqual(guard.read_only_violation(cmd), "")

    def assertViolation(self, cmd):
        self.assertNotEqual(guard.read_only_violation(cmd), "")

    # --- legitimate read-only usage must keep working ------------------------

    def test_plain_read_only_command(self):
        self.assertClean("grep -r foo .")

    def test_pipeline_of_read_only_commands(self):
        self.assertClean("grep -r x . | head -20")

    def test_quoted_alternation_pattern(self):
        self.assertClean("grep -E 'foo|bar' src")

    def test_read_only_git_through_a_pipe(self):
        self.assertClean("git log --oneline | cat")

    def test_stderr_silenced_to_dev_null(self):
        self.assertClean("grep foo x 2>/dev/null")

    def test_stderr_duplicated_onto_stdout(self):
        self.assertClean("ls -la 2>&1 | head")

    def test_leading_env_assignment(self):
        self.assertClean("FOO=1 grep x .")

    def test_find_without_an_action(self):
        self.assertClean("find . -name '*.py' -type f")

    def test_tree_without_its_output_flag(self):
        self.assertClean("tree -L 2 src")

    def test_input_redirection(self):
        self.assertClean("wc -l < file")

    def test_file_descriptor_duplication_and_close(self):
        # `>&N` duplicates and `>&-` closes — neither touches the filesystem.
        self.assertClean("echo hi >&2")
        self.assertClean("grep x . >&-")

    def test_line_continuation(self):
        self.assertClean("grep foo \\\n  bar.txt")

    def test_backgrounding_a_read_only_command(self):
        self.assertClean("ls &")

    # --- the #41 bypasses ----------------------------------------------------

    def test_redirection_writes_a_file(self):
        self.assertViolation("echo pwned > /tmp/pwned.txt")

    def test_appending_redirection_writes_a_file(self):
        self.assertViolation("grep x . >> /tmp/out")

    def test_command_after_a_semicolon(self):
        self.assertViolation("grep foo . ; rm -rf /tmp/x")

    def test_command_after_and_and(self):
        self.assertViolation("cat x && python3 evil.py")

    def test_find_with_delete(self):
        self.assertViolation("find . -name x -delete")

    def test_find_with_exec(self):
        self.assertViolation("find . -name x -exec rm {} ;")

    # --- shell syntax the first fix still mis-tokenized -----------------------
    # Each of these reached `allow` after #41's first pass; they are the reason the
    # boundary rule became a property of the token rather than a list of operators.

    def test_command_after_a_newline(self):
        self.assertViolation("grep foo .\npython3 evil.py")

    def test_command_after_a_carriage_return(self):
        self.assertViolation("ls\rrm -rf /tmp/x")

    def test_backtick_substitution(self):
        self.assertViolation("cat `rm -rf /tmp/x`")

    def test_process_substitution(self):
        self.assertViolation("cat <(rm -rf /tmp/x)")
        self.assertViolation("echo hi >(tee /tmp/pwned)")

    def test_stderr_pipe_operator(self):
        self.assertViolation("grep x . |& python3 evil.py")

    def test_digit_target_is_a_filename_without_an_ampersand(self):
        # `> 1` writes a file literally named `1`; only `>&1` duplicates a descriptor.
        self.assertViolation("echo pwned > 2")
        self.assertViolation("grep x . >> 2")

    def test_clobbering_and_read_write_redirection(self):
        self.assertViolation("echo pwned >| /tmp/pwned.txt")
        self.assertViolation("grep x . <> /tmp/pwned.txt")

    def test_find_with_fprint0(self):
        # The null-separated sibling of -fprint, and just as much a file write.
        self.assertViolation("find . -fprint0 /tmp/pwned.txt")

    def test_tree_writing_to_its_own_output_file(self):
        # tree(1) -o writes the listing itself — no shell redirection to catch.
        self.assertViolation("tree -o /tmp/pwned.txt .")

    def test_heredoc_body_is_not_trusted(self):
        self.assertViolation("cat <<EOF")

    # --- other shapes that must not slip through -----------------------------

    def test_command_inside_a_substitution(self):
        self.assertViolation("echo $(rm -rf /tmp/x)")

    def test_non_read_only_command_at_the_end_of_a_pipeline(self):
        self.assertViolation("grep x . | tee /tmp/out")

    def test_redirection_before_the_command(self):
        self.assertViolation("> /tmp/pwned.txt echo hi")

    def test_redirection_with_no_target(self):
        self.assertViolation("echo hi >")

    def test_traversal_out_of_dev_null(self):
        self.assertViolation("echo x > /dev/null/../../tmp/pwned.txt")

    def test_unparsable_command(self):
        self.assertViolation("grep 'unbalanced")

    def test_empty_command(self):
        self.assertViolation("")


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

    # --- global options between `git` and the subcommand (#41) ---------------

    def test_matches_through_an_option_taking_a_separate_argument(self):
        self.assertTrue(guard.GIT_MUTATE.search("git -C /tmp commit -m x"))

    def test_matches_through_a_long_option(self):
        self.assertTrue(guard.GIT_MUTATE.search("git --no-pager push"))

    def test_matches_through_a_config_override(self):
        self.assertTrue(guard.GIT_MUTATE.search("git -c user.email=x commit -m y"))

    def test_matches_through_several_stacked_options(self):
        self.assertTrue(guard.GIT_MUTATE.search("git -C /tmp -c a=b push"))

    def test_matches_through_a_quoted_argument_containing_a_space(self):
        # `\S+` cannot span the space inside the quotes.
        self.assertTrue(guard.GIT_MUTATE.search('git -C "/tmp/my repo" commit -m x'))

    def test_matches_through_long_options_taking_a_separate_argument(self):
        # git accepts `--work-tree /tmp` as readily as `--work-tree=/tmp`.
        for command in (
            "git --work-tree /tmp commit -m y",
            "git --git-dir /tmp/x.git am patch.mbox",
            "git --namespace foo push",
        ):
            with self.subTest(command=command):
                self.assertTrue(guard.GIT_MUTATE.search(command))

    def test_matches_a_quoted_subcommand(self):
        self.assertTrue(guard.GIT_MUTATE.search('git "commit" -m x'))

    # --- subcommands that write files ----------------------------------------

    def test_matches_subcommands_that_write_files(self):
        for command in (
            "git archive -o /tmp/x.tar HEAD",
            "git bundle create /tmp/b HEAD",
            "git format-patch -o /tmp HEAD~1",
        ):
            with self.subTest(command=command):
                self.assertTrue(guard.GIT_MUTATE.search(command))

    # --- subcommands the original list omitted (#41) -------------------------

    def test_matches_am(self):
        self.assertTrue(guard.GIT_MUTATE.search("git am patch.mbox"))

    def test_matches_config(self):
        self.assertTrue(guard.GIT_MUTATE.search("git config user.name x"))

    def test_matches_submodule(self):
        self.assertTrue(guard.GIT_MUTATE.search("git submodule update --init"))

    def test_matches_worktree(self):
        self.assertTrue(guard.GIT_MUTATE.search("git worktree add /tmp/w"))

    def test_matches_update_ref(self):
        self.assertTrue(guard.GIT_MUTATE.search("git update-ref HEAD x"))

    def test_matches_gc(self):
        self.assertTrue(guard.GIT_MUTATE.search("git gc --prune=now"))

    # --- read-only git must stay allowed -------------------------------------

    def test_does_not_match_git_log(self):
        self.assertFalse(guard.GIT_MUTATE.search("git log --oneline -5"))

    def test_does_not_match_git_status(self):
        self.assertFalse(guard.GIT_MUTATE.search("git status --short"))

    def test_does_not_match_git_diff(self):
        self.assertFalse(guard.GIT_MUTATE.search("git diff develop"))

    def test_does_not_match_a_mutating_word_inside_an_option_value(self):
        # The option run is anchored right after `git`, so `log` ends it and the
        # `push` in --grep=push is never in subcommand position.
        self.assertFalse(guard.GIT_MUTATE.search("git log --grep=push HEAD"))

    def test_does_not_match_a_read_only_subcommand_behind_a_global_option(self):
        self.assertFalse(guard.GIT_MUTATE.search("git --no-pager log --stat"))
        self.assertFalse(guard.GIT_MUTATE.search("git -C /tmp diff"))

    def test_does_not_match_a_pathspec_naming_a_subcommand(self):
        self.assertFalse(guard.GIT_MUTATE.search("git log -- src/add.py"))

    def test_does_not_match_read_only_git_behind_a_separate_argument_option(self):
        # The widened option run must not swallow its way into a false positive.
        for command in (
            "git --work-tree /tmp status",
            "git --git-dir /tmp/x.git log --stat",
            "git show HEAD:src/add.py",
            "git rev-parse HEAD",
        ):
            with self.subTest(command=command):
                self.assertFalse(guard.GIT_MUTATE.search(command))


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

    def test_read_only_agent_allowed_pipeline_of_read_only_commands(self):
        self.assertEqual(
            self.run_hook({
                "agent_type": "code-explorer",
                "tool_name": "Bash",
                "tool_input": {"command": "grep -r foo . | head -20"},
            }),
            "allow",
        )

    def test_read_only_agent_denied_the_41_bypasses(self):
        # The four read-only-allowlist bypasses reported in #41, each of which the
        # first-word-only check cleared.
        for command in (
            "echo pwned > /tmp/pwned.txt",
            "grep foo . ; rm -rf /tmp/x",
            "cat x && python3 evil.py",
            "find . -name x -delete",
        ):
            with self.subTest(command=command):
                self.assertEqual(
                    self.run_hook({
                        "agent_type": "code-explorer",
                        "tool_name": "Bash",
                        "tool_input": {"command": command},
                    }),
                    "deny",
                )

    def test_read_only_agent_denied_the_mis_tokenized_shapes(self):
        # Shell syntax that reached `allow` after #41's first pass, driven end to end.
        for command in (
            "grep foo .\npython3 evil.py",
            "cat `rm -rf /tmp/x`",
            "cat <(rm -rf /tmp/x)",
            "grep x . |& python3 evil.py",
            "echo pwned > 2",
            "find . -fprint0 /tmp/pwned.txt",
            "tree -o /tmp/pwned.txt .",
        ):
            with self.subTest(command=command):
                self.assertEqual(
                    self.run_hook({
                        "agent_type": "code-explorer",
                        "tool_name": "Bash",
                        "tool_input": {"command": command},
                    }),
                    "deny",
                )

    def test_git_mutation_behind_a_global_option_is_denied_for_any_agent(self):
        # GIT_MUTATE is checked BEFORE the read-only branch, so this gap reached every
        # agent — including one that would otherwise land on the build/test allow (#41).
        for agent in ("code-explorer", "full-stack-dev"):
            for command in (
                "git -C /tmp commit -m x",
                "git --no-pager push",
                'git -C "/tmp/my repo" commit -m x',
                "git --work-tree /tmp commit -m y",
            ):
                with self.subTest(agent=agent, command=command):
                    self.assertEqual(
                        self.run_hook({
                            "agent_type": agent,
                            "tool_name": "Bash",
                            "tool_input": {"command": command},
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
