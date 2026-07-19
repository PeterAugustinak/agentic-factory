#!/usr/bin/env bash
#
# uninstall.sh — remove PAF (Personal Agentic Factory) from your Claude Code config.
#
#   curl -sSL https://raw.githubusercontent.com/PeterAugustinak/agentic-factory/develop/scripts/uninstall.sh | bash
#
# Removes exactly what install.sh adds and nothing else:
#   - PAF skills (identified by a `paf:` frontmatter name) + ~/.claude/skills/paf-shared/
#   - ~/.claude/agents/paf/ and ~/.claude/hooks/paf/
#   - the PAF hook entry from ~/.claude/settings.json (other settings untouched)
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

# --- settings.json: strip only the PAF hook entry ---
if [ -f "$SETTINGS" ]; then
  python3 - "$SETTINGS" "$HOOK_NAME" <<'PY'
import json, sys
path, base = sys.argv[1], sys.argv[2]
try:
    with open(path) as fh:
        d = json.load(fh)
except (FileNotFoundError, json.JSONDecodeError):
    raise SystemExit
pre = d.get("hooks", {}).get("PreToolUse")
if isinstance(pre, list):
    keep = [e for e in pre
            if not any(base in (h.get("command") or "") for h in (e or {}).get("hooks", []))]
    if keep:
        d["hooks"]["PreToolUse"] = keep
    else:
        d["hooks"].pop("PreToolUse", None)
        if not d["hooks"]:
            d.pop("hooks", None)
    with open(path, "w") as fh:
        json.dump(d, fh, indent=2)
        fh.write("\n")
    print("STRIPPED")
PY
  removed+=("settings.json PreToolUse entry")
fi

if [ "${#removed[@]}" -eq 0 ]; then
  echo "Nothing to remove — PAF was not installed here."
else
  echo "Removed:"
  for r in "${removed[@]}"; do echo "  - $r"; done
  echo "PAF uninstalled."
fi
