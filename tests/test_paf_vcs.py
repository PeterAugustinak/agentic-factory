"""Tests for skills/paf-shared/paf-vcs.

The adapter is Bash, so every test runs the shipped script as a SUBPROCESS and
asserts on its stdout, stderr, and exit code — the same process-boundary seam
`tests/test_agent_guard.py` uses for the hook.

No network: `gh`/`glab` are replaced by a stub that records each call (argv, the
stdin it received, and whether that stdin was `/dev/null`) and answers with canned
output. The PATH is hermetic — a tools dir symlinking only the externals the
adapter needs, plus the stub dir — because the real `gh`/`glab` are commonly
installed beside `bash` (e.g. `/opt/homebrew/bin`), so prepending a stub dir to the
ambient PATH could never prove the "CLI not installed" path.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from tests.support import PAF_VCS

# The externals paf-vcs (and its `#!/usr/bin/env bash` shebang) runs. Nothing else
# is on the PATH the script sees.
TOOLS = ("bash", "git", "sed", "grep", "tail", "cat")

# The stub is a Python script run through a `#!/bin/sh` exec wrapper, so no
# interpreter path is ever baked into a shebang (spaces / length limits).
STUB_WRAPPER = '#!/bin/sh\nexec "$PAF_STUB_PYTHON" "$PAF_STUB_SCRIPT" "$@"\n'

STUB = """
import json, os, stat, sys

def is_devnull(fd):
    st = os.fstat(fd)
    return stat.S_ISCHR(st.st_mode) and st.st_rdev == os.stat("/dev/null").st_rdev

devnull = is_devnull(0)
data = sys.stdin.read()
with open(os.environ["PAF_STUB_LOG"], "a") as log:
    log.write(json.dumps({"argv": sys.argv[1:], "stdin": data, "stdin_is_devnull": devnull}) + "\\n")
if sys.argv[1:] == ["auth", "status"]:
    sys.exit(int(os.environ.get("PAF_STUB_AUTH_RC", "0")))
