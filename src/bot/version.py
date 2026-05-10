"""
Bot patch version - single source of truth.

Bump PATCH and add a line to PATCH_NOTES whenever a meaningful change is deployed.
The dashboard reads this via /api/version.
"""

PATCH       = "v1.30"
PATCH_DATE  = "2026-05-10"
PATCH_NOTES = "Widened SOL UP band on PAPER from [0.33, 0.35] to [0.33, 0.40] for data collection. LIVE stays at [0.33, 0.35]. Reason: 48h post-v1.28 produced ZERO SOL UP trades because SOL prices haven't been in the narrow band. Of 246 SOL skipped windows in that period, 51% were price_too_high (>0.35), 33% btc_filter, 16% price_too_low. Plan to grow SOL UP n past 200 was infeasible at current rate. Widening on PAPER lets us collect EV data on [0.35, 0.40] with v1.28 corrected accounting; LIVE stays narrow until we know the wider band is +EV. Implementation: should_enter() gets is_live kwarg; multi-loop passes False, multi-live passes True; SOL ceiling is 0.35 for LIVE, 0.40 for PAPER."
