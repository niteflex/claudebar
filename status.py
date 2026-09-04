#!/usr/bin/env python3
"""claudebar: Claude Code usage & context monitor.

Modes:
  --statusline   reads JSON from Claude Code stdin → formatted output
  --zsh          reads cache (populated by statusLine) → zsh RPROMPT string
  --bar          same bar in plain ANSI, for PowerShell / non-zsh prompts
  --cost         per-model $ breakdown for the current session (manual, on-demand)
  --update       refresh JSONL-based cache only, no output (background job)
"""

import json, os, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
CLAUDE_DIR    = Path.home() / ".claude"
PROJECTS_DIR  = CLAUDE_DIR / "projects"
SETTINGS      = CLAUDE_DIR / "settings.json"
CACHE         = Path("/tmp/.cc_status_cache.json")
CACHE_TTL_SHOW = 600  # hide RPROMPT 10 min after last Claude response
CACHE_TTL_COST = 1800 # --cost accepts a stdin cache up to 30 min old

BLOCK_H   = 5
CTX_LIMIT = 200_000

MODEL_SHORT = {
    # short aliases (may appear in ~/.claude/settings.json's "model" field)
    "sonnet": "sonnet",
    "opus":   "opus",
    "haiku":  "haiku",
    "fable":  "fable",
    "default": "?",
    # current model ids
    "claude-sonnet-5":            "sonnet",
    "claude-opus-5":              "opus",
    "claude-haiku-4-5":           "haiku",
    "claude-haiku-4-5-20251001":  "haiku",
    "claude-fable-5-1":           "fable",
    "claude-fable-5":             "fable",
    # retired ids — kept so old sessions still resolve to a short label
    "claude-sonnet-4-6": "sonnet",
    "claude-opus-4-6":   "opus",
    "claude-opus-4-7":   "opus",
    "claude-opus-4-8":   "opus",
}

# $ per MILLION tokens: (input, output, cache_write_5m, cache_read).
# The 1h cache-write tier costs 2x the 5m tier system-wide (applied below).
# Source: https://claude.com/pricing — verified 2026-09-04. Anthropic changes
# these; if a total looks off, check the live page before trusting this table.
PRICING = {
    "claude-haiku-4-5":           (1.00,  5.00,  1.25, 0.10),
    "claude-haiku-4-5-20251001":  (1.00,  5.00,  1.25, 0.10),
    "claude-sonnet-5":            (2.00, 10.00,  2.50, 0.20),
    "claude-opus-5":              (5.00, 25.00,  6.25, 0.50),
    "claude-fable-5-1":           (10.00, 50.00, 12.50, 0.25),
    # Fable 5's cache-read rate is unconfirmed — reuses Fable 5.1's as best effort.
    "claude-fable-5":             (10.00, 50.00, 12.50, 0.25),
}

# ── Color palette: monochrome + alert ────────────────────────────────────────
_GRAY  = "38;5;242"   # normal values
_GREEN = "38;5;114"   # context healthy (< 60%)
_AMBER = "38;5;215"   # warning
_CORAL = "38;5;203"   # critical
_LABEL = "38;5;244"   # dim labels, separators — readable on both dark/light bg
_EMPTY = "38;5;239"   # empty bar blocks — visible on black terminals

RST = "\033[0m"

def _code(pct: float) -> str:
    """Rate limits: green <60%, amber 60-80%, coral ≥80%."""
    return _CORAL if pct >= 80 else _AMBER if pct >= 60 else _GREEN

def _ctx_code(pct: float) -> str:
    """Context window: green <60%, amber 60-80%, coral ≥80%."""
    return _CORAL if pct >= 80 else _AMBER if pct >= 60 else _GREEN

def _a(code: str, t: str) -> str:
    return f"\033[{code}m{t}{RST}"

# statusLine helpers (raw ANSI, single %)
def mono(t: str, pct: float) -> str:
    return _a(_code(pct), t)

def ctxmono(t: str, pct: float) -> str:
    return _a(_ctx_code(pct), t)

def label(t: str) -> str:
    return _a(_LABEL, t)

