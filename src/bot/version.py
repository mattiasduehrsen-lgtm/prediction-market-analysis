"""
Bot patch version - single source of truth.

Bump PATCH and add a line to PATCH_NOTES whenever a meaningful change is deployed.
The dashboard reads this via /api/version.
"""

PATCH       = "v1.32"
PATCH_DATE  = "2026-05-10"
PATCH_NOTES = "Wired WindowBrain (per-trade Claude Haiku reasoner) in advisory-only mode. The pre-existing window_brain.py was designed but never integrated. Now fires once per entry candidate per (asset, window), AFTER should_enter() passes basic filters. Returns regime classification (ranging/trending/volatile/unclear), mr_edge quality (strong/normal/degraded), edge_modifier float [-0.05, +0.05], and reasoning sentence. Brain output is LOGGED to bot.log but does NOT alter trade entry yet - advisory only. Reason: previous claude_advisor (binary block) blocked 96% of windows; window_brain is structurally different (continuous modifier, not gate). After 50+ brain-evaluated trades we'll analyze whether brain advice correlates with EV; if yes, promote to authoritative in v1.33. Cost ~$0.005/day with prompt caching. Brain runs for MR strategy on 15m and 4h windows only. window_brain.py was generalized to support per-(asset, window) filtering (was 15m-hardcoded). Reference: STRATEGY_PIVOT_SCOPING.md."