sys.stdout.write(os.environ.get("PAF_STUB_OUTPUT", ""))
sys.stderr.write(os.environ.get("PAF_STUB_STDERR", ""))
sys.exit(int(os.environ.get("PAF_STUB_RC", "0")))
"""

GITHUB = "https://github.com/o/r.git"
GITLAB = "https://gitlab.com/o/r.git"
ORIGINS = {"gh": GITHUB, "glab": GITLAB}
BRANCH = "feature/7-x"

# A body that would break any quoting/word-splitting/expansion mistake: quotes,
# command substitution in both syntaxes, a glob, a leading flag, several lines.
NASTY_BODY = "line one\n\"double\" 'single' $(id) `id` *\n--repo evil/x\n\nlast line"
NASTY_TITLE = "--repo evil/x; rm -rf / $(id)"

ISSUE_URL = {"gh": "https://github.com/o/r/issues/42", "glab": "https://gitlab.com/o/r/-/issues/42"}
CHANGE_URL = {"gh": "https://github.com/o/r/pull/17", "glab": "https://gitlab.com/o/r/-/merge_requests/17"}
CREATE_URL = {"create-issue": ISSUE_URL, "create-change-request": CHANGE_URL}
CREATE_VERBS = tuple(CREATE_URL)
STDIN_VERBS = ("create-issue", "comment-issue", "create-change-request")

# Minimal valid arguments per verb. Every verb that touches a provider is here.
SIMPLE_ARGS = {
    "auth-status": (),
    "create-issue": ("--title", "T"),
    "view-issue": ("61",),
    "comment-issue": ("61",),
    "list-labels": (),
    "create-change-request": ("--base", "develop", "--title", "T"),
}

# verb -> (full-featured args, the exact argv each provider CLI must receive).
CASES = {
    "create-issue": (
        ("--title", NASTY_TITLE, "--label", "bug", "--label", "two words"),
        {
            "gh": ["issue", "create", "--title", NASTY_TITLE, "--body-file", "-",
                   "--label", "bug", "--label", "two words"],
            "glab": ["issue", "create", "--yes", "--template", "", "--title", NASTY_TITLE,
                     "--description", NASTY_BODY, "--label", "bug", "--label", "two words"],
        },
    ),
    "view-issue": (("61",), {"gh": ["issue", "view", "61"], "glab": ["issue", "view", "61"]}),
    "comment-issue": (
        ("61",),
        {
            "gh": ["issue", "comment", "61", "--body-file", "-"],
            "glab": ["issue", "note", "61", "--message", NASTY_BODY],
        },
    ),
    "list-labels": ((), {"gh": ["label", "list"], "glab": ["label", "list"]}),
    "create-change-request": (
        ("--base", "develop", "--title", NASTY_TITLE),
        {
            "gh": ["pr", "create", "--base", "develop", "--title", NASTY_TITLE, "--body-file", "-"],
            "glab": ["mr", "create", "--yes", "--template", "", "--target-branch", "develop",
                     "--source-branch", BRANCH, "--title", NASTY_TITLE, "--description", NASTY_BODY],
        },
    ),
}


class VcsRunner:
    """Builds the hermetic sandbox and runs paf-vcs inside it. A mixin, so a
    TestCase built on it does not re-run another TestCase's tests."""

    def setUp(self):
        self.fresh()

    def fresh(self):
        """A brand-new sandbox; the previous one (if any) is removed first.
        Call it per subTest iteration instead of re-running setUp()."""
        previous = getattr(self, "_tmp", None)
        if previous is not None:
            previous.cleanup()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = os.path.realpath(self._tmp.name)
        self.tools = self._mkdir("tools")
        self.stubs = self._mkdir("stubs")
        self.home = self._mkdir("home")
        self.repo = self._mkdir("repo")
        self.log = os.path.join(self.root, "calls.jsonl")
        self.stub_script = os.path.join(self.root, "stub.py")
        for tool in TOOLS:
            real = shutil.which(tool)
            if real is None:
                self.skipTest(f"{tool} not found on PATH")
            os.symlink(real, os.path.join(self.tools, tool))
        self.stub_env = {}
        self.git("init", "-q", "-b", "main")

    def _mkdir(self, name):
        path = os.path.join(self.root, name)
        os.mkdir(path)
        return path

    def env(self):
        env = {
            "PATH": f"{self.stubs}{os.pathsep}{self.tools}",
            "HOME": self.home,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CEILING_DIRECTORIES": self.root,
            "PAF_STUB_LOG": self.log,
            "PAF_STUB_PYTHON": sys.executable,
            "PAF_STUB_SCRIPT": self.stub_script,
        }
        env.update(self.stub_env)
        return env

    def git(self, *args, cwd=None):
        subprocess.run(
            ["git", *args], cwd=cwd or self.repo, env={**self.env(), "PATH": self.tools},
            check=True, capture_output=True,
        )

    def set_origin(self, url):
        self.git("remote", "add", "origin", url)

    def use(self, provider):
        """Origin on the provider's host, its CLI stubbed, a named branch checked out."""
        self.set_origin(ORIGINS[provider])
        self.install_stub(provider)
        self.git("-c", "user.name=t", "-c", "user.email=t@example.com",
                 "commit", "-q", "--allow-empty", "-m", "init")
        self.git("checkout", "-q", "-b", BRANCH)

    def install_stub(self, name):
        with open(self.stub_script, "w") as f:
            f.write(STUB)
        path = os.path.join(self.stubs, name)
        with open(path, "w") as f:
            f.write(STUB_WRAPPER)
        os.chmod(path, 0o755)

    def vcs(self, *args, stdin="", cwd=None):
        return subprocess.run(
            [str(PAF_VCS), *args], cwd=cwd or self.repo, input=stdin,
            capture_output=True, text=True, env=self.env(),
        )

    def run_verb(self, provider, verb, args=None, stdin="body", output=None, **stub_env):
        """`use(provider)` then run `verb`. Create verbs get a valid URL as stdout
        unless `output` is given; `stub_env` sets further PAF_STUB_* variables."""
        self.use(provider)
        if output is None:
            output = CREATE_URL[verb][provider] + "\n" if verb in CREATE_VERBS else ""
        self.stub_env["PAF_STUB_OUTPUT"] = output
        self.stub_env.update(stub_env)
        return self.vcs(verb, *(SIMPLE_ARGS[verb] if args is None else args), stdin=stdin)

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return [json.loads(line) for line in f]

    def provider_call(self):
        """The single non-auth call; the auth probe must precede it."""
        calls = self.calls()
        self.assertEqual(len(calls), 2, calls)
        self.assertEqual(calls[0]["argv"], ["auth", "status"])
        return calls[1]

    def assertFailed(self, proc, fragment, code=1):
        self.assertEqual(proc.returncode, code, proc.stderr)
        self.assertIn(fragment, proc.stderr)


