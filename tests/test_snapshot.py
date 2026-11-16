"""Tests for skills/paf-shared/paf-snapshot.py.

Every test runs the shipped script as a SUBPROCESS against a real, throwaway git
repository — the snapshot and its diff are defined by what git does, so a fake git
would test nothing. `HOME` is pointed at a temporary directory, so everything lands
under a scratch `~/.claude` and the real one is never touched; git's global and
system config are disabled so the developer's own config cannot leak in.

The fixture mimics an `implement-issue` hand-off: `develop` holds the base commit,
and the feature branch carries the uncommitted implementation, an untracked file,
and an ignored file. The hand-edits a developer makes after the hand-off come in
each test.
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.support import REVIEW_INPUT, SNAPSHOT

ISSUE = "130"


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(os.path.realpath(self._tmp.name))
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
        self.write("app.py", "base\n")
        self.write("gone.py", "to be deleted\n")
        self.write("CLAUDE.md", "# Rules\n\n- Use class-based views.\n")
        self.write(".gitignore", "*.log\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "feature/130-x")
        # The implementation, left uncommitted as implement-issue hands it off.
        self.write("app.py", "def view():\n    pass\n")
        self.write("helper.py", "x = 1\n")
        self.write("debug.log", "noise\n")

    def tearDown(self):
        self._tmp.cleanup()

    # --- helpers --------------------------------------------------------------

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd or self.repo, env=self.env,
                              capture_output=True, check=True).stdout

    def write(self, rel, text, root=None):
        (Path(root or self.repo) / rel).write_text(text)

    def run_helper(self, *args, cwd=None, script=SNAPSHOT, stdin=b""):
        return subprocess.run([sys.executable, str(script), *args], cwd=cwd or self.repo,
                              env=self.env, input=stdin, capture_output=True)

    def key(self, root=None):
        return hashlib.sha256(os.fsencode(str(root or self.repo))).hexdigest()[:16]

    def snapshot_dir(self, root=None):
        return self.home / ".claude" / "paf" / "snapshots" / self.key(root) / ISSUE

    def input_file(self, root=None):
        return (self.home / ".claude" / "paf" / "review-input" / self.key(root)
                / f"{ISSUE}-conventions.md")

    def save(self, cwd=None):
        proc = self.run_helper("save", "--issue", ISSUE, cwd=cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.decode().strip(), "SNAPSHOT=saved")

    def write_input(self, cwd=None, instructions="CLAUDE.md"):
        proc = self.run_helper("write-input", "--issue", ISSUE, "--instructions", instructions,
                               cwd=cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        line = proc.stdout.decode().strip()
        self.assertTrue(line.startswith("CONVENTION_INPUT="), line)
        return line[len("CONVENTION_INPUT="):]

    def repo_files(self):
        """Every file in the repository, `.git` included, with its bytes."""
        return {str(p.relative_to(self.repo)): p.read_bytes()
                for p in sorted(self.repo.rglob("*")) if p.is_file()}

    def status(self):
        return self.git("status", "--porcelain", "--untracked-files=all")

    def hand_edit(self):
        self.write("app.py", "class View:\n    pass\n")
        self.write("new view.py", "class Other:\n    pass\n")
        (self.repo / "gone.py").unlink()
        self.write("more.log", "ignored\n")

    # --- save -----------------------------------------------------------------

    def test_save_stores_the_snapshot_under_home(self):
        self.save()
        snap = self.snapshot_dir()
        self.assertRegex((snap / "tree").read_text().strip(), r"^[0-9a-f]{40}$")
        self.assertTrue((snap / "objects").is_dir())

    def test_save_and_write_input_leave_the_repository_untouched(self):
        # `git status` may refresh the index itself, so the byte comparisons never
        # straddle one of its calls.
        status = self.status()
        files = self.repo_files()
        self.save()
        self.assertEqual(self.repo_files(), files)
        self.assertEqual(self.status(), status)
        self.hand_edit()
        files = self.repo_files()
        self.write_input()
        self.assertEqual(self.repo_files(), files)

    def test_save_outside_a_repository_fails(self):
        outside = Path(self._tmp.name) / "plain"
        outside.mkdir()
        proc = self.run_helper("save", "--issue", ISSUE, cwd=outside)
        self.assertEqual(proc.returncode, 1)
        self.assertIn(b"ERROR: snapshot not saved", proc.stderr)

    def test_invalid_issue_is_rejected(self):
        for command in (["save"], ["clear"], ["clear-input"],
                        ["write-input", "--instructions", "CLAUDE.md"]):
            with self.subTest(command=command[0]):
                proc = self.run_helper(*command, "--issue", "12; rm -rf x")
                self.assertEqual(proc.returncode, 1)
                self.assertIn(b"invalid --issue", proc.stderr)

    # --- write-input ------------------------------------------------------------

    def test_input_holds_the_diff_since_the_hand_off(self):
        self.save()
        self.hand_edit()
        path = self.write_input()
        self.assertEqual(Path(path), self.input_file())
        content = self.input_file().read_text()
        self.assertIn(f"Project instructions: {self.repo / 'CLAUDE.md'}\n", content)
        diff = content.split("===== BEGIN DIFF =====\n", 1)[1].split("===== END DIFF =====\n")[0]
        self.assertIn("-def view():", diff)            # modified, old side
        self.assertIn("+class View:", diff)            # modified, new side
        self.assertIn("b/new view.py", diff)           # added, untracked
        self.assertIn("deleted file mode", diff)       # deleted
        self.assertIn("-to be deleted", diff)
        self.assertNotIn("helper.py", diff)            # unchanged since the hand-off
        self.assertNotIn(".log", diff)                 # ignored files are left out
        self.assertEqual(oct(self.input_file().stat().st_mode & 0o777), "0o600")

    def test_changes_to_the_instructions_file_are_left_out(self):
        self.save()
        self.write("CLAUDE.md", "# Rules\n\n- Use class-based views.\n- New rule.\n")
        self.assertEqual(self.write_input(), "none")
        self.hand_edit()
        content = Path(self.write_input()).read_text()
        self.assertNotIn("New rule", content)

    def test_instructions_given_as_absolute_path_inside_the_repo(self):
        self.save()
        self.write("CLAUDE.md", "changed\n")
        self.assertEqual(self.write_input(instructions=str(self.repo / "CLAUDE.md")), "none")

    def test_instructions_outside_the_repository_is_rejected(self):
        self.save()
        for bad in ("../CLAUDE.md", "/etc/passwd", "."):
            with self.subTest(bad=bad):
                proc = self.run_helper("write-input", "--issue", ISSUE, "--instructions", bad)
                self.assertEqual(proc.returncode, 1)
                self.assertIn(b"ERROR: convention input not written", proc.stderr)

    def test_no_snapshot_prints_none_and_writes_nothing(self):
        self.hand_edit()
        self.assertEqual(self.write_input(), "none")
        self.assertFalse(self.input_file().exists())

    def test_no_change_since_the_snapshot_prints_none_and_removes_a_stale_input(self):
        self.save()
        self.hand_edit()
        self.write_input()
        self.save()  # a re-run of the hand-off on the hand-edited state
        self.assertEqual(self.write_input(), "none")
        self.assertFalse(self.input_file().exists())

    def test_resave_replaces_the_snapshot(self):
        self.save()
        self.write("app.py", "first edit\n")
        self.save()
        self.write("app.py", "second edit\n")
        content = Path(self.write_input()).read_text()
        self.assertIn("-first edit", content)
        self.assertNotIn("def view", content)
        self.assertEqual([p.name for p in self.snapshot_dir().parent.iterdir()], [ISSUE])

    def test_snapshot_survives_gc_prune_in_the_repository(self):
        self.save()
        self.git("gc", "-q", "--prune=now")
        self.hand_edit()
        self.assertIn("-def view():", Path(self.write_input()).read_text())

    def assert_unreadable_snapshot_fails(self, corrupt):
        self.save()
        self.hand_edit()
        self.write_input()  # a leftover from an earlier run must not survive the failure
        corrupt(self.snapshot_dir())
        proc = self.run_helper("write-input", "--issue", ISSUE, "--instructions", "CLAUDE.md")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn(b"ERROR: convention input not written", proc.stderr)
        self.assertNotIn(b"CONVENTION_INPUT=", proc.stdout)
        self.assertFalse(self.input_file().exists())

    def test_malformed_tree_id_fails(self):
        self.assert_unreadable_snapshot_fails(
            lambda snap: (snap / "tree").write_text("not a sha\n"))

    def test_missing_snapshot_objects_fail(self):
        # What a prune of an object only the snapshot still used leads to.
        def drop_objects(snap):
            shutil.rmtree(snap / "objects")
            (snap / "objects").mkdir()
        self.assert_unreadable_snapshot_fails(drop_objects)

    def test_linked_worktree_is_keyed_by_its_own_root(self):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "impl")
        wt = Path(self._tmp.name).resolve() / "wt"
        self.git("worktree", "add", "-q", "-b", "feature/131-y", str(wt))
        self.save(cwd=wt)
        self.assertTrue((self.snapshot_dir(wt) / "tree").exists())
        self.assertFalse(self.snapshot_dir().exists())
        self.write("app.py", "worktree edit\n", root=wt)
        path = self.write_input(cwd=wt)
        self.assertEqual(Path(path), self.input_file(wt))
        self.assertIn("+worktree edit", Path(path).read_text())

    # --- clear and clear-input ------------------------------------------------------

    def test_clear_removes_the_snapshot(self):
        self.save()
        proc = self.run_helper("clear", "--issue", ISSUE)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(self.snapshot_dir().exists())
        self.assertFalse(self.snapshot_dir().parent.exists())
        self.assertEqual(self.run_helper("clear", "--issue", ISSUE).returncode, 0)  # idempotent

    def test_the_two_input_files_never_clear_each_other(self):
        self.save()
        self.hand_edit()
        self.write_input()
        proc = self.run_helper("write", "--issue", ISSUE, "--base", "develop",
                               script=REVIEW_INPUT, stdin=b"issue\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        reviewers = Path(proc.stdout.decode().strip()[len("REVIEW_INPUT="):])
        self.assertEqual(reviewers.parent, self.input_file().parent)

        self.assertEqual(self.run_helper("clear-input", "--issue", ISSUE).returncode, 0)
        self.assertFalse(self.input_file().exists())
        self.assertTrue(reviewers.exists())

        self.write_input()
        proc = self.run_helper("clear", "--issue", ISSUE, script=REVIEW_INPUT)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(reviewers.exists())
        self.assertTrue(self.input_file().exists())

        self.assertEqual(self.run_helper("clear-input", "--issue", ISSUE).returncode, 0)
        self.assertFalse(self.input_file().parent.exists())


if __name__ == "__main__":
    unittest.main()
