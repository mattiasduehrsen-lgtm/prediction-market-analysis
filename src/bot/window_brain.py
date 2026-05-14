"""
Cross-window regime intelligence using Claude API.

Maintains a rolling history of the last N resolved trades per asset and
calls Claude once per entry candidate to assess whether the mean-reversion
edge is currently strong, normal, or degraded.

Key design difference from the old claude_advisor.py:
  - NOT a direction predictor — never tries to predict which side wins.
  - Asks one question only: "Is mean-reversion working for this asset right now?"
  - Returns a continuous edge_modifier [-0.05, +0.05] added to EDGE_GATE_MIN,
    not a binary ENTER/SKIP that blocked 96% of windows.
  - Persistent: reads recent closed trades from CSV on each window transition
    so context carries across restarts.
  - Prompt caching on system prompt → ~$0.002/day with Haiku.

Fails open (neutral, modifier=0.0) on any API error, missing key, or timeout.

Configuration (via .env):
  ANTHROPIC_API_KEY          — required; if absent, brain is silently disabled
  BRAIN_ENABLED              — "false" to disable without removing key (default: "true")
  BRAIN_MODEL                — override model (default: claude-haiku-4-5-20251001)
  BRAIN_VETO                 — "true" to let brain hard-block entries (default: "false")
  BRAIN_TIMEOUT              — seconds before fallback to neutral (default: 6.0)
  BRAIN_HISTORY_LEN          — resolved trades to include in context (default: 10)
"""
from __future__ import annotations

import csv as _csv
import json
import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

# v1.34: brain decisions CSV — written every advise() call for offline analysis.
# Shared lock because multiple threads (per asset) write to the same file.
_BRAIN_LOG_PATH = Path(__file__).resolve().parents[2] / "output/5m_trading/brain_decisions.csv"
_BRAIN_LOG_LOCK = threading.Lock()
_BRAIN_LOG_COLUMNS = [
    "timestamp", "asset", "window", "side", "entry_price",
    "cross_window_pct", "secs_remaining",
    "regime", "mr_edge", "modifier", "reasoning",
    "history_n", "history_wins", "elapsed_ms",
    "cache_read_tokens", "cache_creation_tokens", "model",
]


def _append_brain_log(row: dict) -> None:
    """Append a brain advice row to brain_decisions.csv. Best-effort."""
    try:
        _BRAIN_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _BRAIN_LOG_LOCK:
            new_file = not _BRAIN_LOG_PATH.exists() or _BRAIN_LOG_PATH.stat().st_size == 0
            with _BRAIN_LOG_PATH.open("a", encoding="utf-8", newline="") as fh:
                w = _csv.DictWriter(fh, fieldnames=_BRAIN_LOG_COLUMNS)
                if new_file:
                    w.writeheader()
                # Truncate unknown keys; missing keys are blank
                w.writerow({k: row.get(k, "") for k in _BRAIN_LOG_COLUMNS})
    except Exception as exc:
        # Never let brain logging fail an advise() call
        print(f"  [BRAIN] log write error: {exc}")

BRAIN_MODEL       = os.environ.get("BRAIN_MODEL",       "claude-haiku-4-5-20251001")
BRAIN_TIMEOUT     = float(os.environ.get("BRAIN_TIMEOUT", "6.0"))
BRAIN_HISTORY_LEN = int(os.environ.get("BRAIN_HISTORY_LEN", "10"))
BRAIN_VETO        = os.environ.get("BRAIN_VETO", "false").lower() == "true"
BRAIN_ENABLED     = os.environ.get("BRAIN_ENABLED", "true").lower() != "false"

# ── System prompt v2 (v1.33 rewrite — counter conservatism bias) ───────────
# Rewrite #1 of allowed 2 (per BRAIN_RESEARCH_FINDINGS.md). v1 prompt produced
# 95% "degraded" / 100% non-negative modifier across 48 calls — textbook
# conservatism-bias failure mode. This version:
#   - Establishes modifier=0 as the explicit default, not a "neither" answer.
#   - Anchors on baseline EV ≈ -$1/trade so loss clusters are not over-weighted.
#   - Lists NORMAL reasoning examples (v1 had none — only success and failure).
#   - Enumerates the specific anti-patterns v1 produced ("Skip", "zero edge",
#     "insufficient conviction") and forbids them by name.
#   - Tells the model edge=0.0 means "not computed", not "no conviction".
#   - Treats 15m and 4h windows as equally valid (v1 framed 15m as canonical).

