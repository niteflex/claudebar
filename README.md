# claudebar

Claude Code usage monitor for your terminal — rate limits, context, and model displayed right where you work.

```
☁  ████░░░░ 45% ↻23:45  ·  7d 63% ↻Sep 7 19:15  ·  ctx 35%  ·  ≈$8.20  Sonnet 5  ~/my-project
```

Two surfaces, one script:

- **StatusLine** — appears at the bottom of every Claude Code response
- **zsh RPROMPT** — appears on the right of your prompt, only in the terminal where Claude is running

## What it shows

| Segment | Meaning |
|---------|---------|
| `████░░░░ 45% ↻23:45` | 5-hour rate limit — bar + usage % + local reset time |
| `7d 63% ↻Apr 30 19:15` | 7-day rate limit + reset date and time |
| `ctx 35%` | Share of the active model's context window used — room left before Claude Code force-compacts |
| `≈$8.20` | API-equivalent cost this session (not actual billing for subscribers) |
| `Opus 4.7` | Active model |
| `~/my-project` | Current project folder |

### Colors

Traffic-light palette — color appears only when you're approaching a limit. Works on both dark and light terminals.

**Rate limits (`5h`, `7d`)** — by percentage of the limit:

| Color | Threshold |
|-------|-----------|
| Green | < 60% |
| Amber | 60–80% |
| Coral | ≥ 80% |

**Context (`ctx`)** — by percentage of the *active model's real context window*
(Claude Code reports it live — 200K, 1M, whatever the current model has):

| Color | Threshold |
|-------|-----------|
| Green | < 70% |
| Amber | 70–85% |
| Coral | ≥ 85% |

The denominator is the current model's own window, so the color adapts per model
with no hardcoded ceiling. Auto-compact fires near the top of that window
(~97–100%), so coral is your margin to wrap up or `/clear` on your own terms
before Claude Code does it for you. Tune `CTX_AMBER_PCT` / `CTX_CORAL_PCT` at the
top of `status.py`.

## Cost breakdown

```bash
python3 ~/.claude/claudebar/status.py --cost
```

Prints a per-model table for the current session — input, output, cache-write and
cache-read tokens with a dollar figure per model, plus Claude Code's own estimate
alongside claudebar's, computed independently. This is a manual, on-demand command;
it is not part of the live bar.

It reads the current session's transcript **and every subagent transcript that
session spawned**, so it reflects what the whole task cost in that terminal window —
not just the main conversation. Subagents usually run a different model than the
one driving the chat (Sonnet up front, Opus/Haiku in the background), and each gets
its own row. Prices are a static table in `status.py` (verified against
claude.com/pricing on the date in the file's comment); it resets when you `/clear`.

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

**Context climbs past 95% now; it used to turn red around 80%.**
`ctx %` is now a percentage of the *active model's real context window*, which
Claude Code reports live (200K on a 200K model, 1M on Sonnet 5 / Opus 5). The
color turns amber at 70% and coral at 85% of that window — so it adapts to
whichever model you're running, no fixed ceiling. Auto-compact itself fires near
the top of the window (~97–100%) regardless of model. To make Claude Code compact
earlier, run `/autocompact 200k` or set `CLAUDE_CODE_AUTO_COMPACT_WINDOW=200000` —
that's a Claude Code setting; claudebar only reads the number.

**The bar shows stale numbers, or nothing at all.**
It only appears in the terminal whose `CC_SESSION_ID` matches the running session,
and it hides 10 minutes after Claude's last response. If your `~/.zshrc` has more
than one claudebar-style precmd hook, re-run the installer — it strips stale hooks
left over from older versions.

## License

MIT

## Notifications (macOS)

`status.py --notify done|attention` turns Claude Code's `Stop` / `Notification` hooks into Notification Center alerts titled `Claude · <repo folder>`.

- **done** fires only when Claude has really stopped: it waits ~12 s and stays silent if the transcript keeps growing (autonomous modes). Replies under 20 s are skipped.
- **attention** fires when Claude waits for a permission or an answer.
- **limits**: the statusLine raises one alert per window at 80 / 95 / 100 % of the 5-hour and weekly limits, and a "limit reset" notice after a limit-reached stop.
- Click a notification to raise the exact Terminal.app tab (`brew install terminal-notifier`; without it you still get alerts, but no click-to-focus).

Hooks in `~/.claude/settings.json`:

```json
"Stop":         [{"hooks":[{"type":"command","command":"python3 \"$HOME/.claude/claudebar/status.py\" --notify done"}]}],
"Notification": [{"hooks":[{"type":"command","command":"python3 \"$HOME/.claude/claudebar/status.py\" --notify attention"}]}]
```
