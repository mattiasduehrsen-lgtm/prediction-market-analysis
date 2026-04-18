"""
Bot patch version — single source of truth.

Bump PATCH and add a line to PATCH_NOTES whenever a meaningful change is deployed.
The dashboard reads this via /api/version.
"""

PATCH       = "v1.16"
PATCH_DATE  = "2026-04-18"
PATCH_NOTES = "Cowork 2026-04-18 filter set: wire hard_stop_max_remaining for 15m (240s gate), soft_exit_secs 300→420s, BTC DOWN regime filter, realized-vol filter, CROSS_WINDOW_MAX 0.15→0.10, CLOB threshold 0.10→0.15."
