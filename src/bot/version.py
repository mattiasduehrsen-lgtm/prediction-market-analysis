"""
Bot patch version — single source of truth.

Bump PATCH and add a line to PATCH_NOTES whenever a meaningful change is deployed.
The dashboard reads this via /api/version.
"""

PATCH       = "v1.20"
PATCH_DATE  = "2026-04-20"
PATCH_NOTES = "Resolution-edge scalp (Cowork 2026-04-19 Strategy #4, Phase 2). New strategy='resolution_scalp' in run_5m_loop: enters last 10-90s of 15m window when GBM implied_p > 0.75 AND Polymarket token is 5+ cents below that probability. Holds to force_exit_time (~5s before window end). No TP/SL. Synthetic backtest: 79% WR, +$0.72/trade @ $5. PAPER-only (BTC/ETH/SOL) until 100 OOS trades confirm WR >= 70%. Also: Phase 1 (edge gate) at 90 trades shows 40% WR — trending market regime, not a code issue."
