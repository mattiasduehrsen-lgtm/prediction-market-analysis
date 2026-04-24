"""
Bot patch version — single source of truth.

Bump PATCH and add a line to PATCH_NOTES whenever a meaningful change is deployed.
The dashboard reads this via /api/version.
"""

PATCH       = "v1.22"
PATCH_DATE  = "2026-04-24"
PATCH_NOTES = "Cowork ETH deep dive (214 trades, 2026-04-24). Core insight: the strategy is BTC→ETH momentum continuation, not symmetric mean-reversion — two non-contiguous cross-window zones (one neg, one pos). Changes: (1) ETH cross-window filter [-0.10,-0.02]∪[+0.03,+0.10] replaces global filter for ETH (Scenario C: WR 53%→72%, +$23→+$306, Welch p=0.012). (2) ETH dead-zone skip [0.38, 0.39): 42 trades, 38% WR, -$68. (3) ETH spread cap 0.03 eliminates 25% WR wide-book tail. BTC/SOL filters unchanged. 30-day projection: +$612 vs +$47 baseline."