def mono_bar(pct: float, w: int = 8) -> str:
    n = round(w * min(max(pct, 0), 100) / 100)
    filled = _a(_code(pct), "█" * n) if n else ""
    empty  = _a(_EMPTY, "░" * (w - n)) if n < w else ""
    return filled + empty

# zsh RPROMPT helpers (%{...%} zero-width wrappers, %% for literal %)
def _zc(code: str, t: str) -> str:
    return f"%{{\033[{code}m%}}{t}%{{\033[0m%}}"

def zmono(t: str, pct: float) -> str:
    return _zc(_code(pct), t)

def zctx(t: str, pct: float) -> str:
    return _zc(_ctx_code(pct), t)

def zlabel(t: str) -> str:
    return _zc(_LABEL, t)

def zmono_bar(pct: float, w: int = 8) -> str:
    n = round(w * min(max(pct, 0), 100) / 100)
    filled = _zc(_code(pct), "█" * n) if n else ""
    empty  = _zc(_EMPTY, "░" * (w - n)) if n < w else ""
    return filled + empty

# ── Formatting ────────────────────────────────────────────────────────────────
def fmt_reset(ts: float, full: bool = False) -> str:
    """Format reset timestamp as local time.
    full=False (5h): '14:30'
    full=True  (7d): 'Apr 30 07:11'
    """
    if ts - time.time() <= 0:
        return "now"
    dt = datetime.fromtimestamp(ts)
    if full:
        return dt.strftime("%b %-d %H:%M")  # Apr 30 07:11
    return dt.strftime("%H:%M")             # 14:30

def fmt_tok(n: int) -> str:
    if n >= 1_000_000: return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:     return f"{n / 1_000:.0f}k"
    return str(n)

def folder(path: str) -> str:
    home = str(Path.home())
    if path == home or path == home + "/":
        return "~"
    return "~/" + (Path(path.rstrip("/")).name or "~")

# ── Active check ──────────────────────────────────────────────────────────────
def is_claude_active() -> bool:
    c = load_cache()
    if not c or c.get("source") != "stdin":
        return False
    if (time.time() - c.get("ts", 0)) >= CACHE_TTL_SHOW:
        return False
    current_sid = os.environ.get("CC_SESSION_ID", "")
    if current_sid and c.get("session_id", "") != current_sid:
        return False  # this terminal has an ID that doesn't match the cached session
    return True

# ── Cache ─────────────────────────────────────────────────────────────────────
def load_cache() -> dict:
    try:
        if CACHE.exists():
            return json.loads(CACHE.read_text())
    except Exception:
        pass
    return {}

def save_cache(data: dict) -> None:
    try:
        CACHE.write_text(json.dumps(data))
    except Exception:
        pass

