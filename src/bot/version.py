"""
Bot patch version — single source of truth.

Bump PATCH and add a line to PATCH_NOTES whenever a meaningful change is deployed.
The dashboard reads this via /api/version.
"""

PATCH       = "v1.19"
PATCH_DATE  = "2026-04-19"
PATCH_NOTES = "Cowork 2026-04-19 deploy: (1) Binance fair-value edge gate on 15m MR entries — skip when GBM implied P(our side) < entry_price (EDGE_GATE_MIN=0.0); backtest lifts avg PnL +$0.11 → +$0.42 per $5 trade, Sharpe 0.55 → 1.74 on 448 paper trades. (2) Soft daily loss stop: block new LIVE entries when today's realised PnL ≤ -$LIVE_DAILY_SOFT_STOP_USD (default $10) without tripping the hard $50 circuit breaker. Both gates honour env overrides."
