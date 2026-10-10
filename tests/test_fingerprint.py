"""Tests for skills/paf-shared/paf-fingerprint.py.

Every test runs the shipped script as a SUBPROCESS against a real, throwaway git
repository — the fingerprint is defined by what git reports, so a fake git would
test nothing. `HOME` is pointed at a temporary directory, so the record lands
under a scratch `~/.claude` and the real one is never touched; git's global and
system config are disabled so the developer's own config cannot leak in.

The fixture mimics an `implement-issue` hand-off: `develop` holds the base commit,
and the feature branch carries an uncommitted modification, a deletion, a new
untracked file (with a space in its name), and an ignored file.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.support import FINGERPRINT

ISSUE = "63"


class FingerprintTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.home = tmp / "home"
        self.home.mkdir()
        self.repo = tmp / "repo"
        self.repo.mkdir()
        self.env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(self.home),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
        }
        self.git("init", "-q", "-b", "develop")
        self.write("app.py", "print('base')\n")
        self.write("gone.py", "old\n")
        self.write("keep.py", "keep\n")
        self.write(".gitignore", "*.log\n")
        (self.repo / "sub").mkdir()
        self.write("sub/mod.py", "mod\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "feature/63-x")
        # The implementation, left uncommitted as implement-issue hands it off.
        self.write("app.py", "print('feature')\n")
        (self.repo / "gone.py").unlink()
        self.write("new file.py", "new\n")
        self.write("debug.log", "noise\n")

    def tearDown(self):
        self._tmp.cleanup()

    # --- helpers -------------------------------------------------------------

    def git(self, *args, cwd=None):
        subprocess.run(["git", *args], cwd=cwd or self.repo, env=self.env, check=True,
                       capture_output=True)

    def write(self, rel, text):
        (self.repo / rel).write_text(text)

    def run_helper(self, *args, cwd=None):
        return subprocess.run(
            [sys.executable, str(FINGERPRINT), *args],
            cwd=cwd or self.repo, env=self.env, capture_output=True, text=True,
        )

    def record(self, issue=ISSUE, cwd=None):
        proc = self.run_helper("record", "--issue", issue, "--base", "develop", cwd=cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("FINGERPRINT=recorded", proc.stdout)
        return proc

    def verdict(self, cwd=None, issue=ISSUE):
        proc = self.run_helper("check", "--issue", issue, cwd=cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = proc.stdout.splitlines()
        self.assertEqual(len([l for l in lines if l.startswith("VERDICT=")]), 1, proc.stdout)
        return lines[0], proc.stdout

    def assertSkip(self, cwd=None, issue=ISSUE):
        v, out = self.verdict(cwd, issue)
        self.assertEqual(v, "VERDICT=skip", out)

    def assertReview(self, reason_fragment=None, issue=ISSUE):
        v, out = self.verdict(issue=issue)
        self.assertEqual(v, "VERDICT=review", out)
        if reason_fragment:
            self.assertIn(reason_fragment, out)

    def record_files(self):
        return list((self.home / ".claude" / "paf" / "fingerprints").rglob("*.json"))

    # --- no content change: skip -------------------------------------------

    def test_untouched_handoff_matches(self):
        self.record()
        self.assertSkip()

    def test_record_lives_under_home_claude_not_the_repo(self):
        self.record()
        self.assertEqual(len(self.record_files()), 1)
        self.assertFalse(any(p.suffix == ".json" for p in self.repo.rglob("*")))

    def test_commit_without_content_change_still_matches(self):
        self.record()
        self.git("add", "-A")  # stages the untracked file too: it moves to tracked
        self.git("commit", "-q", "-m", "review commit")
        self.assertSkip()

    def test_staging_only_still_matches(self):
        self.record()
        self.git("add", "-A")
        self.assertSkip()

    def test_rename_matches_committed_or_not_whatever_rename_config(self):
        self.git("mv", "keep.py", "kept.py")
        self.git("config", "diff.renames", "copies")
        self.record()
        self.assertSkip()
        self.git("commit", "-q", "-m", "rename")
        self.assertSkip()

    def test_rename_records_both_paths(self):
        self.git("mv", "keep.py", "kept.py")
        self.git("config", "diff.renames", "copies")
        self.record()
        self.assertIn("keep.py", self.record_files()[0].read_text())
        self.assertIn("kept.py", self.record_files()[0].read_text())
        self.write("keep.py", "keep\n")  # old path back with its old content
        self.assertReview()

    def test_diff_relative_config_does_not_affect_the_fingerprint(self):
        self.git("config", "diff.relative", "true")
        self.record(cwd=self.repo / "sub")
        self.assertIn("app.py", self.record_files()[0].read_text())
        self.assertSkip(cwd=self.repo / "sub")
        self.assertSkip()

    def test_base_ref_moving_after_record_does_not_matter(self):
        self.record()
        self.git("stash", "-u", "-q")
        self.git("checkout", "-q", "develop")
        self.write("upstream.py", "x\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "upstream moves")
        self.git("checkout", "-q", "feature/63-x")
        self.git("stash", "pop", "-q")
        self.assertSkip()

    def test_check_from_a_subdirectory_uses_the_repo_root(self):
        self.record()
        self.assertSkip(cwd=self.repo / "sub")

    def test_record_from_a_subdirectory_is_the_same_record(self):
        self.record(cwd=self.repo / "sub")
        self.assertEqual(len(self.record_files()), 1)
        self.assertSkip()

    def test_issues_are_recorded_and_cleared_independently(self):
        self.record(issue="63")
        self.write("app.py", "print('second state')\n")
        self.record(issue="64")
        self.assertSkip(issue="64")
        self.assertReview(issue="63")
        proc = self.run_helper("clear", "--issue", "64")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertReview("no hand-off fingerprint", issue="64")
        self.write("app.py", "print('feature')\n")
        self.assertSkip(issue="63")

    def test_ignored_file_change_matches(self):
        self.record()
        self.write("debug.log", "more noise\n")
        self.write("other.log", "x\n")
        self.assertSkip()

    def test_rerecord_supersedes_the_previous_fingerprint(self):
        self.record()
        self.write("app.py", "print('re-run')\n")
        self.assertReview()
        self.record()
        self.assertSkip()
        self.assertEqual(len(self.record_files()), 1)

    # --- any content change: review ----------------------------------------

    def test_uncommitted_tracked_edit_mismatches(self):
        self.record()
        self.write("app.py", "print('hand edit')\n")
        self.assertReview("1 path(s)")

    def test_committed_tracked_edit_mismatches(self):
        self.record()
        self.write("app.py", "print('hand edit')\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "hand edit")
        self.assertReview("content changed")

    def test_edit_to_an_untouched_tracked_file_mismatches(self):
        self.record()
        self.write("sub/mod.py", "edited\n")
        self.assertReview()

    def test_untracked_file_edit_mismatches(self):
        self.record()
        self.write("new file.py", "edited\n")
        self.assertReview()

    def test_new_untracked_file_mismatches(self):
        self.record()
        self.write("extra.py", "x\n")
        self.assertReview()

    def test_restoring_a_deleted_file_mismatches(self):
        self.record()
        self.write("gone.py", "old\n")
        self.assertReview()

    def test_deleting_a_new_file_mismatches(self):
        self.record()
        (self.repo / "new file.py").unlink()
        self.assertReview()

    def test_reverting_an_implemented_change_to_base_mismatches(self):
        self.record()
        self.write("app.py", "print('base')\n")
        self.assertReview()

    def test_exec_bit_change_mismatches(self):
        self.record()
        os.chmod(self.repo / "app.py", 0o755)
        self.assertReview()

    def test_symlink_retarget_mismatches(self):
        os.symlink("app.py", self.repo / "link")
        self.record()
        self.assertSkip()
        (self.repo / "link").unlink()
        os.symlink("keep.py", self.repo / "link")
        self.assertReview()

    # --- missing / broken evidence fails safe ------------------------------

    def test_no_record_means_review(self):
        self.assertReview("no hand-off fingerprint")

    def test_corrupt_record_means_review(self):
        self.record()
        self.record_files()[0].write_text("{not json")
        self.assertReview("unreadable")

    def test_record_missing_keys_means_review(self):
        self.record()
        self.record_files()[0].write_text('{"base": "abc"}')
        self.assertReview("unreadable")

    def test_wrong_types_in_record_mean_review(self):
        self.record()
        for body in ('{"base": "%s", "paths": ["a"]}' % ("0" * 40),
                     '{"base": 5, "paths": {}}',
                     '{"base": "--all", "paths": {}}',
                     '{"base": "%s", "paths": {}}' % ("0" * 40 + "x")):
            with self.subTest(body=body):
                self.record_files()[0].write_text(body)
                self.assertReview("unreadable")

    def test_reason_is_a_single_line(self):
        self.record()
        self.record_files()[0].write_text('{"base": "%s", "paths": {}}' % ("0" * 40))
        out = self.verdict()[1]
        self.assertEqual(len(out.splitlines()), 2, out)

    def test_unreachable_base_sha_means_review(self):
        self.record()
        self.record_files()[0].write_text('{"base": "' + "0" * 40 + '", "paths": {}}')
        self.assertReview("could not recompute")

    def test_unfingerprintable_path_refuses_record_and_check_reviews(self):
        self.record()
        nested = self.repo / "nested"
        nested.mkdir()
        self.git("init", "-q", cwd=nested)
        (nested / "f").write_text("x\n")
        self.git("add", "f", cwd=nested)
        self.git("commit", "-q", "-m", "n", cwd=nested)
        self.git("add", "nested")  # recorded as a gitlink: a directory in the tree
        self.assertReview("could not recompute")
        proc = self.run_helper("record", "--issue", ISSUE, "--base", "develop")
        self.assertNotEqual(proc.returncode, 0)

    def test_outside_a_git_repo(self):
        outside = Path(self._tmp.name) / "plain"
        outside.mkdir()
        proc = self.run_helper("record", "--issue", ISSUE, "--base", "develop", cwd=outside)
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("FINGERPRINT=recorded", proc.stdout)
        proc = self.run_helper("check", "--issue", ISSUE, cwd=outside)
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(proc.stdout.startswith("VERDICT=review"), proc.stdout)

    def test_unknown_base_ref_refuses_record(self):
        proc = self.run_helper("record", "--issue", ISSUE, "--base", "no-such-branch")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(self.record_files(), [])

    def test_option_like_base_is_not_parsed_as_an_option(self):
        proc = self.run_helper("record", "--issue", ISSUE, "--base=--all")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(self.record_files(), [])

    # --- clear and argument validation -------------------------------------

    def test_clear_removes_the_record(self):
        self.record()
        proc = self.run_helper("clear", "--issue", ISSUE)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.record_files(), [])
        self.assertReview("no hand-off fingerprint")

    def test_clear_without_a_record_succeeds(self):
        proc = self.run_helper("clear", "--issue", ISSUE)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_non_numeric_issue_is_rejected(self):
        for cmd in (["record", "--base", "develop"], ["check"], ["clear"]):
            proc = self.run_helper(cmd[0], "--issue", "../x", *cmd[1:])
            self.assertNotEqual(proc.returncode, 0, cmd)
            self.assertNotIn("VERDICT=skip", proc.stdout)
        self.assertEqual(self.record_files(), [])


if __name__ == "__main__":
    unittest.main()
