"""
Bot patch version — single source of truth.

Bump PATCH and add a line to PATCH_NOTES whenever a meaningful change is deployed.
The dashboard reads this via /api/version.
"""

PATCH       = "v1.23"
PATCH_DATE  = "2026-04-25"
PATCH_NOTES = "Cowork comprehensive analysis (785 trades, 2026-04-25). Resolution-scalp UP/DOWN asymmetry: combined ETH+SOL DOWN RS = 82% WR, +$100 on 55 trades; combined UP-side + BTC RS = 65% WR, -$122 on 112 trades (z=2.43, p=0.015). v1.23 adds LIVE-only filter to should_enter_resolution_scalp via new is_live arg: BTC RS disabled entirely (avg_win $3 vs avg_loss $9, needs 74-80% WR, achieves 67% — structural); UP-side RS disabled for ETH/SOL (below breakeven WR). PAPER keeps running all 6 sub-strategies for ongoing monitoring (Cowork explicit recommendation). LIVE rollout deferred ~2 weeks; multi-live default still MR-only, signal filter dormant until ETH DOWN RS is added to multi-live argv. No MR changes; v1.22 validated by Cowork backtest. Regime skip rejected as net-negative on top of v1.22."
