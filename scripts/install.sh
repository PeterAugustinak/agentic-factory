#!/usr/bin/env bash
#
# install.sh — Personal Agentic Factory (PAF) installer.
#
# Install / upgrade with a single command (no manual cloning needed):
#
#   curl -sSL https://raw.githubusercontent.com/PeterAugustinak/agentic-factory/develop/scripts/install.sh | bash
#
# It fetches the factory and installs it into your Claude Code config:
#   - skills  -> ~/.claude/skills/<name>/        (flat; command = frontmatter name, e.g. /paf:create-issue)
#             -> ~/.claude/skills/paf-shared/        (shared helpers; not a skill)
#   - agents  -> ~/.claude/agents/paf/
#   - hooks   -> ~/.claude/hooks/paf/  (registered by the PAF skills' and agents' frontmatter)
#
# Re-running upgrades cleanly (idempotent). Env overrides:
#   PAF_REF             git ref to install (default: develop; master once released)
#   CLAUDE_CONFIG_DIR   Claude config dir (default: ~/.claude)
#   PAF_LOCAL_SRC       use a local checkout instead of cloning (dev/testing)

set -euo pipefail

REPO_URL="https://github.com/PeterAugustinak/agentic-factory.git"
REF="${PAF_REF:-develop}"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
SKILLS_DIR="$CLAUDE_DIR/skills"
AGENTS_DIR="$CLAUDE_DIR/agents/paf"
HOOKS_DIR="$CLAUDE_DIR/hooks/paf"
SETTINGS="$CLAUDE_DIR/settings.json"
HOOK_NAME="PreToolUse-agent-guard.py"
PAF_DIR="$CLAUDE_DIR/paf"          # survives reinstalls (also holds the cost ledger)
MARKER="$PAF_DIR/VERSION"          # the *installed* version

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
read_version() { tr -d '[:space:]' < "$1"; }  # a VERSION file is one line; strip stray whitespace

# --- dependencies ---
command -v python3 >/dev/null 2>&1 || die "'python3' is required but not found."
if [ -z "${PAF_LOCAL_SRC:-}" ]; then
  command -v git >/dev/null 2>&1 || die "'git' is required but not found."
fi

echo "Installing PAF (Personal Agentic Factory)..."

# --- the currently installed version, read before anything is written ---
OLD=""
if [ -f "$MARKER" ]; then OLD="$(read_version "$MARKER")"; fi

# --- obtain the source ---
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
if [ -n "${PAF_LOCAL_SRC:-}" ]; then
  SRC="$PAF_LOCAL_SRC"
  echo "  Source: local checkout ($SRC)"
else
  echo "  Source: $REPO_URL @ $REF"
  git clone --depth 1 --branch "$REF" "$REPO_URL" "$tmp/repo" >/dev/null 2>&1 \
    || die "git clone failed (ref: $REF)."
  SRC="$tmp/repo"
fi
[ -d "$SRC/skills" ] && [ -d "$SRC/agents" ] && [ -d "$SRC/hooks" ] \
  || die "source does not look like the factory repo (missing skills/agents/hooks)."
[ -f "$SRC/VERSION" ] || die "source has no VERSION file (ref: ${REF})."
NEW="$(read_version "$SRC/VERSION")"
[ -n "$NEW" ] || die "source VERSION file is empty."

mkdir -p "$SKILLS_DIR"

