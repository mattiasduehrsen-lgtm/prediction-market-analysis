"""
Bot patch version — single source of truth.

Bump PATCH and add a line to PATCH_NOTES whenever a meaningful change is deployed.
The dashboard reads this via /api/version.
"""

PATCH       = "v1.21"
PATCH_DATE  = "2026-04-22"
PATCH_NOTES = "Cowork 582-trade analysis (2026-04-22) — Scenario B filters. (1) Hard-disable BTC DOWN: t-test p=0.028, 95% CI entirely negative, -$327 on 161 trades, loses even in ranging weeks. (2) BTC-15m floor raised 0.35→0.38: dead zone 22.4% WR -$199 on 49 trades. (3) SOL-15m floor added at 0.33 (0.28-0.32 band too thin). ETH floor unchanged at 0.35 (ETH 0.35-0.38 is best band at 63.6% WR). Expected delta vs baseline: +$419 on 582-trade backtest, 312 trades at 52.6% WR."
