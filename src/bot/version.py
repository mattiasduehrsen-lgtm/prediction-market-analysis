"""
Bot patch version - single source of truth.

Bump PATCH and add a line to PATCH_NOTES whenever a meaningful change is deployed.
The dashboard reads this via /api/version.
"""

PATCH       = "v1.36"
PATCH_DATE  = "2026-05-27"
PATCH_NOTES = "Sports fade bot enters LIVE mode (MLB only). After 4 days of paper data on the v2 sports bot (1095 resolved trades), MLB held the cleanest signal: +7.2% ROI over 355 trades with 58.6% win rate. Tennis collapsed from +2.5% to -19.3% on May 27 (single-day blowup, 311 new trades net -$581) and is excluded from LIVE. NBA still +10.6% but season ending; NHL sample too small (34 trades). MLB-only deployment at $5/trade. Strategy: bot now accepts --live flag (was forcibly PAPER before). When --live is on AND market slug starts with LIVE_SPORTS_PREFIXES ('mlb-'), bot places real CLOB orders via the same place_live_order pipeline as esports_fade_bot. When --live is on but slug isn't MLB, bot falls back to paper logging - data collection on NHL/Tennis/NBA continues uninterrupted. DAILY_LOSS_CAP for sports lowered 150->75 (sport LIVE bankroll is independent from esports). New evaluate_sports_live.py mirrors esports evaluate_live.py but writes to output/sports_fade/ paths. New scheduled task PolyBotSportsLiveEval runs every 10 min to refresh live_daily_pnl.json so the sports bot's loss cap can fire. Watch_sports_fade.bat now launches with --live. Wallet shared with esports for now - data ledgers are fully separate (output/sports_fade vs output/esports_fade). Starting bet size $5/trade; bump after ~200 live trades hold positive ROI."
