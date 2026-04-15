"""
Bot patch version — single source of truth.

Bump PATCH and add a line to PATCH_NOTES whenever a meaningful change is deployed.
The dashboard reads this via /api/version.
"""

PATCH       = "v1.5"
PATCH_DATE  = "2026-04-15"
PATCH_NOTES = "CROSS_WINDOW_MIN/MAX now configurable via .env (default -0.15/0.02)"
