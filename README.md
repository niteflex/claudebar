# claudebar

Claude Code usage monitor for your terminal — rate limits, context, and model displayed right where you work.

```
☁  ████░░░░ 45% ↻23:45  ·  7d 63% ↻Apr 30 19:15  ·  ctx 35%  ·  ≈$8.20  Opus 4.7  ~/my-project
```

Two surfaces, one script:

- **StatusLine** — appears at the bottom of every Claude Code response
- **zsh RPROMPT** — appears on the right of your prompt, only in the terminal where Claude is running

## What it shows

| Segment | Meaning |
|---------|---------|
| `████░░░░ 45% ↻23:45` | 5-hour rate limit — bar + usage % + local reset time |
| `7d 63% ↻Apr 30 19:15` | 7-day rate limit + reset date and time |
| `ctx 35%` | Context window used in the current conversation |
| `≈$8.20` | API-equivalent cost this session (not actual billing for subscribers) |
| `Opus 4.7` | Active model |
| `~/my-project` | Current project folder |

### Colors

Traffic-light palette — color appears only when you're approaching a limit:

| Color | Threshold | Meaning |
|-------|-----------|---------|
| Green | < 60% | Healthy |
| Amber | 60–80% | Getting busy |
| Coral | ≥ 80% | Close to limit |

Works on both dark and light terminals.

## Requirements

- macOS or Linux
- Python 3.9+
- [Claude Code](https://claude.ai/code) CLI
- zsh

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/niteflex/claudebar/main/install.sh | bash
source ~/.zshrc
```

Then start a new Claude Code session — the status bar will appear on the first response.

### What the installer does

- Downloads `status.py` to `~/.claude/claudebar/`
- Adds `statusLine` to `~/.claude/settings.json`
- Adds the RPROMPT hook to `~/.zshrc` (idempotent — safe to run multiple times)

## How it works

Claude Code passes a JSON payload to the `statusLine` command on every response. claudebar reads it, formats the output, and writes to a cache at `/tmp/.claudebar_cache.json`.

The zsh RPROMPT reads from that cache — no polling, no extra processes. The RPROMPT only appears in the terminal where you launched Claude Code (tracked via `CC_SESSION_ID`) and fades out 10 minutes after Claude's last response.

## License

MIT
