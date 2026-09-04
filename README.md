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

## Cost breakdown

```bash
python3 ~/.claude/claudebar/status.py --cost
```

Prints a per-model table for the current session — input, output, cache-write and
cache-read tokens with a dollar figure per model, plus Claude Code's own estimate
alongside claudebar's, computed independently. This is a manual, on-demand command;
it is not part of the live bar. It reads the current session's transcript, so it
covers the main conversation only and resets when you `/clear`.

## Requirements

- macOS, Linux, or Windows
- Python 3.9+
- [Claude Code](https://claude.ai/code) CLI
- zsh (macOS/Linux) or PowerShell (Windows)

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

## Install — Windows

```powershell
irm https://raw.githubusercontent.com/niteflex/claudebar/main/install.ps1 | iex
. $PROFILE
```

Python 3.9+ must be installed and on `PATH` (the installer prefers `python3` and
falls back to `python`; if neither resolves it tells you and stops).

The prompt bar needs a PowerShell profile, which the installer creates and patches
for you. PowerShell honors only the *last* `function prompt` definition, so if you
already use oh-my-posh, starship, or a hand-rolled prompt, the installer leaves your
profile alone and prints the two lines to paste into your existing prompt function
instead of silently disabling one of them. The statusLine half works either way.

## How it works

Claude Code passes a JSON payload to the `statusLine` command on every response. claudebar reads it, formats the output, and writes to a cache at `/tmp/.cc_status_cache.json`.

The zsh RPROMPT reads from that cache — no polling, no extra processes. The RPROMPT only appears in the terminal where you launched Claude Code (tracked via `CC_SESSION_ID`) and fades out 10 minutes after Claude's last response.

On Windows the same cache feeds a `function prompt` override in your PowerShell
profile, which calls `status.py --bar` (plain ANSI) instead of `--zsh` (which emits
zsh-specific prompt escapes).

## Troubleshooting

**Cost resets to $0 after I `/clear`.**
That's Claude Code's own behavior since v2.1.211 — before that, the total carried
over across `/clear`. The `≈$` figure always reflects the current session only.
`--cost` resets too, since it reads the same transcript.

**Context climbs past 95% now; it used to reset around 80%.**
Claude Code's auto-compact fires at an absolute token count that scales with the
model's context window, not at a fixed percentage. A ~200K-window model compacts
around 160K tokens (≈80%), while a 1M-context model like Sonnet 5 or Opus 5 compacts
around 967K tokens (≈97%) — so switching your default model changes where the bar
appears to turn over. To get the old feel back on a 1M-context model, run
`/autocompact 160k` in Claude Code, or set `CLAUDE_CODE_AUTO_COMPACT_WINDOW=160000`.
This is a Claude Code setting; claudebar only displays the number.

**The bar shows stale numbers, or nothing at all.**
It only appears in the terminal whose `CC_SESSION_ID` matches the running session,
and it hides 10 minutes after Claude's last response. If your `~/.zshrc` has more
than one claudebar-style precmd hook, re-run the installer — it strips stale hooks
left over from older versions.

## License

MIT
