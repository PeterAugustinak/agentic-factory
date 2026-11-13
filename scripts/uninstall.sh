#!/usr/bin/env bash
#
# uninstall.sh — remove PAF (Personal Agentic Factory) from your Claude Code config.
#
#   curl -sSL https://raw.githubusercontent.com/PeterAugustinak/agentic-factory/develop/scripts/uninstall.sh | bash
#
# Removes exactly what install.sh adds and nothing else:
#   - PAF skills (identified by a `paf:` frontmatter name) + ~/.claude/skills/paf-shared/
#   - ~/.claude/agents/paf/ and ~/.claude/hooks/paf/
#   - a PAF hook entry an earlier version wired into ~/.claude/settings.json (other settings untouched)
#
# Env override: CLAUDE_CONFIG_DIR (default: ~/.claude)

set -euo pipefail

CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
SKILLS_DIR="$CLAUDE_DIR/skills"
SETTINGS="$CLAUDE_DIR/settings.json"
HOOK_NAME="PreToolUse-agent-guard.py"
PAF_DIR="$CLAUDE_DIR/paf"
MARKER="$PAF_DIR/VERSION"

if [ -f "$MARKER" ]; then
  echo "Uninstalling PAF v$(tr -d '[:space:]' < "$MARKER") from $CLAUDE_DIR..."
else
  echo "Uninstalling PAF from $CLAUDE_DIR..."
fi
removed=()

# --- skills: any whose frontmatter `name` is paf:-prefixed, plus the shared helpers ---
if [ -d "$SKILLS_DIR" ]; then
  for f in "$SKILLS_DIR"/*/SKILL.md; do
    [ -f "$f" ] || continue
    if grep -Eq '^name:[[:space:]]*"?paf:' "$f"; then
      d="$(dirname "$f")"; rm -rf "$d"; removed+=("skills/$(basename "$d")")
    fi
  done
  if [ -d "$SKILLS_DIR/paf-shared" ]; then rm -rf "$SKILLS_DIR/paf-shared"; removed+=("skills/paf-shared"); fi
fi

# --- agents + hooks (installed under their own paf/ namespace) ---
[ -d "$CLAUDE_DIR/agents/paf" ] && { rm -rf "$CLAUDE_DIR/agents/paf"; removed+=("agents/paf"); }
[ -d "$CLAUDE_DIR/hooks/paf" ]  && { rm -rf "$CLAUDE_DIR/hooks/paf";  removed+=("hooks/paf"); }

# --- installed-version marker (the cost ledger in the same dir is left alone) ---
if [ -f "$MARKER" ]; then
  rm -f "$MARKER"; removed+=("paf/VERSION")
  rmdir "$PAF_DIR" 2>/dev/null || true   # only if nothing else (e.g. costs/) remains
fi

# --- settings.json: strip only a PAF hook entry an earlier version wired in ---
# Rewritten only when it holds one; the same snippet is in install.sh.
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
  if [ "$stripped" = "STRIPPED" ]; then removed+=("settings.json PreToolUse entry"); fi
fi

if [ "${#removed[@]}" -eq 0 ]; then
  echo "Nothing to remove — PAF was not installed here."
else
  echo "Removed:"
  for r in "${removed[@]}"; do echo "  - $r"; done
  echo "PAF uninstalled."
fi
