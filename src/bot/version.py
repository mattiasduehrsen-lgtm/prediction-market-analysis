"""
Bot patch version — single source of truth.

Bump PATCH and add a line to PATCH_NOTES whenever a meaningful change is deployed.
The dashboard reads this via /api/version.
"""

PATCH       = "v1.11"
PATCH_DATE  = "2026-04-16"
PATCH_NOTES = "Fix: size orders by actual wallet balance, not API size_matched (prevents orphaned positions); settle on orderbook-gone instead of infinite retry"