class ProviderDetectionTests(VcsRunner, unittest.TestCase):
    def detect(self, url):
        self.set_origin(url)
        self.install_stub("gh")
        self.install_stub("glab")
        return self.vcs("provider")

    def test_supported_hosts_in_every_remote_shape(self):
        for host, provider in (("github.com", "gh"), ("gitlab.com", "glab")):
            for url in (
                f"https://{host}/o/r.git",
                f"git@{host}:o/r.git",
                f"ssh://git@{host}/o/r",
                f"ssh://git@{host}:22/o/r",
                f"https://user:tok@{host}/o/r",
            ):
                with self.subTest(url=url):
                    self.fresh()
                    proc = self.detect(url)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    self.assertEqual(proc.stdout, f"{provider}\n")
                    # `provider` only reads the remote; it never touches a CLI.
                    self.assertEqual(self.calls(), [])

    def test_lookalike_hosts_are_rejected_not_substring_matched(self):
        for host in ("notgithub.com", "github.com.evil.example", "gitlab.com.evil.example",
                     "evilgitlab.com", "example.com"):
            with self.subTest(host=host):
                self.fresh()
                proc = self.detect(f"https://{host}/o/r.git")
                self.assertFailed(proc, f"unsupported VCS host '{host}'")
                self.assertEqual(proc.stdout, "")

    def test_userinfo_path_and_case_spoofs_are_rejected(self):
        for url, host in (
            ("https://github.com@evil.example/o/r", "evil.example"),
            ("https://github.com:x@evil.example/o/r", "evil.example"),
            ("https://evil.example/github.com/o/r", "evil.example"),
            ("https://evil.example:443/github.com", "evil.example"),
            ("/tmp/github.com/o/r", ""),  # a local path has no host at all
            ("https://GitHub.com/o/r", "GitHub.com"),  # host match is case-sensitive
        ):
            with self.subTest(url=url):
                self.fresh()
                proc = self.detect(url)
                self.assertFailed(proc, f"unsupported VCS host '{host}'")
                self.assertEqual(proc.stdout, "")

    def test_unsupported_host_is_rejected_by_every_provider_verb(self):
        for verb, args in SIMPLE_ARGS.items():
            with self.subTest(verb=verb):
                self.fresh()
                self.set_origin("git@github.com.evil.example:o/r.git")
                self.install_stub("gh")
                proc = self.vcs(verb, *args, stdin="body")
                self.assertFailed(proc, "unsupported VCS host 'github.com.evil.example'")
                self.assertEqual(self.calls(), [])

    def test_missing_origin_is_rejected_by_every_provider_verb(self):
        for verb, args in SIMPLE_ARGS.items():
            with self.subTest(verb=verb):
                self.fresh()
                self.install_stub("gh")
                proc = self.vcs(verb, *args, stdin="body")
                self.assertFailed(proc, "'origin' remote")
                self.assertEqual(self.calls(), [])

    def test_credentials_in_remote_never_reach_stderr(self):
        proc = self.detect("https://user:SECRET-TOKEN@example.com/o/r.git")
        self.assertFailed(proc, "unsupported VCS host 'example.com'")
        self.assertNotIn("SECRET-TOKEN", proc.stderr)

    def test_no_origin_remote(self):
        self.install_stub("gh")
        proc = self.vcs("provider")
        self.assertFailed(proc, "'origin' remote")

    def test_not_a_git_repository(self):
        outside = self._mkdir("outside")
        proc = self.vcs("provider", cwd=outside)
        self.assertFailed(proc, "'origin' remote")


class ArgvTests(VcsRunner, unittest.TestCase):
    """The exact argv composed for each provider, per verb."""

    def test_every_verb_for_both_providers(self):
        for verb, (args, per_provider) in CASES.items():
            for provider, argv in per_provider.items():
                with self.subTest(verb=verb, provider=provider):
                    self.fresh()
                    proc = self.run_verb(provider, verb, args, stdin=NASTY_BODY)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    self.assertEqual(self.provider_call()["argv"], argv)

    def test_auth_status(self):
        for provider in ("gh", "glab"):
            with self.subTest(provider=provider):
                self.fresh()
                self.use(provider)
                proc = self.vcs("auth-status")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(proc.stdout, f"provider: {provider} (authenticated)\n")
                self.assertEqual([c["argv"] for c in self.calls()], [["auth", "status"]])

    def test_create_issue_without_labels_adds_no_label_flag(self):
        for provider in ("gh", "glab"):
            with self.subTest(provider=provider):
                self.fresh()
                proc = self.run_verb(provider, "create-issue")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertNotIn("--label", self.provider_call()["argv"])


