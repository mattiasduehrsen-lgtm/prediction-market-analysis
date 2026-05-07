"""
Bot patch version — single source of truth.

Bump PATCH and add a line to PATCH_NOTES whenever a meaningful change is deployed.
The dashboard reads this via /api/version.
"""

PATCH       = "v1.28"
PATCH_DATE  = "2026-05-06"
PATCH_NOTES = "Execution-drag root cause identified: most of the measured LIVE-vs-PAPER drag was PAPER over-reporting wins, NOT LIVE underperforming. Three fixes: (1) PAPER books TP exits at exactly pos.take_profit instead of cur_up — was over-stating winning-trade pnl by ~$0.20-$0.30/trade because cur_up is by definition >= TP when the condition fires. (2) PAPER models the ~4.5% wallet-fill discount LIVE actually experiences (Polymarket's size_matched over-reports vs wallet) — was over-stating share count by ~$0.10/trade. (3) LIVE rewrites exit_reason to 'market_resolved' on wallet-empty path — previously preserved hard_stop_floor/soft_exit_stalled, distorting exit-reason analysis. Implication: PAPER MR-15m EV +$0.12 retroactively becomes ~-$0.20, meaning the strategy was never +EV at $5 LIVE size. Forward PAPER and LIVE should converge. LIVE remains paused; resume only after re-measuring matched-pairs drag is below ~$0.10/trade."