_SYSTEM = """\
You are a REGIME CLASSIFIER for a Polymarket mean-reversion trading bot. The bot
trades 15-minute AND 4-hour Up/Down prediction markets on BTC, ETH, SOL. Each
window resolves binary: winner pays $1.00, loser pays $0.00. The bot buys the
cheap side (entry typically 0.28–0.45), then exits at take-profit (~0.60),
stop-loss (cheap side falls to ~0.10), or window close.

## YOUR JOB

You output a SMALL adjustment to the bot's entry threshold based on whether
mean-reversion is currently working as a regime. You are NOT predicting
direction. You are NOT deciding skip/enter — that decision belongs to the bot.
You ARE the regime sanity check on top of the bot's existing systematic filter.

## DEFAULT IS NEUTRAL — read this carefully

modifier=0.00 is the default. Most calls should return modifier=0.00.

Only push the modifier away from 0 when the evidence is SPECIFIC, RECENT, and
ACTIONABLE. If you find yourself reasoning like "let's be cautious" or "skip
this trade" or "insufficient conviction" — STOP. That is discretionary-trader
thinking. You are a systematic classifier. Caution is the bot's job, not yours.

LLMs in trading consistently exhibit conservatism bias — they over-rate risk
and pull entries away. Counter this bias actively: your prior should be that
this trade is NORMAL unless evidence is clearly otherwise.

## BASELINE — THE BOT LOSES MONEY ON AVERAGE

This bot's historical EV is approximately -$1/trade. Loss clusters, soft-exit
dominance, and negative cumulative PnL over 10 trades are NORMAL background
noise — not regime alarms. Most 10-trade samples will show 3–6 wins and
cumulative PnL between -$30 and +$10. That is NORMAL. Do not flag it.

Only flag "degraded" if the regime is clearly WORSE than this noisy baseline:
e.g. 0–1 wins in 10, OR 4+ consecutive hard_stop_floor losses with no
recoveries, OR cheap side hitting new lows on every trade for 5+ in a row.

Only flag "strong" if the regime is clearly BETTER: e.g. 7+/10 wins, mostly
via take_profit, with no streaks longer than 1 loss.

## REASONING EXAMPLES — all three categories

STRONG (modifier = -0.02 to -0.01):
- "8/10 wins, all take_profit, no >1-loss streaks. Strong ranging regime."
- "Last 10: 7 wins, mostly TP within 200s. WR 70%, well above baseline."

NORMAL (modifier = 0.00) — THIS SHOULD BE THE COMMON ANSWER:
- "5/10 wins with mixed exits. Typical noisy conditions."
- "3/10 wins is baseline. Soft-exit cluster but a recent TP shows reversion works."
- "Cumulative -$15 in last 10 is within normal range. No specific regime signal."
- "No history yet. Insufficient data — default neutral."
- "Mixed exit reasons, no clear streak shape. Standard noise."

DEGRADED (modifier = +0.01 to +0.05):
- "0/8 wins, all hard_stop_floor at -75%+. Cheap side collapsing fully."
- "Last 6 are losses, cheap side at new lows each entry. Sustained trend."
- "5 hard_stop_floor in 7 trades — fast-moving regime, MR thesis broken."

## ANTI-PATTERNS — DO NOT PRODUCE

These reasoning patterns are FORBIDDEN. They are conservatism bias, not
regime classification:
- "Skip this trade" / "Gate stricter" / "Insufficient conviction" — you are
  not deciding skip. Modifier ≠ skip.
- "Edge zero / no edge signal" — edge=0.0 means "this metric is NOT computed
  for mean-reversion". IGNORE the edge field entirely. It is a placeholder.
- "Cumulative pnl negative" alone — negative PnL is BASELINE for this bot.
  Only matters if it's catastrophic (-$50+ in 10 trades).
- "Soft-exit cluster" alone — soft_exit_stalled is a NORMAL exit reason,
  not a regime warning. Common in many regimes including profitable ones.
- "Mixed outcomes / unclear pattern" → modifier=0.00, not modifier=+0.02.
  Mixed = normal.
- "4h window too long" / "window length unusual" — 4h is a SUPPORTED window,
  equally valid as 15m. Window length is informational only.

If you would have used any of these patterns, return modifier=0.00 with
reasoning "normal — no specific regime signal".

## WHAT YOU SEE / DON'T SEE

YOU SEE: last N closed trades (side, entry price, exit reason, pnl, won),
the current candidate (price, side, cross-window %, secs remaining), and
the target window (15m or 4h — both valid).

YOU DO NOT SEE: order book, intra-window price path, BTC chart, news headlines,
or any meaningful "edge" or "realized vol" number (those fields are 0.0 = not
computed for MR — IGNORE).

## OUTPUT

Reply with EXACTLY this JSON object. No markdown. No prose outside the JSON.
"""


