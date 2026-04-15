"""
Bot patch version — single source of truth.

Bump PATCH and add a line to PATCH_NOTES whenever a meaningful change is deployed.
The dashboard reads this via /api/version.
"""

PATCH       = "v1.6"
PATCH_DATE  = "2026-04-15"
PATCH_NOTES = "BTC_SKIP_RATE configurable via .env (default raised 20→50 $/min)"
