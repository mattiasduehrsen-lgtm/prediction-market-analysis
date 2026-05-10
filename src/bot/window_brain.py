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

import json
import os
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

BRAIN_MODEL       = os.environ.get("BRAIN_MODEL",       "claude-haiku-4-5-20251001")
BRAIN_TIMEOUT     = float(os.environ.get("BRAIN_TIMEOUT", "6.0"))
BRAIN_HISTORY_LEN = int(os.environ.get("BRAIN_HISTORY_LEN", "10"))
BRAIN_VETO        = os.environ.get("BRAIN_VETO", "false").lower() == "true"
BRAIN_ENABLED     = os.environ.get("BRAIN_ENABLED", "true").lower() != "false"

# ── System prompt (cached by Anthropic — charged once per 5-min TTL) ─────────

_SYSTEM = """\
You are a regime-detection assistant for a Polymarket 15-minute mean-reversion \
trading bot. The bot buys the "cheap side" token (~35–40¢) in BTC/ETH/SOL \
Up/Down prediction markets, betting the price will revert to ~50¢ before the \
15-minute window expires. It profits in ranging/choppy conditions and loses \
in sustained trending conditions.

Your only job is to assess whether mean-reversion is likely to work well right \
now for this specific asset, based on recent trade history. You are NOT trying \
to predict which direction the asset moves.

Key failure modes:
- Trending regime: consecutive losses where "cheap side" kept moving further away
- High-vol regime: stop-losses triggered at median 45% through window, then price \
  reverting — we exited too early
- Illiquid regime: very wide spreads, poor fills, unusually thin books

Key success signals:
- Ranging regime: recent wins via take-profit, prices oscillating around 0.50
- Consistent WR ≥ 55% over last 8+ trades = edge is working
- Edge values consistently positive (our side underpriced by Binance)

Output ONLY a valid JSON object — no markdown, no explanation outside the JSON.
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

        prompt = (
            f"Asset: {self.asset} | Window: {self.window}\n\n"
            f"Recent resolved trades (oldest → newest):\n{history_block}\n\n"
            f"Summary: {summary}\n\n"
            f"Current entry candidate:\n"
            f"  Side:          {side}\n"
            f"  Entry price:   {entry_price:.3f}\n"
            f"  Edge (Binance implied P − price): {edge:+.4f}\n"
            f"  Realized vol:  {rv_std:.4f} (per 2s bar; >0.0029 = high-vol)\n"
            f"  Cross-window:  {cross_window_pct:+.3f}% (prior window BTC move)\n"
            f"  Secs remaining: {secs_remaining:.0f}s\n\n"
            f"Assess the mean-reversion regime for {self.asset} right now.\n"
            f"Reply with ONLY this JSON:\n"
            f'{{\n'
            f'  "regime": "ranging|trending|volatile|unclear",\n'
            f'  "mr_edge": "strong|normal|degraded",\n'
            f'  "edge_modifier": <float, -0.05 to +0.05>,\n'
            f'  "reasoning": "<one sentence, max 20 words>"\n'
            f'}}\n\n'
            f'edge_modifier guide:\n'
            f'  +0.02 to +0.05: degraded (trending regime, loss cluster) → stricter gate\n'
            f'  0.00:           normal / unclear → no change\n'
            f'  -0.01 to -0.02: strong (ranging, consistent wins, edge positive) → slightly looser'
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
