"""
Bot patch version — single source of truth.

Bump PATCH and add a line to PATCH_NOTES whenever a meaningful change is deployed.
The dashboard reads this via /api/version.
"""

PATCH       = "v1.12"
PATCH_DATE  = "2026-04-16"
PATCH_NOTES = "Cowork pre-live review: per-strategy paper summary JSON now filters by asset/window/strategy (was writing identical aggregate to every summary_*.json). Entry filters (min DOWN>=0.35, BTC-5m disabled) already in place. Live sizing cut to $3/trade and daily loss cap tightened to $25 via .env."
