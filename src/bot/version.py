"""
Bot patch version - single source of truth.

Bump PATCH and add a line to PATCH_NOTES whenever a meaningful change is deployed.
The dashboard reads this via /api/version.
"""

PATCH       = "v1.34"
PATCH_DATE  = "2026-05-12"
PATCH_NOTES = "ETH-15m re-enabled on LIVE conditional on recent 8-trade WR >= 5/8 (62.5%). Forward-EV replay analysis on 693 PAPER trades showed: brain regime calls are anti-predictive for BTC (strong -$2.97 vs degraded -$0.97) and SOL (small n), but work for ETH (strong +$0.52 vs degraded -$0.95). The brain essentially echoes recent-WR; using recent-WR directly is cheaper, deterministic, and has no API dependency. v1.34 implements _recent_trade_wr() helper that reads PAPER trades.csv and counts wins over last N closed trades. ETH-15m LIVE entries require >=5/8 recent wins; otherwise skipped with [WR-FILTER] log. ETH PAPER continues to enter unconditionally (data collection). BTC stays off LIVE. SOL stays unconditional (no useful signal). Brain narrowed to ETH-15m only (observation/research; BTC/SOL/4h brain calls eliminated — saves cost, removes noise). LIVE remains paused via paused.live.flag; user must explicitly unpause for v1.34 to actually trade. Expected production: ETH LIVE 1-2 entries/week when WR filter passes; EV ~+$0.50/trade (95% CI wide). First defensible +EV LIVE configuration since project inception."
