# cc-status

Claude Code usage monitor for your terminal — rate limits, context window, cost, and model, right where you work.

```
☁  ████░░░░ 43%  2h18m  ·  7d 31%  3d  ·  ctx 22%  ·  $4.52  Sonnet 4.6  my-project
```

Two surfaces, one script:

- **StatusLine** — appears at the bottom of every Claude Code response
- **zsh RPROMPT** — appears on the right side of your prompt, only when Claude is running

## What it shows

| Segment | Meaning |
|---------|---------|
| `████░░░░ 43%  2h18m` | 5-hour rate limit — usage bar + % + time until reset |
| `7d 31%  3d` | 7-day rate limit + time until reset |
| `ctx 22%` | Context window used in the current conversation |
| `$4.52` | Session cost (API users only — hidden when zero) |
| `Sonnet 4.6` | Active model |
| `my-project` | Current project folder |

Colors stay gray until you approach a limit — amber at 70%, coral at 90%.

## Requirements

- macOS or Linux
- Python 3.9+
- [Claude Code](https://claude.ai/code) CLI
- zsh (for RPROMPT)

## Install

**1. Copy the script**

```bash
mkdir -p ~/.claude/cc-status
curl -o ~/.claude/cc-status/status.py \
  https://raw.githubusercontent.com/YOUR_USERNAME/cc-status/main/status.py
```

**2. Wire up the Claude Code statusLine**

Add to `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "python3 ${CLAUDE_CONFIG_DIR:-$HOME/.claude}/cc-status/status.py --statusline"
  }
}
```

If `settings.json` already has other content, add just the `"statusLine"` key.

**3. Wire up the zsh RPROMPT**

Add to `~/.zshrc`:

```zsh
_cc_status_cache="/tmp/.cc_status_cache.json"
_cc_status_ttl=60

_cc_status_update() {
  local mtime age
  mtime=$(stat -f %m "$_cc_status_cache" 2>/dev/null || echo 0)
  age=$(( $(date +%s) - mtime ))
  (( age < _cc_status_ttl )) && return
  ( python3 ~/.claude/cc-status/status.py --update > /dev/null 2>&1 ) &!
}

_cc_status_precmd() {
  _cc_status_update
  RPROMPT="$(python3 ~/.claude/cc-status/status.py --zsh 2>/dev/null)"
}
precmd_functions+=(_cc_status_precmd)
```

Then reload:

```bash
source ~/.zshrc
```

## How it works

Claude Code passes a JSON payload to the `statusLine` command on every response. The script reads it, formats the output, and caches the values to `/tmp/.cc_status_cache.json`.

The zsh RPROMPT reads from that cache — no extra API calls, no polling. It only renders when the `claude` process is running; disappears when you close Claude Code.

For the 5-hour rate limit, when official API data is unavailable (subscription users), the script falls back to estimating usage by scanning `~/.claude/projects/**/*.jsonl`.

## Color palette

Everything is gray by default. Color appears only when a limit is close.

| Color | Threshold | 256-color |
|-------|-----------|-----------|
| Gray | default | `242` |
| Amber | ≥ 70% | `215` |
| Coral | ≥ 90% | `203` |

Works on both dark and light terminals.

## License

MIT
