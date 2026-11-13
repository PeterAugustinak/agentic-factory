"""Tests for scripts/install.sh and scripts/uninstall.sh and settings.json (#122).

The hook is registered by the PAF skills' and agents' frontmatter, so the installer
no longer adds it to the user-level settings.json. On an upgrade it removes the PAF
entry an earlier version wrote, and the uninstaller removes a leftover one. Every
other piece of the file stays as it was, and a file without a PAF entry is never
rewritten.

The real scripts run as subprocesses against a scratch config directory
(`CLAUDE_CONFIG_DIR`) and a scratch HOME, installing from this checkout
(`PAF_LOCAL_SRC`), so nothing touches the real `~/.claude`.
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.support import INSTALL, REPO_ROOT, UNINSTALL
from tests.test_hook_registration import HOOK_BLOCK, frontmatter

OLD_PAF_ENTRY = {
    "matcher": "Bash|Edit|Write|MultiEdit|Read|Grep|Glob|WebSearch|WebFetch|Task",
    "hooks": [{"type": "command", "command": "python3 /x/.claude/hooks/paf/PreToolUse-agent-guard.py"}],
}
USER_PRE_ENTRY = {"matcher": "Bash", "hooks": [{"type": "command", "command": "my-guard.sh"}]}
USER_POST = [{"matcher": "Edit", "hooks": [{"type": "command", "command": "fmt.sh"}]}]


class ScriptRunner:
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.config = os.path.join(self.tmp, "config")
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.config)
        os.makedirs(self.home)
        self.settings = os.path.join(self.config, "settings.json")

    def run_script(self, script):
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": self.home,
            "CLAUDE_CONFIG_DIR": self.config,
            "PAF_LOCAL_SRC": str(REPO_ROOT),
        }
        proc = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def write_settings(self, data):
        text = json.dumps(data, indent=4, sort_keys=False)  # not the scripts' own format
        with open(self.settings, "w") as fh:
            fh.write(text)
        return text

    def read_settings(self):
        with open(self.settings) as fh:
            return fh.read()


class InstallTests(ScriptRunner, unittest.TestCase):
    def test_no_settings_file_is_created(self):
        self.run_script(INSTALL)
        self.assertFalse(os.path.exists(self.settings))

    def test_installs_the_hook_and_the_registering_frontmatter(self):
        self.run_script(INSTALL)
        hook = os.path.join(self.config, "hooks", "paf", "PreToolUse-agent-guard.py")
        self.assertTrue(os.access(hook, os.X_OK))
        skill = Path(self.config, "skills", "paf-implement-issue", "SKILL.md")
        agent = Path(self.config, "agents", "paf", "full-stack-dev.md")
        self.assertIn(HOOK_BLOCK, frontmatter(skill))
        self.assertIn(HOOK_BLOCK, frontmatter(agent))

    def test_upgrade_removes_the_old_entry_and_keeps_everything_else(self):
        self.write_settings({
            "model": "opus",
            "hooks": {"PreToolUse": [USER_PRE_ENTRY, OLD_PAF_ENTRY], "PostToolUse": USER_POST},
            "permissions": {"allow": ["Bash(ls)"]},
        })
        out = self.run_script(INSTALL)
        self.assertEqual(
            json.loads(self.read_settings()),
            {
                "model": "opus",
                "hooks": {"PreToolUse": [USER_PRE_ENTRY], "PostToolUse": USER_POST},
                "permissions": {"allow": ["Bash(ls)"]},
            },
        )
        self.assertIn("Removed the old PAF hook entry from settings.json", out)

    def test_upgrade_drops_hooks_left_empty(self):
        self.write_settings({"model": "opus", "hooks": {"PreToolUse": [OLD_PAF_ENTRY]}})
        self.run_script(INSTALL)
        self.assertEqual(json.loads(self.read_settings()), {"model": "opus"})

    def test_settings_without_a_paf_entry_is_left_byte_identical(self):
        before = self.write_settings({"hooks": {"PreToolUse": [USER_PRE_ENTRY]}, "x": 1})
        out = self.run_script(INSTALL)
        self.assertEqual(self.read_settings(), before)
        self.assertNotIn("Removed the old PAF hook entry", out)

    def test_unparsable_or_odd_settings_are_left_byte_identical(self):
        for text in ("{not json", "[1, 2]", '{"hooks": []}', '{"hooks": {"PreToolUse": {}}}',
                     '{"hooks": {"PreToolUse": [1, {"hooks": "x"}, {"hooks": [{"command": 3}]}]}}'):
            with self.subTest(text=text):
                with open(self.settings, "w") as fh:
                    fh.write(text)
                self.run_script(INSTALL)
                self.assertEqual(self.read_settings(), text)

    def test_reinstall_is_idempotent(self):
        self.write_settings({"hooks": {"PreToolUse": [OLD_PAF_ENTRY, USER_PRE_ENTRY]}})
        self.run_script(INSTALL)
        after_first = self.read_settings()
        self.run_script(INSTALL)
        self.assertEqual(self.read_settings(), after_first)


class UninstallTests(ScriptRunner, unittest.TestCase):
    def test_strips_a_leftover_entry_and_reports_it(self):
        self.run_script(INSTALL)
        self.write_settings({"hooks": {"PreToolUse": [OLD_PAF_ENTRY, USER_PRE_ENTRY]}, "x": 1})
        out = self.run_script(UNINSTALL)
        self.assertEqual(json.loads(self.read_settings()),
                         {"hooks": {"PreToolUse": [USER_PRE_ENTRY]}, "x": 1})
        self.assertIn("settings.json PreToolUse entry", out)

    def test_without_an_entry_settings_is_untouched_and_not_reported(self):
        self.run_script(INSTALL)
        before = self.write_settings({"hooks": {"PreToolUse": [USER_PRE_ENTRY]}})
        out = self.run_script(UNINSTALL)
        self.assertEqual(self.read_settings(), before)
        self.assertNotIn("settings.json", out)

    def test_unparsable_or_odd_settings_are_left_byte_identical(self):
        for text in ("{not json", "[1, 2]", '{"hooks": []}', '{"hooks": {"PreToolUse": {}}}',
                     '{"hooks": {"PreToolUse": [1, {"hooks": "x"}, {"hooks": [{"command": 3}]}]}}'):
            with self.subTest(text=text):
                with open(self.settings, "w") as fh:
                    fh.write(text)
                out = self.run_script(UNINSTALL)
                self.assertEqual(self.read_settings(), text)
                self.assertNotIn("settings.json", out)

    def test_dropping_the_last_pre_tool_use_entry_keeps_other_hooks(self):
        self.write_settings({"hooks": {"PreToolUse": [OLD_PAF_ENTRY], "PostToolUse": USER_POST}})
        self.run_script(UNINSTALL)
        self.assertEqual(json.loads(self.read_settings()), {"hooks": {"PostToolUse": USER_POST}})

    def test_removes_what_the_installer_placed(self):
        self.run_script(INSTALL)
        self.run_script(UNINSTALL)
        for rel in ("agents/paf", "hooks/paf", "skills/paf-shared", "skills/paf-init"):
            with self.subTest(path=rel):
                self.assertFalse(os.path.exists(os.path.join(self.config, rel)))


if __name__ == "__main__":
    unittest.main()
