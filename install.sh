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
