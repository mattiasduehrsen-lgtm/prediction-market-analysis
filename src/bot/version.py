"""
Bot patch version — single source of truth.

Bump PATCH and add a line to PATCH_NOTES whenever a meaningful change is deployed.
The dashboard reads this via /api/version.
"""

PATCH       = "v1.9"
PATCH_DATE  = "2026-04-15"
PATCH_NOTES = "Entry taker slippage: +1c buffer ensures GTC order crosses spread; cancelled-order fast-cleanup"
