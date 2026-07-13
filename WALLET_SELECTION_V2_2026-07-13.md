# Wallet-selection v2 — fill-true, shrunken, out-of-time (2026-07-13)

> ## VERDICT (run 2026-07-13, 444,914 fills / 17,088 wallets / 428 GRID-era markets):
> ## **THE FADE WELL IS DRY. The optimal fade portfolio is EMPTY.**
>
> - Population mean fade-edge = **−0.002** per unit (fading a random wallet loses
>   0.2¢ before spread) and — the deep finding — **τ = 0.001**: the dispersion of
>   TRUE wallet skill across 4,043 scoreable wallets is one-tenth of a cent.
>   Nobody tracked is reliably dumb (or smart) relative to the price minutes
>   later. The best posterior fade-edge in the population is **+0.0004**; zero
>   wallets clear the +0.03 floor. A raw +0.60-edge wallet (n=9) shrinks to
>   −0.0015 — the lucky tail, exposed.
> - **Out-of-time confirmation in money terms** (Jul 6–13): fading the CURRENT
>   target list = **−15.1% ROI, clustered t=−2.55** (significantly negative);
>   fading random scored wallets = −11.9% (t=−4.58). Consistent with the actual
>   GRID-era live record (−$141 on 44 fills).
> - 2,665 of 4,043 wallets (66%) carry MM/bot signatures (frequency or
>   two-sided flow) — most tracked "wallets" are automation, and the residual
>   human flow carries no exploitable information either.
> - Latency caveat, addressed: p_after is measured 60–600s post-fill; the bot
>   acts in ~2–6s on-chain. If an edge existed only inside the first minute it
>   would be a latency race — and the live record at REAL sub-minute fills
>   (1–8 gated, −$141 GRID era) already measured that race as lost.
> - Consistent with `book_vs_market` (Polymarket now out-sharps bookmakers):
>   a market this sharp absorbs retail flow without leaving a fade edge.
>
> **Consequences:** wallet-list optimization is answered — don't fade anyone on
> GRID-era esports. The esports fade thesis should not return to live on ANY
> wallet list without this analysis flipping on a future window. R1 keeps
> running purely per its pre-registration (its fade leg is now known-dead;
> expect KILL). Confirmation re-run on the second window (~Jul 21) per the
> promotion protocol — expected to confirm dryness.

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
