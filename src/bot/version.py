"""
Bot patch version — single source of truth.

Bump PATCH and add a line to PATCH_NOTES whenever a meaningful change is deployed.
The dashboard reads this via /api/version.
"""

PATCH       = "v1.24"
PATCH_DATE  = "2026-04-25"
PATCH_NOTES = "RS rollout to LIVE. Both ETH DOWN RS and SOL DOWN RS cleared all rollout gates (last-50: ETH 75% WR +$16.27, SOL 79% WR +$46.00; gate = WR>=70% AND PnL>0). Added ETH:15m:resolution_scalp and SOL:15m:resolution_scalp to multi-live default argv. v1.23 is_live filter (already deployed) automatically blocks BTC RS (structural loser) and ETH/SOL UP RS (below breakeven) — only DOWN-side RS fires on LIVE. No changes to signal logic or MR."
