#!/usr/bin/env bash
#
# pre-merge.sh — PAF's full pre-merge validation gate.
#
# The command CLAUDE.md names as "full pre-merge validation"; /paf:check-out runs
# it once before opening the MR/PR.
#
# Standard library only — no third-party tooling (no ruff, shellcheck, pytest).
# It runs on a bare machine that has python3 and bash, nothing else:
#
#   1. python3 -m py_compile   over every .py file       (Python syntax)
#   2. bash -n                 over every shell script   (shell syntax)
#   3. python3 -m unittest     from the repository root  (the test suite)
#
# Every stage always runs — one invocation reports every problem rather than
# stopping at the first. Exits non-zero if any stage failed.
#
# Trust boundary: stages 1 and 2 are diagnostic only (they read source, they don't
# run it). Stage 3 is not — unittest discovery imports every discoverable test
# module, which executes the module-level code of the scripts under test.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

# py_compile and the test imports both write bytecode. Send it to a scratch dir
# instead of scattering __pycache__/ through the source tree, which the installer
# would otherwise copy into an installed skill.
PYCACHE_DIR="$(mktemp -d)"
if [ -z "$PYCACHE_DIR" ]; then
  echo "FATAL: mktemp -d failed" >&2
  exit 1
fi
trap 'rm -rf "$PYCACHE_DIR"' EXIT
export PYTHONPYCACHEPREFIX="$PYCACHE_DIR"

failures=0
stage() { printf '\n== %s ==\n' "$1"; }
fail()  { printf 'FAIL: %s\n' "$1" >&2; failures=$((failures + 1)); }

# --- 1. Python syntax ---------------------------------------------------------
stage "py_compile — Python syntax"
if find . -name '*.py' -not -path './.git/*' -not -path '*/__pycache__/*' -print0 \
    | xargs -0 python3 -m py_compile; then
  echo "OK"
else
  fail "Python syntax errors (py_compile)"
fi

# --- 2. Shell syntax ----------------------------------------------------------
# Matched by extension AND by shebang: PAF's most-used script, skills/paf-shared/
# paf-vcs, is a bash script with no .sh extension, so an extension-only glob
# would silently skip it. The shebang read is restricted to executable files so
# this stage never opens arbitrary (e.g. binary) files that happen to live in
# the repo.
stage "bash -n — shell syntax"
shell_failures=0
shell_count=0
while IFS= read -r f; do
  case "$f" in
    *.sh) ;;
    *)
      # Not a .sh file — keep it only if it's executable AND its shebang says
      # it is a shell script.
      [ -x "$f" ] || continue
      head -1 "$f" 2>/dev/null | grep -Eq '^#!.*\b(bash|sh)\b' || continue
      ;;
  esac
  shell_count=$((shell_count + 1))
  if ! bash -n "$f"; then
    printf '  syntax error: %s\n' "$f" >&2
    shell_failures=$((shell_failures + 1))
  fi
done < <(find . -type f -not -path './.git/*' -not -path './.idea/*' -not -name '*.py')

if [ "$shell_failures" -ne 0 ]; then
  fail "$shell_failures shell script(s) with syntax errors"
else
  echo "OK ($shell_count shell script(s))"
fi

# --- 3. Test suite ------------------------------------------------------------
stage "unittest — test suite"
if python3 -m unittest; then
  echo "OK"
else
  fail "test suite failed"
fi

# --- Verdict ------------------------------------------------------------------
if [ "$failures" -ne 0 ]; then
  printf '\npre-merge FAILED (%d stage(s))\n' "$failures" >&2
  exit 1
fi
printf '\npre-merge PASSED\n'
