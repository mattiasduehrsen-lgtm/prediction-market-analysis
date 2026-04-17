"""
Bot patch version — single source of truth.

Bump PATCH and add a line to PATCH_NOTES whenever a meaningful change is deployed.
The dashboard reads this via /api/version.
"""

PATCH       = "v1.15"
PATCH_DATE  = "2026-04-17"
PATCH_NOTES = "Remove signal mirroring: LIVE now evaluates should_enter() independently instead of copying PAPER entries. Eliminates delayed/stale entries caused by mirror lag."
