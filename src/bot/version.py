"""
Bot patch version — single source of truth.

Bump PATCH and add a line to PATCH_NOTES whenever a meaningful change is deployed.
The dashboard reads this via /api/version.
"""

PATCH       = "v1.26c"
PATCH_DATE  = "2026-05-03"
PATCH_NOTES = "HOTFIX: Corrected v1.26a cw filter bands. v1.26a mistakenly used +0.03 (copied from old ETH-only v1.22 filter) and -0.10 instead of Cowork's validated spec: CW_BAND_POS=(+0.02,+0.10), CW_BAND_NEG=(-0.15,-0.02). This blocked all windows where cw in (+0.02,+0.03) — BTC was reading cw=+0.022% every window → zero PAPER trades for 24h. Fix: signal_5m.py global filter now uses -0.15/+0.02 as the band edges. Also includes v1.26b crash regime filter (BTC_CRASH_PCT_THRESHOLD=0.10) from the prior commit."
