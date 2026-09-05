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
| `ctx 35%` | Share of the model's context window used — i.e. room left before Claude Code force-compacts |
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

**Context (`ctx`)** — by *absolute token count*, not percentage of the window:

| Color | Threshold |
|-------|-----------|
| Green | < 120K tokens |
| Amber | 120K–160K tokens |
| Coral | ≥ 160K tokens |

The number stays a percentage (how full the window is), but the color is driven by
real tokens so it means the same thing whether you're on a 200K- or a 1M-context
model. Anthropic publishes no "quality drops here" threshold; 120K/160K reproduces
the old 60%/80%-of-200K calibration that practice settled on. On a 1M-context model
the bar will look conservative — coral at ~16% of the window — by design. Adjust
`CTX_AMBER_TOKENS` / `CTX_CORAL_TOKENS` at the top of `status.py` to taste.

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
Two things changed, neither of them a bug:

1. **The `ctx` color is now absolute-token based** (see [Colors](#colors)). Older
   claudebar colored at 60%/80% of the window; on a 200K window that was 120K/160K
   tokens, but on today's 1M-context models (Sonnet 5, Opus 5) the same 80% is 800K
   tokens — far past where you'd actually want to compact. The new fixed thresholds
   restore the old behavior in real terms.
2. **Claude Code's auto-compact scales with the window.** It fires near the top of
   whatever window the model has — roughly the full ~200K on a 200K model, ~967K on
   a 1M model. So the raw percentage naturally sits higher before anything happens
   on a big-window model. To force earlier auto-compaction, run `/autocompact 200k`
   in Claude Code or set `CLAUDE_CODE_AUTO_COMPACT_WINDOW=200000`. This is a Claude
   Code setting; claudebar only reads the number.

**The bar shows stale numbers, or nothing at all.**
It only appears in the terminal whose `CC_SESSION_ID` matches the running session,
and it hides 10 minutes after Claude's last response. If your `~/.zshrc` has more
than one claudebar-style precmd hook, re-run the installer — it strips stale hooks
left over from older versions.

## License

MIT
