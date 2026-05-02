"""
Bot patch version — single source of truth.

Bump PATCH and add a line to PATCH_NOTES whenever a meaningful change is deployed.
The dashboard reads this via /api/version.
"""

PATCH       = "v1.26b"
PATCH_DATE  = "2026-05-02"
PATCH_NOTES = "Phase 2 of Cowork May 1 deep-dive v1.26 implementation: crash regime filter. Adds circuit breaker for extreme-volatility windows where systematic risk spikes. Cowork analysis of April 27 & May 1 crashes found both RS and underlying MR edge vanish when BTC moves >10% from window start (cascading liquidations, thin markets). Filter: skip entries when |btc_pct_change_at_entry| > 0.10 (10% move threshold). New const BTC_CRASH_PCT_THRESHOLD (env configurable, default 0.10) in market_5m.py. Integrated at main.py lines ~879-887 after GBM collapse gate, before BTC DOWN regime filter. Projected impact from Cowork backtest on 1633-trade history: +$200 PnL (loss avoidance, no WR change). Expected to prevent ~8-15 trades/month during volatile windows. Files changed: main.py (imports + filter logic), src/bot/market_5m.py (new constant), src/bot/version.py, PATCH_HISTORY.md, STRATEGY_HISTORY.md."