class StdinPlumbingTests(VcsRunner, unittest.TestCase):
    def test_body_goes_to_stdin_for_gh_and_to_argv_for_glab(self):
        for provider in ("gh", "glab"):
            for verb in STDIN_VERBS:
                with self.subTest(provider=provider, verb=verb):
                    self.fresh()
                    proc = self.run_verb(provider, verb, stdin=NASTY_BODY)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    call = self.provider_call()
                    if provider == "gh":
                        self.assertEqual(call["stdin"], NASTY_BODY)
                        self.assertFalse(call["stdin_is_devnull"])
                        self.assertNotIn(NASTY_BODY, call["argv"])  # kept off argv
                    else:
                        self.assertIn(NASTY_BODY, call["argv"])
                        self.assertEqual(call["stdin"], "")
                        self.assertTrue(call["stdin_is_devnull"])

    def test_trailing_newlines_of_the_body_are_stripped(self):
        sent = "keep\n\nmid\n\n\n"
        kept = "keep\n\nmid"
        for provider in ("gh", "glab"):
            for verb in STDIN_VERBS:
                with self.subTest(provider=provider, verb=verb):
                    self.fresh()
                    proc = self.run_verb(provider, verb, stdin=sent)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    call = self.provider_call()
                    if provider == "gh":
                        self.assertEqual(call["stdin"], kept)
                    else:
                        self.assertIn(kept, call["argv"])
                        self.assertNotIn(sent, call["argv"])

    def test_read_only_verbs_and_auth_probe_read_devnull(self):
        for provider in ("gh", "glab"):
            for verb in ("view-issue", "list-labels"):
                with self.subTest(provider=provider, verb=verb):
                    self.fresh()
                    proc = self.run_verb(provider, verb, stdin="must not be forwarded")
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    for call in self.calls():
                        self.assertTrue(call["stdin_is_devnull"], call)

    def test_missing_stdin_fails_instead_of_hanging(self):
        try:
            primary, replica = os.openpty()
        except (AttributeError, OSError) as exc:
            self.skipTest(f"no pty available: {exc}")
        self.addCleanup(os.close, primary)
        self.addCleanup(os.close, replica)
        for verb in STDIN_VERBS:
            with self.subTest(verb=verb):
                self.fresh()
                self.use("gh")
                proc = subprocess.run(
                    [str(PAF_VCS), verb, *SIMPLE_ARGS[verb]], cwd=self.repo, stdin=replica,
                    capture_output=True, text=True, env=self.env(), timeout=10,
                )
                self.assertFailed(proc, f"{verb}: expected content on stdin")
                self.assertEqual(self.calls(), [])


