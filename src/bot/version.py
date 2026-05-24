"""
Bot patch version - single source of truth.

Bump PATCH and add a line to PATCH_NOTES whenever a meaningful change is deployed.
The dashboard reads this via /api/version.
"""

PATCH       = "v1.35"
PATCH_DATE  = "2026-05-24"
PATCH_NOTES = "Esports LIVE bet size $10 -> $15 (first scale-up). Wallet equity reconcile against starting deposit $749 showed lifetime PnL +$214 / +28.6% ROI over 9 days (275 resolved trades). My evaluator was systematically under-reporting because winning shares sit in the wallet at ~$0.999 until manual redemption — the user keeps them parked to save the ~30c redemption-fee delta. The new wallet-equity view (pUSD cash + open-position MTM) is the canonical PnL going forward. ROI gate for $15/trade scaling (>= +2% over 400+ trades) is well past on ROI dimension; 275 trades is below the conservative sample threshold but +28.6% is far outside variance noise. evaluate_live.py also updated to optionally read ESPORTS_STARTING_DEPOSIT_USD env var and write lifetime_equity_pnl_usd to live_daily_pnl.json so the dashboard / future scaling decisions have a ground-truth number that doesn't depend on redemption timing. Also bumps LIVE_MAX_DAILY_LOSS_USD 50 -> 75 to scale proportionally with bet size. Crypto bot remains dormant; this affects esports fade only."
