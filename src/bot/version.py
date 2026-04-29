"""
Bot patch version — single source of truth.

Bump PATCH and add a line to PATCH_NOTES whenever a meaningful change is deployed.
The dashboard reads this via /api/version.
"""

PATCH       = "v1.25"
PATCH_DATE  = "2026-04-28"
PATCH_NOTES = "HOTFIX: revert v1.24 RS-on-LIVE rollout. v1.24 added ETH/SOL RS threads to multi-live default argv, but LiveEngine5m has no `open()` method (only place_entry/place_exit, used by MR). Every RS-LIVE entry attempt has been crashing with AttributeError every second since v1.24 deployed (~24h of error spam in bot.log). Even with the AttributeError fixed, LiveEngine5m's hard_stop_floor and soft_exit_stalled exits would mishandle RS positions which need TP=0.99-unreachable + force_exit_at_window_end. Proper LIVE RS requires engine refactor — out of scope here. v1.25: (1) remove RS threads from multi-live default argv, (2) add defensive `if live: continue` guard at RS call site in main.py. PAPER unchanged (still runs all 6 sub-strategies). MR on LIVE unchanged. Coincides with Polymarket V2 cutover (April 28 11:00 UTC); v1.18 SDK migration to py-clob-client-v2 already complete."
