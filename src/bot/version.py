"""
Bot patch version — single source of truth.

Bump PATCH and add a line to PATCH_NOTES whenever a meaningful change is deployed.
The dashboard reads this via /api/version.
"""

PATCH       = "v1.13"
PATCH_DATE  = "2026-04-16"
PATCH_NOTES = "Record resolution_side and our_side_won in live trades — live engine now back-fills which side won at window close, matching paper engine. Fixes missing data for 'right direction, bad stop' analysis."
