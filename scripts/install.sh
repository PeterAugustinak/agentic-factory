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
#             -> ~/.claude/skills/_shared/        (shared helpers; not a skill)
#   - agents  -> ~/.claude/agents/paf/
#   - hooks   -> ~/.claude/hooks/paf/  (+ wired into ~/.claude/settings.json)
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

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }

# --- dependencies ---
command -v python3 >/dev/null 2>&1 || die "'python3' is required but not found."
if [ -z "${PAF_LOCAL_SRC:-}" ]; then
  command -v git >/dev/null 2>&1 || die "'git' is required but not found."
fi

echo "Installing PAF (Personal Agentic Factory)..."

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

mkdir -p "$SKILLS_DIR"

# --- skills (flat) ---
installed_skills=()
for d in "$SRC"/skills/*/; do
  name="$(basename "$d")"
  [ -f "$d/SKILL.md" ] || continue          # only real skills (skips README, _shared)
  rm -rf "${SKILLS_DIR:?}/$name"
  cp -R "$d" "$SKILLS_DIR/$name"
  installed_skills+=("$name")
done
[ "${#installed_skills[@]}" -gt 0 ] || die "no skills found in source."

# --- shared helpers (sibling of the skills) ---
rm -rf "${SKILLS_DIR:?}/_shared"
cp -R "$SRC/skills/_shared" "$SKILLS_DIR/_shared"
chmod +x "$SKILLS_DIR"/_shared/*.py 2>/dev/null || true

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

# --- wire the hook into settings.json (idempotent, preserves everything else) ---
python3 - "$SETTINGS" "$HOOKS_DIR/$HOOK_NAME" <<'PY'
import json, os, sys
settings_path, hook_path = sys.argv[1], sys.argv[2]
command = f"python3 {hook_path}"
matcher = "Bash|Edit|Write|MultiEdit"
try:
    with open(settings_path) as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        data = {}
except (FileNotFoundError, json.JSONDecodeError):
    data = {}
pre = data.setdefault("hooks", {}).setdefault("PreToolUse", [])
base = os.path.basename(hook_path)
def is_ours(entry):
    return any(base in (h.get("command") or "") for h in (entry or {}).get("hooks", []))
pre[:] = [e for e in pre if not is_ours(e)]   # drop any prior PAF entry
pre.append({"matcher": matcher, "hooks": [{"type": "command", "command": command}]})
os.makedirs(os.path.dirname(settings_path), exist_ok=True)
with open(settings_path, "w") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
PY

# --- post-install summary ---
skill_command() {  # print the frontmatter `name` (the invoke command) for a skill dir
  sed -n 's/^name:[[:space:]]*//p' "$SKILLS_DIR/$1/SKILL.md" | head -1 | tr -d '"'
}
echo
echo "PAF installed into $CLAUDE_DIR"
echo "  skills:  $SKILLS_DIR/<name>   (+ _shared)"
echo "  agents:  $AGENTS_DIR"
echo "  hook:    $HOOKS_DIR/$HOOK_NAME  (wired into settings.json)"
echo
echo "Skills — invoke in Claude Code:"
for s in "${installed_skills[@]}"; do
  cmd="$(skill_command "$s")"
  printf '  /%s\n' "${cmd:-$s}"
done
echo
echo "Start a new Claude Code session (or restart) to pick up the skills."
