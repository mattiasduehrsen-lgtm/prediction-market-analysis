"""
Bot patch version - single source of truth.

Bump PATCH and add a line to PATCH_NOTES whenever a meaningful change is deployed.
The dashboard reads this via /api/version.
"""

PATCH       = "v1.29"
PATCH_DATE  = "2026-05-07"
PATCH_NOTES = "ETH disabled on LIVE. Retroactive application of v1.28 corrections to n=693 historical MR-15m PAPER trades reveals the '+$0.12/trade PAPER EV' baseline was entirely the over-statement artifact (TP wins recorded ~2.4 cents above the actual TP fill, ~$2/winning trade overstatement). Corrected per-segment EV: ETH UP -$0.43 (n=145), ETH DOWN -$0.49 (n=123), SOL UP +$0.53 (n=74, only +EV segment), BTC UP -$1.05 (already off). ETH t-stat=-0.71 (insignificant but firmly negative). LIVE now runs SOL only. ETH stays on PAPER for continued data collection. LIVE remains paused. See V1_28_RETROACTIVE_FINDINGS.md."
