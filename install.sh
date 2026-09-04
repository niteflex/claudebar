#!/usr/bin/env bash
set -e

REPO="https://raw.githubusercontent.com/niteflex/claudebar/main"
INSTALL_DIR="$HOME/.claude/claudebar"
SETTINGS="$HOME/.claude/settings.json"
ZSHRC="$HOME/.zshrc"

echo "Installing claudebar..."

# 1. Download script
mkdir -p "$INSTALL_DIR"
curl -fsSL "$REPO/status.py" -o "$INSTALL_DIR/status.py"
echo "  ✓ status.py → $INSTALL_DIR/"

# 2. Patch settings.json
if [ ! -f "$SETTINGS" ]; then
  echo '{}' > "$SETTINGS"
fi

python3 - "$SETTINGS" <<'EOF'
import json, sys
path = sys.argv[1]
with open(path) as f:
    data = json.load(f)
data["statusLine"] = {
    "type": "command",
    "command": "python3 $HOME/.claude/claudebar/status.py --statusline"
}
with open(path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
EOF
echo "  ✓ statusLine added to $SETTINGS"

# 3. Patch .zshrc (idempotent)

# 3a. Migration: strip any leftover block from the old "cc-status" name.
# That block calls ~/.claude/cc-status/status.py, which no longer exists, so it
# spawns a doomed python3 process on every prompt redraw. Runs before the
# claudebar check below so an existing install self-heals too. No-op when clean.
if [ -f "$ZSHRC" ] && grep -q "_cc_status_precmd" "$ZSHRC" 2>/dev/null; then
  python3 - "$ZSHRC" <<'EOF'
import re, sys
path  = sys.argv[1]
lines = open(path, encoding="utf-8").read().splitlines(keepends=True)

def find(pred, start=0):
    for i in range(start, len(lines)):
        if pred(lines[i]):
            return i
    return -1

fn  = find(lambda l: re.match(r"\s*_cc_status_precmd\s*\(\)", l))
if fn != -1:
    # Start at the "# cc-status:" comment when it directly precedes the block
    # (allowing extra comment/export/blank lines between it and the function).
    cmt = find(lambda l: re.match(r"\s*#\s*cc-status\b", l))
    start = cmt if 0 <= cmt < fn else fn
    # End at the precmd_functions registration, else at the function's closing brace.
    end = find(lambda l: "precmd_functions" in l and "_cc_status_precmd" in l, fn)
    if end == -1:
        end = find(lambda l: l.strip() == "}", fn)
    if end == -1:
        end = fn
    del lines[start:end + 1]
    # Collapse the blank-line gap the removal may have left behind.
    while (start < len(lines) and not lines[start].strip()
           and (start == 0 or not lines[start - 1].strip())):
        del lines[start]
    open(path, "w", encoding="utf-8").write("".join(lines))
    print("  ✓ removed stale cc-status hook from ~/.zshrc")
EOF
fi

ZSHRC_BLOCK='
# claudebar: Claude Code usage monitor
export CC_SESSION_ID="$$"
_claudebar_precmd() {
  RPROMPT="$(python3 ~/.claude/claudebar/status.py --zsh 2>/dev/null)"
}
precmd_functions+=(_claudebar_precmd)'

if grep -q "claudebar" "$ZSHRC" 2>/dev/null; then
  echo "  ✓ ~/.zshrc already patched — skipping"
else
  printf '%s\n' "$ZSHRC_BLOCK" >> "$ZSHRC"
  echo "  ✓ RPROMPT hook added to $ZSHRC"
fi

echo ""
echo "Done. Reload your shell:"
echo "  source ~/.zshrc"
echo ""
echo "Then start a new Claude Code session — the status bar will appear on the first response."
