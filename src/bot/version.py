"""
Bot patch version — single source of truth.

Bump PATCH and add a line to PATCH_NOTES whenever a meaningful change is deployed.
The dashboard reads this via /api/version.
"""

PATCH       = "v1.27"
PATCH_DATE  = "2026-05-06"
PATCH_NOTES = "BTC fully disabled on LIVE (BTC DOWN was already off v1.21; BTC UP now off too). Cowork May 5 Opus reanalysis: LIVE BTC UP n=13, WR=23%, EV=-$2.80, total=-$36.38. Matched-pairs LIVE-vs-PAPER execution drag: BTC -$0.36/trade (t=-3.76), ETH -$0.55/trade (t=-2.52). Half the LIVE damage is execution drag, not strategy. LIVE remains paused via paused.live.flag pending root-cause investigation of execution drag (TP fills below 0.60, stop_loss fills past 0.10, fee leakage). NO new filters added: UTC blackout failed multiple-testing correction (only hr 16 survives Bonferroni and that's a +EV hour); SOL band widening was bin-hunting on n=50. ETH and SOL kept LIVE-eligible; BTC kept on PAPER for continued data collection."
