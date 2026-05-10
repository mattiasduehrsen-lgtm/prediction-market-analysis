"""
Bot patch version - single source of truth.

Bump PATCH and add a line to PATCH_NOTES whenever a meaningful change is deployed.
The dashboard reads this via /api/version.
"""

PATCH       = "v1.31"
PATCH_DATE  = "2026-05-10"
PATCH_NOTES = "PAPER-only 4h experiment (Option 1 strategy pivot from STRATEGY_PIVOT_SCOPING.md). ML feature exploration on 700 MR-15m PAPER trades found AUC=0.496 - no learnable signal in current data. Higher model confidence -> WORSE outcomes (textbook overfit). Strategy is structurally noise on these features. Pivot: longer-horizon Polymarket Up/Down markets. 4h has same {asset}-updown-4h-{epoch} slug pattern as 5m/15m - clean drop-in. Added: WINDOW_SECONDS['4h']=14400, SLUG_PREFIXES, per-window MIN_LIQUIDITY (4h=$2k, was $15k), per-window ENTRY_MIN/MAX (4h=[0.28,0.45], was [0.32,0.40]). Per-window soft_exit_secs (4h=3600s) and hard_stop_max_remaining (4h=3600s). cw filter and BTC DOWN filter disabled on 4h to gather fresh data. multi-loop default adds BTC/ETH/SOL 4h. multi-live UNCHANGED (LIVE = SOL 15m only). 6 windows/day per asset = 18 PAPER 4h trades/day expected. Reach n=200 in ~10 days. See OPTION_1_DISCOVERY.md, ML_FEATURE_EXPLORATION.md."
