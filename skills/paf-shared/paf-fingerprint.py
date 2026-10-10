#!/usr/bin/env python3
"""PAF hand-off content fingerprint.

Lets `/paf:check-out` tell, deterministically, whether anything changed on the
branch since `/paf:implement-issue` handed off its deep-reviewed work. At the
hand-off `record` pins the base commit and stores a fingerprint of the working
tree relative to it; at check-out `check` recomputes the fingerprint against the
SAME pinned sha and prints a verdict: `VERDICT=skip` only on an exact match,
`VERDICT=review` for everything else (a mismatch, no record, an unreadable
record, any git error). Absence of evidence fails safe into running the review.

The fingerprint is ONE merged path -> token map over every path whose content
differs from the pinned base:

  - tracked:   `git diff --name-only -z --no-renames <sha>` (working tree vs the
               pinned commit, staged or not; `--no-renames` neutralises any
               `diff.renames` config, so a rename is always its two paths);
  - untracked: `git ls-files -z --others --exclude-standard` (new files are
               absent from `git diff`), run from the repository root because
               `ls-files` is cwd-relative.

Each path's token is computed from the working tree itself — `deleted` for an
absent path, `link:<sha256>` of a symlink's target, `file:<x|->:<sha256>` of a
regular file's bytes (the executable bit is in scope: it is the only file mode
git records, and a chmod ships). A path that is none of these (a submodule
directory) cannot be fingerprinted, so the check fails safe to `review`.

The map is commit-invariant — committing content changes neither the working
tree nor the pinned sha, and the merged map has no tracked/untracked buckets a
commit could move a path between — and content-based: nothing hashes `git diff`
text, so diff config and external diff/textconv drivers cannot shift it.

Accepted residual limits: a path marked `--assume-unchanged` or `--skip-worktree`
is invisible to `git diff`, so a hand-edit there does not change the map; and a
clean filter / `core.autocrlf` normalisation can hide a line-ending-only change
from `git diff --name-only`, so such an edit on an otherwise-unchanged path does
not either.

The record lives under the user's ~/.claude namespace, never in the project,
keyed by a hash of the repository root (`git rev-parse --show-toplevel`) and the
issue number. `record` overwrites (a re-run of implement-issue supersedes it); `clear`
removes it when the feature ships, alongside the cost ledger.

Usage:
  paf-fingerprint.py record --issue <n> --base <ref>
  paf-fingerprint.py check  --issue <n>
  paf-fingerprint.py clear  --issue <n>
"""

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

FINGERPRINT_ROOT = Path.home() / ".claude" / "paf" / "fingerprints"
SHA_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


class FingerprintError(Exception):
    """The fingerprint cannot be computed (git failure, unfingerprintable path)."""


def _validate_issue(value: str) -> None:
    if not re.fullmatch(r"[0-9]+", value):
        sys.exit(f"ERROR: invalid --issue value {value!r}")


def _git(root, *args) -> str:
    cmd = ["git"] + (["-C", root] if root else []) + list(args)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except OSError as exc:
        raise FingerprintError(f"cannot run git: {exc}") from exc
    if proc.returncode != 0:
        raise FingerprintError(f"`git {' '.join(args)}` failed: {proc.stderr.strip()}")
    return proc.stdout


def repo_root() -> str:
    return _git(None, "rev-parse", "--show-toplevel").strip()


def record_path(root: str, issue: str) -> Path:
    # A hash, not a path-to-dashes slug: distinct roots must never share a record.
    key = hashlib.sha256(os.fsencode(root)).hexdigest()[:16]
    return FINGERPRINT_ROOT / key / f"{issue}.json"


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def path_token(root: str, rel: str) -> str:
    full = os.path.join(root, rel)
    try:
        st = os.lstat(full)
        if stat.S_ISLNK(st.st_mode):
            return "link:" + hashlib.sha256(os.fsencode(os.readlink(full))).hexdigest()
        if stat.S_ISREG(st.st_mode):
            exe = "x" if st.st_mode & stat.S_IXUSR else "-"
            return f"file:{exe}:{_sha256_file(full)}"
    except FileNotFoundError:
        return "deleted"
    except OSError as exc:
        raise FingerprintError(f"cannot read {rel!r}: {exc}") from exc
    raise FingerprintError(f"cannot fingerprint {rel!r}: not a regular file or symlink")