# --- skills (flat) ---
installed_skills=()
for d in "$SRC"/skills/*/; do
  name="$(basename "$d")"
  [ -f "$d/SKILL.md" ] || continue          # only real skills (skips README, paf-shared)
  rm -rf "${SKILLS_DIR:?}/$name"
  cp -R "$d" "$SKILLS_DIR/$name"
  installed_skills+=("$name")
done
[ "${#installed_skills[@]}" -gt 0 ] || die "no skills found in source."

# --- shared helpers (sibling of the skills) ---
rm -rf "${SKILLS_DIR:?}/paf-shared"
cp -R "$SRC/skills/paf-shared" "$SKILLS_DIR/paf-shared"
chmod +x "$SKILLS_DIR"/paf-shared/*.py "$SKILLS_DIR"/paf-shared/paf-vcs 2>/dev/null || true

# --- agents (namespaced; recursive scan makes this fine) ---
rm -rf "$AGENTS_DIR"; mkdir -p "$AGENTS_DIR"
for f in "$SRC"/agents/*.md; do
  [ "$(basename "$f")" = "README.md" ] && continue
  cp "$f" "$AGENTS_DIR/"
done

# --- hooks (namespaced; referenced by path) ---
rm -rf "$HOOKS_DIR"; mkdir -p "$HOOKS_DIR"
cp "$SRC/hooks/$HOOK_NAME" "$HOOKS_DIR/"
chmod +x "$HOOKS_DIR/$HOOK_NAME"

# --- drop a PAF hook entry an earlier version wired into settings.json ---
# The hook is registered by the PAF skills' and agents' frontmatter, so it runs only where
# PAF runs; settings.json would apply it to every session (architecture.md §3). The file is
# rewritten only when it holds a PAF entry; otherwise it is left exactly as it is. The same
# snippet is in uninstall.sh: both run standalone (curl | bash), so they cannot share a file.
if [ -f "$SETTINGS" ]; then
  stripped="$(python3 - "$SETTINGS" "$HOOK_NAME" <<'PY'
import json, sys
path, base = sys.argv[1], sys.argv[2]
try:
    with open(path) as fh:
        d = json.load(fh)
except (OSError, ValueError):
    raise SystemExit
hooks = d.get("hooks") if isinstance(d, dict) else None
pre = hooks.get("PreToolUse") if isinstance(hooks, dict) else None
if not isinstance(pre, list):
    raise SystemExit
def is_ours(entry):
    handlers = entry.get("hooks") if isinstance(entry, dict) else None
    return isinstance(handlers, list) and any(
        isinstance(h, dict) and isinstance(h.get("command"), str) and base in h["command"]
        for h in handlers)
keep = [e for e in pre if not is_ours(e)]
if len(keep) == len(pre):
    raise SystemExit   # no PAF entry: leave the file exactly as it is
if keep:
    hooks["PreToolUse"] = keep
else:
    hooks.pop("PreToolUse")
    if not hooks:
        d.pop("hooks")
with open(path, "w") as fh:
    json.dump(d, fh, indent=2)
    fh.write("\n")
print("STRIPPED")
PY
)"
  if [ "$stripped" = "STRIPPED" ]; then echo "  Removed the old PAF hook entry from settings.json"; fi
fi

# --- record the installed version ---
mkdir -p "$PAF_DIR"
printf '%s\n' "$NEW" > "$MARKER"

# --- post-install summary ---
skill_command() {  # print the frontmatter `name` (the invoke command) for a skill dir
  sed -n 's/^name:[[:space:]]*//p' "$SKILLS_DIR/$1/SKILL.md" | head -1 | tr -d '"'
}
echo
if [ -z "$OLD" ]; then
  echo "PAF v$NEW installed (new installation)"
elif [ "$OLD" = "$NEW" ]; then
  echo "PAF v$NEW reinstalled (already up to date)"
else
  echo "PAF upgraded: v$OLD -> v$NEW"
fi
echo
echo "PAF installed into $CLAUDE_DIR"
echo "  skills:  $SKILLS_DIR/<name>   (+ paf-shared)"
echo "  agents:  $AGENTS_DIR"
echo "  hook:    $HOOKS_DIR/$HOOK_NAME  (registered by the PAF skills and agents)"
echo
echo "Skills — invoke in Claude Code:"
for s in "${installed_skills[@]}"; do
  cmd="$(skill_command "$s")"
  printf '  /%s\n' "${cmd:-$s}"
done
echo
echo "Start a new Claude Code session (or restart) to pick up the skills."
echo "Using PAF in a repo for the first time? Run /paf:init there first."
