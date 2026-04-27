#!/usr/bin/env python3
"""cc-status: Claude Code usage & context monitor.

Modes:
  --statusline   reads JSON from Claude Code stdin → formatted output
  --zsh          reads cache (populated by statusLine) → zsh RPROMPT string
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
CACHE_TTL_ZSH  = 60
CACHE_TTL_SHOW = 600  # hide RPROMPT 10 min after last Claude response

BLOCK_H   = 5
CTX_LIMIT = 200_000

MODEL_SHORT = {
    "sonnet": "sonnet", "claude-sonnet-4-6": "sonnet",
    "haiku":  "haiku",  "claude-haiku-4-5-20251001": "haiku",
    "opus":   "opus",   "claude-opus-4-7": "opus",
    "default": "?",
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

# ── Render: zsh RPROMPT ───────────────────────────────────────────────────────
# Layout B compact: ██████░░ 68%  1h12m  ·  7d 31%  3d  ·  ×4  sonnet
def render_zsh() -> None:
    if not is_claude_active():
        return

    c   = load_cache()
    now = time.time()

    if c and c.get("source") == "stdin" and (now - c.get("ts", 0)) < 300:
        five_h_pct  = c.get("five_h_pct")
        five_h_rst  = c.get("five_h_reset")
        seven_d_pct = c.get("seven_d_pct")
        seven_d_rst = c.get("seven_d_reset")
        cost_usd    = c.get("cost_usd", 0)
        model_name  = c.get("model") or settings_model()
    else:
        jd = collect_jsonl() if not c or (now - c.get("ts", 0)) > CACHE_TTL_ZSH else c
        five_h_pct  = jd.get("five_h_pct")
        five_h_rst  = jd.get("five_h_reset")
        seven_d_pct = jd.get("seven_d_pct")
        seven_d_rst = jd.get("seven_d_reset")
        cost_usd    = jd.get("cost_usd", 0)
        model_name  = jd.get("model") or settings_model()

    DOT   = zlabel("  ·  ")
    SPACE = "  "
    parts: list[str] = []

    # 5h — always clock time
    if five_h_pct is not None:
        seg = zmono_bar(five_h_pct) + " " + zmono(f"{int(five_h_pct)}%%", five_h_pct)
        if five_h_rst:
            seg += " " + zlabel("↻" + fmt_reset(five_h_rst))
        parts.append(seg)

    # 7d — date if >24h, clock time if ≤24h
    if seven_d_pct is not None:
        seg = zlabel("7d ") + zmono(f"{int(seven_d_pct)}%%", seven_d_pct)
        if seven_d_rst:
            seg += " " + zlabel("↻" + fmt_reset(seven_d_rst, full=True))
        parts.append(seg)

    # ctx — green <60%, amber 60-80%, coral ≥80%
    ctx_pct_c = c.get("ctx_pct") if c else None
    if ctx_pct_c and ctx_pct_c > 2:
        parts.append(zlabel("ctx ") + zctx(f"{int(ctx_pct_c)}%%", ctx_pct_c))

    # cost (≈ = API-equivalent, not real spend) + model
    tail = ""
    if cost_usd and cost_usd >= 0.01:
        tail = zlabel(f"≈${cost_usd:.2f}") + SPACE
    tail += zlabel(model_name)
    parts.append(tail)

    print("☁ " + DOT.join(parts), end="")

# ── Entry point ───────────────────────────────────────────────────────────────
def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "--zsh"
    if mode == "--update":
        save_cache(collect_jsonl())
    elif mode == "--statusline":
        render_statusline()
    else:
        render_zsh()

if __name__ == "__main__":
    main()