def fingerprint(root: str, base_sha: str) -> dict:
    if not SHA_RE.fullmatch(base_sha):
        raise FingerprintError(f"malformed base commit {base_sha!r}")
    tracked = _git(root, "diff", "--name-only", "-z", "--no-renames",
                   "--no-ext-diff", "--no-textconv", base_sha, "--")
    untracked = _git(root, "ls-files", "-z", "--others", "--exclude-standard")
    paths = {p for p in (tracked + untracked).split("\0") if p}
    return {p: path_token(root, p) for p in sorted(paths)}


def cmd_record(args) -> None:
    _validate_issue(args.issue)
    try:
        root = repo_root()
        base_sha = _git(root, "rev-parse", "--verify", "--end-of-options",
                        f"{args.base}^{{commit}}").strip()
        paths = fingerprint(root, base_sha)
    except FingerprintError as exc:
        sys.exit(f"ERROR: fingerprint not recorded: {exc}")
    path = record_path(root, args.issue)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write-then-rename so a concurrent or interrupted run never leaves a
    # half-written record that a later `check` would have to treat as unreadable.
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"base": base_sha, "paths": paths}, indent=1))
    os.replace(tmp, path)
    print("FINGERPRINT=recorded")
    print(f"Pinned base {base_sha}; {len(paths)} changed path(s) fingerprinted.")


def _one_line(text: str) -> str:
    """Collapse whitespace and control characters so REASON is always one line."""
    return re.sub(r"[\x00-\x1f\x7f\s]+", " ", text).strip()


def _evaluate(issue: str):
    """Return (skip, reason); skip is True only on an exact fingerprint match."""
    try:
        root = repo_root()
        path = record_path(root, issue)
        if not path.exists():
            return False, "no hand-off fingerprint recorded for this feature"
        try:
            rec = json.loads(path.read_text())
            base_sha, recorded = rec["base"], rec["paths"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return False, f"hand-off fingerprint unreadable: {exc}"
        if not (isinstance(base_sha, str) and SHA_RE.fullmatch(base_sha)
                and isinstance(recorded, dict)):
            return False, "hand-off fingerprint unreadable: malformed record"
        current = fingerprint(root, base_sha)
    except FingerprintError as exc:
        return False, f"could not recompute the fingerprint: {exc}"
    if current == recorded:
        return True, "branch content is identical to the implement-issue hand-off"
    changed = sum(1 for p in set(current) | set(recorded) if current.get(p) != recorded.get(p))
    return False, f"content changed since the implement-issue hand-off ({changed} path(s))"


def cmd_check(args) -> None:
    _validate_issue(args.issue)
    skip, reason = _evaluate(args.issue)
    print("VERDICT=skip" if skip else "VERDICT=review")
    print(f"REASON={_one_line(reason)}")


def cmd_clear(args) -> None:
    _validate_issue(args.issue)
    try:
        root = repo_root()
    except FingerprintError as exc:
        sys.exit(f"ERROR: {exc}")
    record_path(root, args.issue).unlink(missing_ok=True)
    print(f"Hand-off fingerprint for issue {args.issue} cleared.")


def main() -> None:
    parser = argparse.ArgumentParser(description="PAF hand-off content fingerprint.")
    sub = parser.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("record", help="pin the base and record the working-tree fingerprint")
    rec.add_argument("--issue", required=True)
    rec.add_argument("--base", required=True)
    rec.set_defaults(func=cmd_record)

    chk = sub.add_parser("check", help="recompute and compare; print VERDICT=skip|review")
    chk.add_argument("--issue", required=True)
    chk.set_defaults(func=cmd_check)

    clr = sub.add_parser("clear", help="remove the feature's fingerprint record")
    clr.add_argument("--issue", required=True)
    clr.set_defaults(func=cmd_clear)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
