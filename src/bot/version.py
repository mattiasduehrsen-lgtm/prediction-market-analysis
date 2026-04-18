"""
Bot patch version — single source of truth.

Bump PATCH and add a line to PATCH_NOTES whenever a meaningful change is deployed.
The dashboard reads this via /api/version.
"""

PATCH       = "v1.17"
PATCH_DATE  = "2026-04-18"
PATCH_NOTES = "Fix CB not recording FOK exits: place_exit() now returns ClosedLiveTrade5m when settling synchronously; main.py calls cb.record_trade() on return value. Also fixes wallet-empty/min-shares/market-resolved inline settles. Stop-loss exits now correctly count against the daily loss limit."
