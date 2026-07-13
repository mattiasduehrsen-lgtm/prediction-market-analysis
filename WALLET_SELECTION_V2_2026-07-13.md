# Wallet-selection v2 — fill-true, shrunken, out-of-time (2026-07-13)

**Goal:** super-optimize which wallets the esports fade targets. Design first,
then a pipeline (`analysis/wallet_scores.py`), then a pre-registered promotion
bar. Nothing swaps into `fade_targets.json` from today's run alone.

## Why the current picker is statistically naive

The current list (`identify_active_targets.py`, frozen 2026-05-23 lineage) ranks
wallets by historical ROI ascending with ad-hoc guards (>30 trades/day excluded,
ROI<−15% & recent<−5%, cap 300). Five structural problems:

1. **Selection on noise.** Ranking thousands of wallets by raw ROI selects the
   *unlucky* tail, not the *dumb* tail. Future performance regresses to the mean;
   the historical extreme was substantially luck. This alone predicts live fade
   ROI ≪ backtest — which is what happened (+133% backtest → ~−1.5% live).
2. **Wrong property.** "Loses money" ≠ "fadeable". Everyone paying spread loses
   slowly; fading them earns ≈ −spread. The fadeable property is
   **information-negative flow relative to price we can get**: conditional on the
   wallet backing X, X wins *less* than the price 1–10 minutes later implies.
   That per-fill residual (p_after − won) is the quantity to rank on.
3. **MM/bot contamination.** Spread-capturers look mildly ROI-negative on
   directional accounting with huge n (the 0x47138dc1 lesson: one such wallet WAS
   the entire live loss). Frequency + two-sided-flow signatures identify them
   structurally; a >30/day cutoff is a crude proxy.
4. **Regime shift.** GRID (Jun 23) repriced the market to sharper-than-bookmaker
   (book_vs_market: corr .96, Polymarket beats the book's Brier, follow-the-book
   0–6). Pre-GRID wallet skill may not transfer. Scores must be fit and — more
   importantly — **evaluated** inside the GRID era.
5. **No out-of-time referee.** The list has never been validated by "select on
   window 1, measure fade PnL at achievable prices on window 2." That is the only
   score that counts.

## The v2 architecture

- **Data:** full GRID-era tape per series market (every wallet's every fill:
  wallet, outcome, price, size, ts) + resolutions. SELLs are normalized to
  complement-buys so every action is "backed outcome O at effective prob p".
- **Per-fill fade edge:** `p_after − won(O)`, where `p_after` = last traded prob
  of O in [fill+60s, fill+600s] (≈ our achievable entry, before +1¢). Aggregated
  per (wallet, market) first — repeat fills on one match are one observation.
- **Empirical-Bayes shrinkage:** wallet means are shrunk toward the population
  mean with variance-weighted posteriors (τ² by method of moments). Kills the
  lucky-tail selection; a 6-market wallet cannot out-rank a 40-market wallet on
  noise.
- **Structural MM exclusion:** fills/day > 30 OR both-sides-of-same-market
  fraction > 20% → excluded from targeting regardless of score (reported
  separately).
- **Out-of-time eval:** scores fit on Jun 23–Jul 5 fills; fade simulated on
  Jul 6–13 fills of the selected wallets at achievable complement prices (+1¢),
  one fade per (market, outcome), cluster-bootstrapped by match. Baseline = the
  CURRENT fade_targets.json list run through the identical simulator.

## Pre-registered promotion bar (set before today's results)

Swap the live target list only if ALL hold:
1. v2 selection OOS fade ROI > baseline list's on the same window, and
2. v2 OOS fade edge > 0 with cluster-t ≥ 2, and
3. it repeats on a **second, disjoint eval window** (≈ Jul 14–21, run next week).

Condition 3 means **no promotion today under any result.** If v2 fails both
windows, the honest conclusion is that no wallet cohort carries fadeable
information in the GRID-era market — the fade well is dry, and R1
(fade+model agreement) is the only surviving esports hypothesis.

## Out of scope today (v2.1 candidates, only if v2 shows signal)

Hierarchical priors from wallet covariates (price-band tilt, breadth, account
age, streak-chasing), pre-GRID history as prior-only (never as eval), LoL/CS2
separate pools, consensus-of-losers interaction, per-wallet Kelly weighting.
