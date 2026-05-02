"""
Bot patch version — single source of truth.

Bump PATCH and add a line to PATCH_NOTES whenever a meaningful change is deployed.
The dashboard reads this via /api/version.
"""

PATCH       = "v1.26a"
PATCH_DATE  = "2026-05-02"
PATCH_NOTES = "Phase 1 of Cowork May 1 deep-dive v1.26 implementation: kill RS entirely + generalize cross-window filter. (1) Removed all RS configs from multi-loop default argv (lines 1176-1178). Cowork reanalysis found April 25 RS findings were false positive at small N (n=55, z=2.43 → p~0.05 at Bonferroni limit); with 3x data all RS sub-strategies are net-negative (ETH DOWN 56% WR/-$86, SOL DOWN 60% WR/+$6) and structurally unsalvageable (avg_loss/avg_win = 7.7/3.5 requires ~69% WR to break even, actual max 61%). (2) Removed is_live parameter from should_enter_resolution_scalp() in signal_5m.py — RS dead code now. (3) Generalized v1.22 ETH cross-window filter [-0.10,-0.02]U[+0.03,+0.10] to all assets (BTC, ETH, SOL). This filter isolated profitable momentum-continuation regimes in Cowork analysis. Removed global CROSS_WINDOW_MIN/MAX check (lines 54-60) and unified all assets on the union filter. PAPER now runs 3 sub-strategies (BTC/ETH/SOL MR) instead of 6. LIVE unchanged (still 3 MR threads). v1.26b (crash regime filter) follows separately for validation."
