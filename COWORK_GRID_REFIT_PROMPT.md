# Cowork (Fable 5) — GRID-era gate re-fit. The bot is PAUSED; your job is to earn the resume.

> All data local + verified (30/30 files, `analysis/_verify_cowork_data.py`).
> Same rules as always: "no" and "this won't work" are not outputs. Iterate until
> there's a deployable answer. But remember what progress means here — **an edge
> that survives real money.** The bot is paused precisely because we shipped a
> backtest-true edge that was population-false. Don't repeat that; beat it.

## What happened (read REPORT_V2.md + PATCH_HISTORY v1.54–v1.58 for the full arc)

The v2 model + decision layer was OOS-validated (+6.1% filtered mid-range) on
2025-09→2026-06 markets — and then went **0–5 (−$75)** live. The live calibration
referee (`analysis/_live_calibration.py`, 108 resolved real signals, three
probability sources side by side) found:

| source | Brier |
|---|--:|
| **market price** | **.216** |
| Elo | .243 |
| v2 | .255 |

**The market beats both models on the CURRENT population, and v2 is worst.** The
GRID expansion (June 23+) flooded the signal stream with academy/tier-C matches:
both models are overconfident there (v2 "73%" bets win 64%), and live gate-pass
"edges" (median 0.24 vs backtest ~0.13) were miscalibration, not opportunity.
The old backtest population no longer exists. LIVE is paused (`paused.flag`).

## The new weapon you didn't have last time

`cowork_snapshot/live/price_capture/prices_*.jsonl` — **~600k real order-book
snapshots (bid/ask/depth, per minute, July 1–5) on every near-start esports market**,
props included. This is the exact live population with exact fillable prices. No more
joining approximate prices to approximate matches: backtest against THIS.
Plus: `live/fade_events.jsonl` now carries `shadow_compare` (Elo + v2 + market price
per real signal), `model_filter_pass`/`skip_bet_filter` with tiers, `live_orders.jsonl`
with exec_mode (maker/taker) + model_edge per order, and `gamedata/bo3/tier_index.parquet`.

## Mission

Build the gate that is **positive on GRID-era data with real captured quotes** —
or produce the honest, specific statement of what must accumulate before one exists,
with the exact trigger criteria for resume. Candidate levers (attack in parallel):

1. **Recalibrate on the new population**: fit isotonic/shrinkage on June-23+ outcomes
   only; or shrink model p toward market price (λ·model + (1−λ)·market) and find the
   λ where residual disagreement is real edge.
2. **Data-richness gate**: both teams ≥N matches (the failures are thin-data academy
   rosters); find N where calibration holds. Segment by tier — is there a tier band
   where the model still beats the market?
3. **Fillability-true backtest**: every bet priced from the captured ask at signal
   time (not midpoint, not trade-tape). Include the maker-vs-taker fill evidence
   from live_orders.jsonl.
4. **The prop surface**: 600k snapshots include handicaps/totals/kills quotes GRID
   just listed. Is any prop class miscalibrated at the ask (prop_edge_scan.json is
   the seed)? A NEW soft surface may beat re-sharpening the old one.
5. **In-play re-check**: cs2_inplay paper is at n≈150+; the pre-registered gate is
   contrarian n≥100 AND win-rate-vs-price p<0.02 (`analysis/_inplay_sig.py`) — run
   it; if it passes, spec the live deployment.

## Deliverables

1. GRID-era backtest results per lever, with the same honesty bar as before
   (time-split, real quotes, dose-response, paired bootstrap vs "never trade").
2. A deployable gate spec (thresholds, filters, code-level) IF anything clears
   +ROI at real fills — else the data-accumulation plan with numeric resume triggers.
3. Updated verdict table: ship / iterate / dead-redirect per lever.
