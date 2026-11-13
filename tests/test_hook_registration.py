"""Tests for where the PreToolUse hook is registered (#122).

The hook is registered by the frontmatter `hooks` field of every PAF skill and every
PAF agent, never by settings.json (architecture.md §3). These tests pin that each of
those files carries the one registration block, and that the block's command, run
through `sh -c` as Claude Code runs a shell-form hook command, reaches the hook
installed under the Claude config directory — `CLAUDE_CONFIG_DIR` when set,
otherwise `$HOME/.claude`.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest

from tests.support import AGENT_GUARD, REPO_ROOT

# The command exactly as Claude Code receives it once the YAML single quotes are parsed.
HOOK_COMMAND = 'python3 "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/hooks/paf/PreToolUse-agent-guard.py"'

HOOK_BLOCK = f"""hooks:
  PreToolUse:
    - matcher: "Bash|Edit|Write|MultiEdit|Read|Grep|Glob|WebSearch|WebFetch|Task"
      hooks:
        - type: command
          command: '{HOOK_COMMAND}'
"""

SKILLS = sorted((REPO_ROOT / "skills").glob("paf-*/SKILL.md"))
AGENTS = sorted(p for p in (REPO_ROOT / "agents").glob("*.md") if p.name != "README.md")


def frontmatter(path):
    """The text between a file's opening `---` line and the next one."""
    text = path.read_text()
    if not text.startswith("---\n"):
        return ""
    end = text.find("\n---\n", 4)
    return text[4 : end + 1] if end != -1 else ""


class FrontmatterRegistrationTests(unittest.TestCase):
    def test_the_four_skills_and_the_agents_are_found(self):
        self.assertEqual(
            [p.parent.name for p in SKILLS],
            ["paf-check-out", "paf-create-issue", "paf-implement-issue", "paf-init"],
        )
        self.assertTrue(AGENTS)

    def test_every_skill_and_agent_registers_the_hook(self):
        for path in SKILLS + AGENTS:
            with self.subTest(path=str(path.relative_to(REPO_ROOT))):
                self.assertIn(HOOK_BLOCK, frontmatter(path))


class CommandResolutionTests(unittest.TestCase):
    """The frontmatter command, run through `sh -c`, reaches the installed hook."""

    MAIN_THREAD = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)

    def install_hook(self, config_dir):
        target = os.path.join(config_dir, "hooks", "paf")
        os.makedirs(target)
        shutil.copy(AGENT_GUARD, target)

    def run_command(self, env):
        env = {"PATH": os.environ.get("PATH", ""), **env}
        return subprocess.run(
            ["sh", "-c", HOOK_COMMAND], input=self.MAIN_THREAD,
            capture_output=True, text=True, env=env,
        )

    def decision(self, proc):
        out = proc.stdout.strip()
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"] if out else None

    def test_resolves_under_claude_config_dir_when_set(self):
        config = os.path.join(self.tmp, "config")
        self.install_hook(config)
        home = os.path.join(self.tmp, "home")
        os.makedirs(home)
        proc = self.run_command({"CLAUDE_CONFIG_DIR": config, "HOME": home})
        self.assertEqual(self.decision(proc), "allow", proc.stderr)

    def test_resolves_under_home_dot_claude_when_unset(self):
        home = os.path.join(self.tmp, "home")
        self.install_hook(os.path.join(home, ".claude"))
        proc = self.run_command({"HOME": home})
        self.assertEqual(self.decision(proc), "allow", proc.stderr)

    def test_no_hook_at_the_resolved_path_gives_no_decision(self):
        # Proves the path is what resolves: a hook under HOME is not reached when
        # CLAUDE_CONFIG_DIR points elsewhere.
        home = os.path.join(self.tmp, "home")
        self.install_hook(os.path.join(home, ".claude"))
        proc = self.run_command({"CLAUDE_CONFIG_DIR": os.path.join(self.tmp, "empty"), "HOME": home})
        self.assertIsNone(self.decision(proc))
        # python3 exits 2 for a script it cannot open, and Claude Code treats exit 2
        # from PreToolUse as a blocking error (architecture.md section 3, accepted limit).
        self.assertEqual(proc.returncode, 2)

    def test_resolves_a_config_dir_containing_a_space(self):
        config = os.path.join(self.tmp, "my config")
        self.install_hook(config)
        proc = self.run_command({"CLAUDE_CONFIG_DIR": config, "HOME": self.tmp})
        self.assertEqual(self.decision(proc), "allow", proc.stderr)

    def test_resolves_a_home_containing_a_space(self):
        home = os.path.join(self.tmp, "my home")
        self.install_hook(os.path.join(home, ".claude"))
        proc = self.run_command({"HOME": home})
        self.assertEqual(self.decision(proc), "allow", proc.stderr)


if __name__ == "__main__":
    unittest.main()
