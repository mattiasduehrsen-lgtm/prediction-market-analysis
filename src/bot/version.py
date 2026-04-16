"""
Bot patch version — single source of truth.

Bump PATCH and add a line to PATCH_NOTES whenever a meaningful change is deployed.
The dashboard reads this via /api/version.
"""

PATCH       = "v1.14"
PATCH_DATE  = "2026-04-16"
PATCH_NOTES = "Fix FOK exit price fallback: use actual market price at exit time instead of AGGRESSIVE_EXIT_PRICE (0.01) when Polymarket doesn't return average_price — fixes dashboard entry/exit price inaccuracy and PnL understatement."