# ── JSONL fallback (for zsh when no Claude session is running) ────────────────
def _block_start(ts: datetime) -> datetime:
    h = (ts.hour // BLOCK_H) * BLOCK_H
    return ts.replace(hour=h, minute=0, second=0, microsecond=0)

def collect_jsonl() -> dict:
    now      = datetime.now(timezone.utc)
    cur_bs   = _block_start(now)
    cur_be   = cur_bs + timedelta(hours=BLOCK_H)
    week_ago = now - timedelta(days=7)
    block_hist: dict[str, int] = {}
    cur_block = 0
    weekly    = 0

    for jpath in PROJECTS_DIR.rglob("*.jsonl"):
        try:
            file_blocks: dict[str, int] = {}
            with open(jpath, errors="ignore") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw or '"assistant"' not in raw:
                        continue
                    try:
                        e = json.loads(raw)
                    except Exception:
                        continue
                    if e.get("type") != "assistant":
                        continue
                    usage = e.get("message", {}).get("usage")
                    if not usage:
                        continue
                    try:
                        ts = datetime.fromisoformat(
                            e.get("timestamp", "").replace("Z", "+00:00"))
                    except Exception:
                        continue
                    tok = (usage.get("input_tokens", 0)
                           + usage.get("output_tokens", 0)
                           + usage.get("cache_creation_input_tokens", 0)
                           + usage.get("cache_read_input_tokens", 0))
                    if ts >= week_ago:
                        weekly += tok
                    if ts >= cur_bs:
                        cur_block += tok
                    bs_iso = _block_start(ts).isoformat()
                    file_blocks[bs_iso] = file_blocks.get(bs_iso, 0) + tok
            for k, v in file_blocks.items():
                block_hist[k] = block_hist.get(k, 0) + v
        except Exception:
            continue

    hist_vals   = [v for k, v in block_hist.items() if k != cur_bs.isoformat()]
    block_limit = max(hist_vals) if hist_vals else max(cur_block, 1)
    block_pct   = min(int(cur_block / block_limit * 100), 100)

    return {
        "five_h_pct":    block_pct,
        "five_h_reset":  int(cur_be.timestamp()),
        "seven_d_pct":   None,
        "seven_d_reset": None,
        "ctx_pct":       None,
        "cost_usd":      0.0,
        "model":         None,
        "source":        "jsonl",
        "ts":            time.time(),
    }

def settings_model() -> str:
    try:
        s = json.loads(SETTINGS.read_text())
        m = s.get("model", "")
        return MODEL_SHORT.get(m, m) or "?"
    except Exception:
        return "?"

# ── Render: statusLine ────────────────────────────────────────────────────────
# Layout B: ctx 49%  ██████░░ 68%  1h12m  ·  7d 31%  3d  ·  ×4 $4.52  sonnet  mira
def render_statusline() -> None:
    try:
        raw = sys.stdin.read()
        d   = json.loads(raw) if raw.strip() else {}
    except Exception:
        d = {}

    ctx_d   = d.get("context_window") or {}
    rate    = d.get("rate_limits") or {}
    cost_d  = d.get("cost") or {}
    model_d = d.get("model") or {}
    ws      = d.get("workspace") or {}

    ctx_pct     = float(ctx_d.get("used_percentage") or 0)
    five_h      = rate.get("five_hour") or {}
    seven_d     = rate.get("seven_day") or {}
    five_h_pct  = float(five_h.get("used_percentage", 0)) if five_h else None
    five_h_rst  = five_h.get("resets_at")
    seven_d_pct = float(seven_d.get("used_percentage", 0)) if seven_d else None
    seven_d_rst = seven_d.get("resets_at")
    cost_usd    = float(cost_d.get("total_cost_usd") or 0)
    model_name  = model_d.get("display_name") or model_d.get("id") or "?"
    cwd         = ws.get("current_dir") or d.get("cwd") or os.getcwd()
    now         = time.time()

    save_cache({
        "five_h_pct":    five_h_pct,
        "five_h_reset":  five_h_rst,
        "seven_d_pct":   seven_d_pct,
        "seven_d_reset": seven_d_rst,
        "ctx_pct":       ctx_pct,
        "cost_usd":      cost_usd,
        "model":         model_name,
        "source":        "stdin",
        "session_id":    os.environ.get("CC_SESSION_ID", ""),
        "transcript_path": d.get("transcript_path"),
        "ts":            now,
    })

    DOT   = label("  ·  ")
    SPACE = "  "
    parts: list[str] = []

    # Group 1: 5h rate limit — always show reset clock time
    if five_h_pct is not None:
        seg = mono_bar(five_h_pct) + " " + mono(f"{int(five_h_pct)}%", five_h_pct)
        if five_h_rst:
            seg += " " + label("↻" + fmt_reset(five_h_rst))
        parts.append(seg)

    # Group 2: 7-day — date if >24h away, clock time if ≤24h
    if seven_d_pct is not None:
        seg = label("7d ") + mono(f"{int(seven_d_pct)}%", seven_d_pct)
        if seven_d_rst:
            seg += " " + label("↻" + fmt_reset(seven_d_rst, full=True))
        parts.append(seg)

    # Group 3: ctx — color: green <60%, amber 60-80%, coral ≥80%
    if ctx_pct > 2:
        parts.append(label("ctx ") + _a(_ctx_code(ctx_pct), f"{int(ctx_pct)}%"))

    # Group 4: cost (≈ prefix signals API-equivalent, not real spend) + model + folder
    tail = ""
    if cost_usd >= 0.01:
        tail = label(f"≈${cost_usd:.2f}") + SPACE
    tail += label(model_name) + SPACE + label(folder(cwd))
    parts.append(tail)

    print("☁  " + DOT.join(parts), end="")

# ── Render: prompt bar (zsh RPROMPT / PowerShell prompt) ─────────────────────
# Layout B compact: ██████░░ 68% ↻14:30  ·  7d 31% ↻Apr 30 07:11  ·  ctx 42%  ·  ≈$4.52  sonnet
def render_bar(zsh: bool = True) -> None:
    if not is_claude_active():
        return

    # is_claude_active() already guarantees a stdin-sourced cache newer than
    # CACHE_TTL_SHOW, so trust it directly — a second, tighter freshness check
    # here used to fall through to collect_jsonl()'s heuristic (and its full
    # rglob over ~/.claude/projects) on every prompt redraw between 5 and 10
    # minutes after Claude's last response.
    c = load_cache()

    five_h_pct  = c.get("five_h_pct")
    five_h_rst  = c.get("five_h_reset")
    seven_d_pct = c.get("seven_d_pct")
    seven_d_rst = c.get("seven_d_reset")
    cost_usd    = c.get("cost_usd", 0)
    model_name  = c.get("model") or settings_model()

    # zsh needs %{...%} zero-width wrappers and %% for a literal percent; every
    # other shell (PowerShell) wants plain ANSI and a bare %.
    if zsh:
        col, ctxcol, bar, lab, PCT = zmono, zctx, zmono_bar, zlabel, "%%"
    else:
        col, ctxcol, bar, lab, PCT = mono, ctxmono, mono_bar, label, "%"

    DOT   = lab("  ·  ")
    SPACE = "  "
    parts: list[str] = []

    # 5h — always clock time
    if five_h_pct is not None:
        seg = bar(five_h_pct) + " " + col(f"{int(five_h_pct)}{PCT}", five_h_pct)
        if five_h_rst:
            seg += " " + lab("↻" + fmt_reset(five_h_rst))
        parts.append(seg)

    # 7d — date if >24h, clock time if ≤24h
    if seven_d_pct is not None:
        seg = lab("7d ") + col(f"{int(seven_d_pct)}{PCT}", seven_d_pct)
        if seven_d_rst:
            seg += " " + lab("↻" + fmt_reset(seven_d_rst, full=True))
        parts.append(seg)

    # ctx — green <60%, amber 60-80%, coral ≥80%
    ctx_pct_c = c.get("ctx_pct")
    if ctx_pct_c and ctx_pct_c > 2:
        parts.append(lab("ctx ") + ctxcol(f"{int(ctx_pct_c)}{PCT}", ctx_pct_c))

    # cost (≈ = API-equivalent, not real spend) + model
    tail = ""
    if cost_usd and cost_usd >= 0.01:
        tail = lab(f"≈${cost_usd:.2f}") + SPACE
    tail += lab(model_name)
    parts.append(tail)

    print("☁ " + DOT.join(parts), end="")

# ── Render: --cost (manual, on-demand per-model breakdown) ────────────────────
def _tally_transcript(path: Path) -> dict[str, dict[str, int]]:
    """Sum token usage per model id across one session transcript."""
    per_model: dict[str, dict[str, int]] = {}
    with open(path, errors="ignore") as f:
        for raw in f:
            raw = raw.strip()
            if not raw or '"assistant"' not in raw:
                continue
            try:
                e = json.loads(raw)
            except Exception:
                continue
            if e.get("type") != "assistant":
                continue
            msg   = e.get("message") or {}
            usage = msg.get("usage")
            if not usage:
                continue
            mid = msg.get("model") or "?"
            t = per_model.setdefault(
                mid, {"input": 0, "output": 0, "cw5m": 0, "cw1h": 0, "read": 0})

            # Prefer the explicit 5m/1h split when the entry carries it; the flat
            # cache_creation_input_tokens field merges both tiers, so falling back
            # to it slightly undercounts when 1h caching was used (1h costs 2x).
            cc = usage.get("cache_creation")
            if isinstance(cc, dict):
                t["cw5m"] += cc.get("ephemeral_5m_input_tokens", 0) or 0
                t["cw1h"] += cc.get("ephemeral_1h_input_tokens", 0) or 0
            else:
                t["cw5m"] += usage.get("cache_creation_input_tokens", 0) or 0

            t["input"]  += usage.get("input_tokens", 0) or 0
            t["output"] += usage.get("output_tokens", 0) or 0
            t["read"]   += usage.get("cache_read_input_tokens", 0) or 0
    return per_model

def render_cost() -> None:
    c = load_cache()
    fresh = (c.get("source") == "stdin"
             and (time.time() - c.get("ts", 0)) < CACHE_TTL_COST)
    tpath = c.get("transcript_path") if fresh else None
    if not tpath or not Path(tpath).is_file():
        print("No active Claude Code session detected — run this from a terminal "
              "where Claude Code is running, after at least one response.")
        return

    per_model = _tally_transcript(Path(tpath))
    if not per_model:
        print(f"No assistant messages with usage data found in {tpath}")
        return

    rows, total, unpriced_tokens = [], 0.0, 0
    for mid, t in sorted(per_model.items()):
        price = PRICING.get(mid)
        tok_total = t["input"] + t["output"] + t["cw5m"] + t["cw1h"] + t["read"]
        if price:
            pin, pout, pcw, pread = price
            usd = (t["input"] * pin
                   + t["output"] * pout
                   + t["cw5m"] * pcw
                   + t["cw1h"] * pcw * 2   # 1h cache-write tier costs 2x the 5m tier
                   + t["read"] * pread) / 1_000_000
            total += usd
            cost_s = f"${usd:.4f}"
        else:
            unpriced_tokens += tok_total
            cost_s = "?"
        rows.append((MODEL_SHORT.get(mid, mid)[:13], t, cost_s))

    W = (14, 12, 12, 14, 14, 12)
    head = ("model", "input", "output", "cache write", "cache read", "cost")
    print(label("claudebar — session cost breakdown"))
    print(label(tpath))
    print()
    print(label(f"{head[0]:<{W[0]}}{head[1]:>{W[1]}}{head[2]:>{W[2]}}"
                f"{head[3]:>{W[3]}}{head[4]:>{W[4]}}{head[5]:>{W[5]}}"))
    print(label("─" * sum(W)))
    for name, t, cost_s in rows:
        cw = t["cw5m"] + t["cw1h"]
        print(f"{name:<{W[0]}}{t['input']:>{W[1]},}{t['output']:>{W[2]},}"
              f"{cw:>{W[3]},}{t['read']:>{W[4]},}{cost_s:>{W[5]}}")
    print(label("─" * sum(W)))
    agg = {k: sum(t[k] for _, t, _ in rows)
           for k in ("input", "output", "cw5m", "cw1h", "read")}
    print(f"{'total':<{W[0]}}{agg['input']:>{W[1]},}{agg['output']:>{W[2]},}"
          f"{agg['cw5m'] + agg['cw1h']:>{W[3]},}{agg['read']:>{W[4]},}"
          f"{'$' + format(total, '.4f'):>{W[5]}}")
    print()
    cc_est = c.get("cost_usd")
    if cc_est is not None:
        print(f"Claude Code's own estimate:           ${float(cc_est):.2f}")
    print(f"claudebar per-model breakdown total:  ${total:.2f}")
    print(label("The two are computed independently and may differ; neither is "
                "authoritative billing."))
    if unpriced_tokens:
        print(label(f"{unpriced_tokens:,} tokens belong to models missing from the "
                    "pricing table and are excluded from the total."))
    subs = Path(tpath).with_suffix("") / "subagents"
    if subs.is_dir():
        print(label("Subagent transcripts exist for this session and are not "
                    "included — this covers the main conversation only."))

# ── Entry point ───────────────────────────────────────────────────────────────
def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "--zsh"
    if mode == "--update":
        save_cache(collect_jsonl())
    elif mode == "--statusline":
        render_statusline()
    elif mode == "--cost":
        render_cost()
    elif mode == "--bar":
        render_bar(zsh=False)   # plain ANSI — PowerShell and other non-zsh prompts
    else:
        render_bar(zsh=True)

if __name__ == "__main__":
    main()