class OutputContractTests(VcsRunner, unittest.TestCase):
    def test_create_verbs_print_number_url_separator_then_raw_output(self):
        for provider in ("gh", "glab"):
            for verb, number in (("create-issue", "42"), ("create-change-request", "17")):
                with self.subTest(provider=provider, verb=verb):
                    self.fresh()
                    url = CREATE_URL[verb][provider]
                    raw = f"Creating in o/r\n\n{url}\n"
                    proc = self.run_verb(provider, verb, output=raw)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    self.assertEqual(proc.stdout, f"NUMBER={number}\nURL={url}\n---\n{raw}")

    def test_url_printed_only_on_stderr_is_still_found(self):
        for provider in ("gh", "glab"):
            for verb, number in (("create-issue", "42"), ("create-change-request", "17")):
                with self.subTest(provider=provider, verb=verb):
                    self.fresh()
                    url = CREATE_URL[verb][provider]
                    proc = self.run_verb(provider, verb, output="", PAF_STUB_STDERR=f"Created {url}\n")
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    self.assertEqual(proc.stdout, f"NUMBER={number}\nURL={url}\n---\nCreated {url}\n")

    def test_last_url_in_output_wins(self):
        decoy = "https://github.com/o/r/issues/1"
        proc = self.run_verb("gh", "create-issue", output=f"see {decoy}\n{ISSUE_URL['gh']}\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(proc.stdout.startswith(f"NUMBER=42\nURL={ISSUE_URL['gh']}\n---\n"))

    def test_output_without_url_fails_without_guessing(self):
        for provider in ("gh", "glab"):
            for verb in CREATE_VERBS:
                with self.subTest(provider=provider, verb=verb):
                    self.fresh()
                    proc = self.run_verb(provider, verb, output="created, but no link printed\n")
                    self.assertFailed(proc, "could not find an issue/PR/MR URL")
                    self.assertNotIn("NUMBER=", proc.stdout)
                    self.assertNotIn("URL=", proc.stdout)

    def test_cli_failure_surfaces_output_and_its_exit_status(self):
        for provider in ("gh", "glab"):
            for verb in CREATE_VERBS:
                for channel in ("PAF_STUB_OUTPUT", "PAF_STUB_STDERR"):
                    with self.subTest(provider=provider, verb=verb, channel=channel):
                        self.fresh()
                        text = f"boom {CREATE_URL[verb][provider]}\n"
                        stub = {"PAF_STUB_OUTPUT": "", "PAF_STUB_STDERR": "", channel: text}
                        proc = self.run_verb(provider, verb, PAF_STUB_RC="3", **stub)
                        self.assertEqual(proc.returncode, 3)
                        self.assertEqual(proc.stdout, "")
                        self.assertIn("boom", proc.stderr)

    def test_other_verbs_pass_provider_output_through_unchanged(self):
        raw = "title:\tX\n\n  indented  \nNUMBER=999\n---\n"
        for provider in ("gh", "glab"):
            for verb in ("view-issue", "comment-issue", "list-labels"):
                with self.subTest(provider=provider, verb=verb):
                    self.fresh()
                    proc = self.run_verb(provider, verb, output=raw)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    self.assertEqual(proc.stdout, raw)

    def test_pass_through_verbs_propagate_cli_exit_status(self):
        for provider in ("gh", "glab"):
            for verb in ("view-issue", "comment-issue", "list-labels"):
                with self.subTest(provider=provider, verb=verb):
                    self.fresh()
                    proc = self.run_verb(provider, verb, PAF_STUB_RC="4")
                    self.assertEqual(proc.returncode, 4, proc.stderr)


class FailureTests(VcsRunner, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.use("gh")

    def assertRejected(self, args, fragment, stdin="body"):
        proc = self.vcs(*args, stdin=stdin)
        self.assertFailed(proc, fragment)
        self.assertEqual(self.calls(), [])  # failed before touching the provider

    def test_no_verb_prints_usage(self):
        self.assertRejected((), "usage: paf-vcs <verb>")

    def test_unknown_verb(self):
        self.assertRejected(("frob",), "unknown verb 'frob'")

    def test_missing_or_malformed_flags(self):
        for args, fragment in (
            (("create-issue",), "create-issue: --title is required"),
            (("create-issue", "--label", "bug"), "create-issue: --title is required"),
            (("create-issue", "--title", ""), "create-issue: --title is required"),
            (("create-issue", "--title"), "create-issue: --title requires a value"),
            (("create-issue", "--title", "T", "--label"), "create-issue: --label requires a value"),
            (("create-issue", "--title", "T", "--body", "x"), "create-issue: unknown flag '--body'"),
            (("create-change-request", "--title", "T"), "create-change-request: --base is required"),
            (("create-change-request", "--base", "", "--title", "T"),
             "create-change-request: --base is required"),
            (("create-change-request", "--base", "develop"), "create-change-request: --title is required"),
            (("create-change-request", "--base", "develop", "--title", ""),
             "create-change-request: --title is required"),
            (("create-change-request", "--base"), "create-change-request: --base requires a value"),
            (("create-change-request", "--base", "d", "--title", "T", "--draft"),
             "create-change-request: unknown flag '--draft'"),
            (("view-issue",), "view-issue: issue id is required"),
            (("view-issue", ""), "view-issue: issue id is required"),
            (("comment-issue",), "comment-issue: issue id is required"),
            (("comment-issue", ""), "comment-issue: issue id is required"),
        ):
            with self.subTest(args=args):
                self.assertRejected(args, fragment)


class ProviderCliTests(VcsRunner, unittest.TestCase):
    def test_missing_cli_binary(self):
        for provider in ("gh", "glab"):
            with self.subTest(provider=provider):
                self.fresh()
                self.set_origin(ORIGINS[provider])  # no stub installed
                proc = self.vcs("list-labels")
                self.assertFailed(proc, f"'{provider}' is required but not installed")

    def test_unauthenticated_cli(self):
        for provider in ("gh", "glab"):
            with self.subTest(provider=provider):
                self.fresh()
                self.use(provider)
                self.stub_env["PAF_STUB_AUTH_RC"] = "1"
                proc = self.vcs("view-issue", "61")
                self.assertFailed(proc, f"'{provider}' is not authenticated. Run '{provider} auth login'")
                self.assertEqual([c["argv"] for c in self.calls()], [["auth", "status"]])


if __name__ == "__main__":
    unittest.main()
