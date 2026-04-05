"""
Claude API advisor for 5-minute BTC trade entry decisions.

Called when basic price/filter checks pass. Analyzes BTC momentum context
and decides whether to enter (fade the move, expecting reversal) or skip
(BTC is trending — don't fight it).

Cost: ~$0.001 per call with Haiku, ~$0.01/hour at typical entry frequency.
Falls back to ENTER (normal behavior) if API key missing or call times out.
"""
from __future__ import annotations

import os
import time

ADVISOR_MODEL   = "claude-haiku-4-5-20251001"
ADVISOR_TIMEOUT = 8.0   # seconds before giving up and defaulting to ENTER

_client = None


def _get_client():
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            return None
        import anthropic
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def advise_entry(
    side: str,                  # "UP" or "DOWN" — the cheap side we want to buy
    entry_price: float,         # price of the cheap side (0.30–0.39)
    cl_pct_change: float,       # Chainlink % move this window from start (+= BTC up)
    btc_rate_per_min: float,    # BTC $/min rate right now
    btc_momentum_decel: float,  # rate_10s / rate_30s: <1=slowing, <0=reversing, >1=accelerating
    cross_window_pct: float,    # Chainlink % move from prev window start to this window start
    cheap_side_velocity: float, # ¢/s of cheap side price in last 20s (<0 = still falling)
    secs_remaining: float,
) -> tuple[bool, str]:
    """
    Returns (should_enter, reason_string).
    On API failure or missing key, defaults to (True, reason) — normal behavior.
    """
    client = _get_client()
    if client is None:
        return True, "no_api_key"

    # Describe momentum state in human terms for the prompt
    btc_dir      = "UP" if cl_pct_change >= 0 else "DOWN"
    decel_desc   = (
        "already reversing direction"  if btc_momentum_decel < 0 else
        "clearly decelerating"         if btc_momentum_decel < 0.5 else
        "slightly decelerating"        if btc_momentum_decel < 0.85 else
        "roughly steady"               if btc_momentum_decel < 1.15 else
        "accelerating"
    )
    cross_same   = (cross_window_pct > 0) == (cl_pct_change > 0)
    cross_desc   = f"SAME direction ({cross_window_pct:+.3f}%)" if cross_same else f"OPPOSITE direction ({cross_window_pct:+.3f}%)"
    still_fall   = cheap_side_velocity < -0.0003

    prompt = f"""\
You are advising a Polymarket 5-minute BTC Up/Down market bot on whether to enter a trade.

PROPOSED TRADE: Buy {side} side at {entry_price:.3f}
This bets that BTC will REVERSE from its current move by window end.
Settlement: winning side pays $1.00, losing side pays $0.00.
Time remaining in window: {secs_remaining:.0f}s

BTC CONTEXT RIGHT NOW:
- This window: BTC moved {btc_dir} by {abs(cl_pct_change):.3f}% from window start
- Current BTC rate: {btc_rate_per_min:+.1f} $/min
- Momentum trend: {decel_desc} (10s/30s rate ratio: {btc_momentum_decel:.2f})
- Previous window: BTC moved in {cross_desc}
- Cheap side price still falling: {"YES — momentum not finished" if still_fall else "NO — stabilizing"}

DECISION: Should the bot enter this trade (bet BTC reverses) or skip?

Reply with exactly one word on the first line: ENTER or SKIP
Second line: one short sentence explaining why (max 15 words)."""

    try:
        t0  = time.time()
        msg = client.messages.create(
            model=ADVISOR_MODEL,
            max_tokens=60,
            messages=[{"role": "user", "content": prompt}],
        )
        elapsed = time.time() - t0
        text    = msg.content[0].text.strip()
        lines   = [l.strip() for l in text.splitlines() if l.strip()]
        decision = lines[0].upper() if lines else "ENTER"
        reason   = lines[1] if len(lines) > 1 else ""
        enter    = decision.startswith("ENTER")
        action   = "ENTER" if enter else "SKIP"
        print(f"[ADVISOR] {action} ({elapsed:.1f}s) — {reason}")
        return enter, reason
    except Exception as exc:
        print(f"[ADVISOR] Error ({exc}) — defaulting to ENTER")
        return True, f"api_error"