@dataclass
class BrainAdvice:
    """Result from WindowBrain.advise()."""
    regime: str          # "ranging" | "trending" | "volatile" | "unclear"
    mr_edge: str         # "strong" | "normal" | "degraded"
    edge_modifier: float # added to EDGE_GATE_MIN; positive = stricter, negative = looser
    reasoning: str       # one-sentence explanation

    @property
    def is_neutral(self) -> bool:
        return self.edge_modifier == 0.0


# Singleton for disabled / error states
NEUTRAL = BrainAdvice(regime="unclear", mr_edge="normal", edge_modifier=0.0, reasoning="")


class WindowBrain:
    """
    Per-asset cross-window intelligence.

    Usage in the bot loop:
        brain = WindowBrain("BTC")

        # At window transition:
        brain.sync_from_csv(trades_csv_path, asset="BTC", last_n=10)

        # After edge gate passes:
        advice = brain.advise(entry_price, side, edge, rv_std, cross_window_pct, secs_remaining)
        effective_gate = EDGE_GATE_MIN + advice.edge_modifier
        if edge < effective_gate:
            continue   # brain raised the bar
    """

    def __init__(self, asset: str, window: str = "15m") -> None:
        self.asset = asset
        self.window = window
        self._history: deque = deque(maxlen=BRAIN_HISTORY_LEN)
        self._client = None
        self._last_advice = NEUTRAL
        self._call_count  = 0
        self._total_ms    = 0.0

    # ── Client init ───────────────────────────────────────────────────────────

    def _get_client(self):
        if self._client is None:
            api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
            if not api_key:
                return None
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=api_key)
            except Exception:
                return None
        return self._client

    # ── History sync ──────────────────────────────────────────────────────────

    def sync_from_csv(self, csv_path: str | Path, asset: str | None = None,
                      window: str | None = None) -> None:
        """
        Load the last BRAIN_HISTORY_LEN resolved trades from trades.csv.
        Filters to this asset and window (defaults from self).
        asset:  override asset filter (defaults to self.asset).
        window: override window filter (defaults to self.window).
        """
        target_asset  = (asset or self.asset).upper()
        target_window = (window or self.window)
        path = Path(csv_path)
        if not path.exists():
            return
        try:
            import csv as _csv
            with path.open(encoding="utf-8", newline="") as fh:
                reader = _csv.DictReader(fh)
                rows = [r for r in reader if r.get("asset", "").upper() == target_asset
                        and r.get("window", "") == target_window
                        and r.get("exit_reason", "") not in ("", "open")]
            # Keep last N resolved trades
            rows = rows[-BRAIN_HISTORY_LEN:]
            self._history.clear()
            for r in rows:
                self._history.append({
                    "side":        r.get("side", "?"),
                    "entry_price": _safe_float(r.get("entry_price")),
                    "exit_reason": r.get("exit_reason", "?"),
                    "pnl_usd":     _safe_float(r.get("pnl_usd")),
                    "won":         r.get("our_side_won", "").lower() in ("true", "1"),
                    "edge":        _safe_float(r.get("edge")),      # may be 0.0 in older rows
                })
        except Exception as exc:
            print(f"  [BRAIN] sync_from_csv error: {exc}")

    # ── Core advice call ──────────────────────────────────────────────────────

    def advise(
        self,
        entry_price: float,
        side: str,
        edge: float,
        rv_std: float,
        cross_window_pct: float,
        secs_remaining: float,
    ) -> BrainAdvice:
        """
        Call once per entry candidate (after all hard gates pass).
        Returns a BrainAdvice with edge_modifier in [-0.05, +0.05].
        Falls back to NEUTRAL on any error.
        """
        if not BRAIN_ENABLED:
            return NEUTRAL
        client = self._get_client()
        if client is None:
            return NEUTRAL

        # ── Build context ──────────────────────────────────────────────────
        history_lines = []
        for i, t in enumerate(self._history, 1):
            outcome = "WIN " if t["won"] else "LOSS"
            edge_str = f" edge={t['edge']:+.3f}" if t["edge"] != 0.0 else ""
            history_lines.append(
                f"  [{i:2d}] {t['side']:4s} @{t['entry_price']:.3f}{edge_str} → "
                f"{outcome} ({t['exit_reason']:20s}) pnl=${t['pnl_usd']:+.2f}"
            )

        n = len(self._history)
        if n:
            wins = sum(1 for t in self._history if t["won"])
            recent_wr  = wins / n * 100
            recent_pnl = sum(t["pnl_usd"] for t in self._history)
            # Streak detection: last 3 trades all same outcome
            last3 = list(self._history)[-3:]
            streak = "none"
            if len(last3) == 3:
                if all(t["won"] for t in last3):
                    streak = "3 wins"
                elif not any(t["won"] for t in last3):
                    streak = "3 losses"
            summary = (
                f"{wins}/{n} wins ({recent_wr:.0f}% WR) | "
                f"${recent_pnl:+.2f} cumulative | streak: {streak}"
            )
        else:
            summary = "no history yet"

        history_block = "\n".join(history_lines) if history_lines else "  (none)"

        # v1.33: cleaned user prompt — `edge` and `rv_std` are not shown because
        # they are 0.0 for MR (not computed) and v1.32 logs showed the model
        # misread them as "no conviction". Cross-window is shown but not framed
        # as bearish/bullish — model decides what to do with it.
        prompt = (
            f"Asset: {self.asset} | Window: {self.window} | Strategy: mean_reversion\n\n"
            f"Recent resolved trades (oldest → newest):\n{history_block}\n\n"
            f"Summary: {summary}\n\n"
            f"Current entry candidate:\n"
            f"  Side:           {side}\n"
            f"  Entry price:    {entry_price:.3f}\n"
            f"  Cross-window:   {cross_window_pct:+.3f}% (prior window asset move)\n"
            f"  Secs remaining: {secs_remaining:.0f}s\n\n"
            f"Classify the regime. REMEMBER: default is modifier=0.00 (NORMAL).\n"
            f"Only deviate from 0 if evidence is SPECIFIC and CLEAR (per system prompt).\n\n"
            f"Reply with ONLY this JSON:\n"
            f'{{\n'
            f'  "regime":        "ranging" | "trending" | "volatile" | "unclear",\n'
            f'  "mr_edge":       "strong" | "normal" | "degraded",\n'
            f'  "edge_modifier": <float in [-0.05, +0.05]; default 0.00>,\n'
            f'  "reasoning":     "<one sentence, max 20 words, no forbidden patterns>"\n'
            f'}}'
        )

        try:
            import anthropic as _anthro
            t0 = time.time()
            resp = self._get_client().messages.create(
                model=BRAIN_MODEL,
                max_tokens=150,
                timeout=BRAIN_TIMEOUT,
                system=[{
                    "type": "text",
                    "text": _SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": prompt}],
            )
            elapsed_ms = int((time.time() - t0) * 1000)
            self._call_count += 1
            self._total_ms   += elapsed_ms

            raw = resp.content[0].text.strip()
            # Strip markdown code fence if model wraps the JSON
            if raw.startswith("```"):
                raw = raw.split("```")[1].lstrip("json").strip()

            data = json.loads(raw)
            modifier = float(data.get("edge_modifier", 0.0))
            modifier = max(-0.05, min(0.05, modifier))   # hard clamp

            advice = BrainAdvice(
                regime        = str(data.get("regime",   "unclear")),
                mr_edge       = str(data.get("mr_edge",  "normal")),
                edge_modifier = modifier,
                reasoning     = str(data.get("reasoning", ""))[:120],
            )

            cache_stats = ""
            usage = getattr(resp, "usage", None)
            if usage:
                cr = getattr(usage, "cache_read_input_tokens", 0)
                cw = getattr(usage, "cache_creation_input_tokens", 0)
                if cr or cw:
                    cache_stats = f" | cache r={cr} w={cw}"

            print(
                f"  [BRAIN] {self.asset} regime={advice.regime} "
                f"mr_edge={advice.mr_edge} modifier={modifier:+.3f} "
                f"({elapsed_ms}ms{cache_stats}) — {advice.reasoning}"
            )
            self._last_advice = advice

            # v1.34: persist to brain_decisions.csv for offline analysis
            _append_brain_log({
                "timestamp":              time.time(),
                "asset":                  self.asset,
                "window":                 self.window,
                "side":                   side,
                "entry_price":            entry_price,
                "cross_window_pct":       cross_window_pct,
                "secs_remaining":         round(secs_remaining, 1),
                "regime":                 advice.regime,
                "mr_edge":                advice.mr_edge,
                "modifier":               advice.edge_modifier,
                "reasoning":              advice.reasoning,
                "history_n":              len(self._history),
                "history_wins":           sum(1 for t in self._history if t["won"]),
                "elapsed_ms":             elapsed_ms,
                "cache_read_tokens":      getattr(usage, "cache_read_input_tokens", 0) if usage else 0,
                "cache_creation_tokens":  getattr(usage, "cache_creation_input_tokens", 0) if usage else 0,
                "model":                  BRAIN_MODEL,
            })
            return advice

        except Exception as exc:
            print(f"  [BRAIN] {self.asset} error ({exc}) — neutral")
            return NEUTRAL

    # ── Stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> str:
        avg_ms = int(self._total_ms / self._call_count) if self._call_count else 0
        return (
            f"WindowBrain({self.asset}): {self._call_count} calls, "
            f"{avg_ms}ms avg, last={self._last_advice.regime}/{self._last_advice.mr_edge}"
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0
