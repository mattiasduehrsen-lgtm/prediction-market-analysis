# GRID-era gate re-fit — results (Cowork Fable 5, 2026-07-05)

**Mandate:** build a gate that is positive on GRID-era data with real captured quotes, or state
honestly what must accumulate before one exists, with numeric resume triggers.

**Verdict up front: nothing clears the bar for live money today.** One lever — market-anchored
recalibration of v2 — is promising (+16% to +32% ROI fill-true on the July capture depending on
pipeline micro-choices, and it opposite-sides the live bot's actual losers), but it rests on 21–24
bets over 4.5 days, fails significance (price-matched excess P≈0.13–0.33), and **is fragile: moving a
single June signal between fit and eval shifts an isotonic plateau and swings July ROI by ±15pp.**
That fragility is itself the finding — the sample cannot support a live decision. Everything else is
dead or must wait for the laptop. The deployable output is a **paper-validation spec with
pre-registered numeric resume triggers** (§6). LIVE stays paused.

All numbers reproducible via `analysis/_grid_refit_2026-07-05.py` (consolidated; runs on the
snapshot only). Data: 30/30 files verified.

---

## 0. Ground truth updates since the prompt was written

- The live record has worsened: GRID-era (Jun 23+) realized is **−$141.29 on 44 resolved fills**;
  post-v1.57 the gated fade is **1–8, −$83.28** (the 0–5/−$75 in the prompt, plus 3 more losses and
  one +$36.72 LoL longshot win).
- Referee reproduced on 117 resolved shadow signals (was 108): market Brier **.222** < Elo **.246** < v2 **.258**.
- Two of the nine post-v1.57 fills were **prop markets** (a LoL game-handicap, twice) — see §4 for
  why fading into props at these quotes is structurally terrible, independent of any model.
- The bot **doubled into the same losing match** twice (mibra-vexa1 ×2, paina-bsta ×2, mw-mag ×2,
  each same-day). Correlated re-entry is uncontrolled at the match level.

The single most important diagnostic (188 resolved GRID-era signals, live-logged probs):

| raw v2 edge bucket | n | market says | v2 says | actually won | who's right |
|---|--:|--:|--:|--:|---|
| ≤ −0.10 (v2: "overpriced") | 49 | .717 | .475 | **.592** | truth in the middle |
| −0.05..+0.05 | 52 | ~.49 | ~.49 | .56 | both fine |
| +0.05..+0.10 | 25 | .443 | .513 | .400 | market |
| +0.10..+0.20 (gate bets) | 23 | .410 | .553 | **.304** | market, by a mile |
| > +0.20 (gate's best bets) | 24 | .240 | .583 | **.250** | market, exactly |

**Dose-response is inverted for raw v2: the more edge it claims, the more wrong it is.** Where v2
sees its biggest edges, the market price is already the truth. That is why v1.57 went 1–8. But note
the top row: when v2 says a price is too HIGH, the market really is ~12pp too high — the model's
disagreement direction carries information; its magnitude is what lies. That asymmetry is exactly
what recalibration exploits (§1).

---

## 1. Lever 1 — recalibrate on the GRID population → **the one live lever. ITERATE (paper), do not ship.**

Method: 188 resolved GRID-era signals with live-logged v2 probs. Time split: fit = Jun 23–30 (n=80),
eval = Jul 1–5 (n=108). Recalibrations fitted on the fit half only, evaluated once on the eval half.

Brier on the eval half: market .2401, raw v2 .2543, logit-blend k=0.25 .2375, prob-blend λ=0.14 .2379,
June-fit isotonic(v2) .2461. Blends beat the market by a hair; k̂ fit on June ≈ 0.125 — the honest
optimal weight of v2 vs the market is about **one-eighth**.

Trading sims, eval half only (canonical numbers = `_grid_refit_2026-07-05.py`; session-pipeline
variant in parentheses — the spread between them is the fragility warning above):

| gate | th | n | ROI | significance |
|---|--:|--:|--:|--|
| raw v2 (current live gate), entry+1¢ | 0.10 | 20 | **−17.5%** | P(PnL≤0)=.72 |
| isotonic June-frozen, entry+1¢ | 0.05 | 22 (20) | **+4.7%** (+15.1%) | P(PnL≤0)=.47 (.36) |
| isotonic June-frozen, **captured ask** | 0.02 | 24 (21) | **+15.6%** (+32.1%) | P(excess≤0)=.33 (.13) |
| isotonic June-frozen, **captured ask** | 0.05 | 16 (11) | **+25.1%** (+55.2%) | P(excess≤0)=.28 (.11) |

The fill-true gate frequently takes the **opposite side of the live bot in the same match** (bought
MAGICOS 0.30 where LIVE bought METANOIA 0.59/0.48 and lost; bought Guara 0.21* where LIVE bought
Procyon 0.49 and lost). But: ~11W/10L, best single win is 3.8u (ROI excluding it +14.9% in the
session variant), PnL by day +5.2/+3.4/−0.8/−1.0, and no variant clears price-matched significance.
**Direction consistent across all variants and both pricing methods; proof absent. n must accumulate.**
(*ge3-pcy cleared the 0.20 floor at the captured ask of 0.21.)

What the recalibration actually is: the GRID-era truth curve collapses v2's confident range
(v2 0.40→0.72 all map to realized ~0.48–0.57). It mostly says: *v2's spread on this population is
noise; trust deviations only at the extremes.*

## 2. Lever 2 — data-richness / tier gate → **DEAD as a fix.**

No games floor rescues the model: CS2 Brier diff (market − v2) is negative on BOTH time halves at
every floor (0/30/75/150 games). LoL flips sign between halves (noise). The gate's actual failed
bets had **median 61 games and tiers 2/3 or unjoined — not thin-data academy rosters.** The
"academy flood" story is true of the population shift but false as a filterable cause: v2 is
miscalibrated against this market everywhere, including on data-rich tier-A matches (tier 2 is its
*worst* band: v2 .293 vs market .218). Keep tier/entry rules as risk hygiene; they will not create edge.

## 3. Lever 3 — fillability-true backtest → **BUILT; it is the new referee.**

688,254 captured book snapshots → 67 resolved series markets Jul 1–5 with pre-start executable
quotes (T−5min), both sides reconstructed from one token's book (buy B = 1−bid_A; median series
spread 0.01–0.02, two-side cost sum 1.02). Resolution labels cross-validated against terminal
captured prices: 29/29 agree.

- Current raw-v2 gate at real asks: n=13, +18.8%, price-matched excess +0.16u, P(excess≤0)=.32 —
  statistically nothing, and its th=0.10 eval-half twin at entry prices was −17.5%. The live 1–8 is
  the same coin.
- **Window warning:** buy-EVERY-side ROI in this window is +15% — two sub-20¢ longshots hit. Underdog
  overperformance overall is insignificant (z=+0.54). Any GRID-era backtest MUST be judged against a
  price-matched baseline, which is what the excess test above does.
- Maker/taker: only 19 tagged orders exist since v1.56 (5 maker, 14 taker) — far too few for the
  adverse-selection read. Keep the tagging running.
- Coverage hole: only 54/67 July series markets got a model price. 13 GRID-era teams are absent
  from the model state. Local predictor vs live-logged probs on the same markets: MAE .076,
  corr .68 — the state build / daily refresh materially moves probs (part may be sklearn version
  skew in this sandbox). The weekly-refresh cadence of the state is a real live-risk item.

## 4. Lever 4 — prop surface → **DEAD-REDIRECT. Do not touch props at these quotes. Ever.**

Both sides of every prop class, priced at executable quotes (T−5), cluster-bootstrapped by match:

| class | side-Y ROI | side-N ROI | median spread |
|---|--:|--:|--:|
| handicap | −32% | −9% | 0.45 |
| totals | −25% | −21% | 0.69 |
| kills | −60% | −29% | 0.68 |
| occurrence | −61% | −46% | 0.88 |
| map_winner | −11% | −13% | 0.05 |
| firsts | −16% | −24% | 0.15 |

Frequency z-scores −2.5 to −10. There is no soft side: the spread IS the market maker's model, and
crossing it is the only thing GRID props let a taker do. The only conceivable play is being the
maker inside those spreads — a different business with unmeasured adverse selection; not this bot.
**Immediate code-level rule regardless of everything else: exclude prop slugs from all fading**
(the live bot lost 2 of its 9 post-v1.57 fills on a handicap market).

## 5. Lever 5 — in-play pre-registered gate → **CANNOT ADJUDICATE FROM THE SNAPSHOT; run on laptop.**

`output/cs2_inplay/paper_results.csv` (the n≈150+ live paper stream) is not in the snapshot — only
the historical 122-row join (2025-09→2026-01) is. On that historical population, blanket contrarian
is *negative* (all: z=−1.49; ≤0.30: z=−0.51, −0.1% ROI; only ≤0.15 positive at n=33, p=.30) — i.e.
the June paper +40% is not a re-expression of an old population-wide effect, which makes the
pre-registered test on the live stream genuinely decisive. Run on the laptop:

```powershell
.venv\Scripts\python.exe -u analysis\_inplay_sig.py
```

Gate (pre-registered, unchanged): **contrarian n≥100 AND win-rate-vs-price p<0.02.** If it passes,
spec live deployment in a dedicated session (it will need its own fill-true check against the
in-play capture, which the price logger already records). If p is in (0.02, 0.10), keep paper
running to n=200 and re-run once. No peeking in between.

---

## 6. The deployable output: paper-validation spec + numeric resume triggers

Nothing goes live now. The following goes to PAPER (code-level spec; the paper path already exists):

**Gate spec "R1" (recalibrated fade gate):**
1. Signal source: unchanged (fade stream, all existing caps/filters upstream).
2. Probability: `p_r1 = iso(v2_p)` with the **frozen curve** fit on all 188 GRID-era resolved
   signals (breakpoints: ≤0.15→0.00, 0.20→0.03, 0.25→0.18, 0.30–0.35→0.35, 0.40–0.65→0.48,
   0.70–0.80→0.57, 0.85→0.82, ≥0.90→1.0; linear between; store as a table, not a refit).
3. Bet iff `p_r1 − best_ask ≥ 0.05` and `0.20 < best_ask < 0.95` and ask-depth ≥ bet.
   (0.05 chosen from the fit half; 0.02 traded more but thinner excess.)
4. CS2 tier rule stays (known & non-S). LoL: **observe-only again** — LoL failed both the Brier
   eval half and the fill-true sim (−12.6%); v1.55's go-live gates never included a price test.
5. **No props** (slug filter), **max 1 gated entry per match per day**.
6. Log `p_r1`, ask, depth, tier at decision time (the capture logger keeps running — it is the
   referee for everything now).

**Resume triggers (pre-registered here; do not re-derive after seeing results):**
- **GO-LIVE** when, on ≥150 resolved R1 paper bets at captured asks: ROI > +10% AND price-matched
  excess > 0 with cluster-bootstrap P(≤0) < 0.05. At ~4.7 gated bets/day → first read ~32 days
  (early August). If true edge ≈ +30% (July point estimate), this passes; if ≈ +10%, it needs
  ~250 bets — accept the wait; that is the cost of the v1.57 lesson.
- **KILL R1** if at any n ≥ 60 the running ROI < −10% (symmetric protection against the inverse mistake).
- **Secondary health metric** (not a go-live trigger): rolling 200-signal Brier of `p_r1` vs market;
  R1 should stay within .01 of market. If it drifts worse by >.02, refit the curve (new curve =
  new pre-registration, clock restarts).
- **In-play:** laptop adjudication per §5; its gate is its own trigger.
- **Weekly during accumulation:** refresh model state + tier index (the 13-team coverage hole and
  the June-5 state staleness are live risks); keep maker/taker tagging accruing toward the
  ~100-fill adverse-selection read.

## 7. Verdict table

| lever | verdict | one-line reason |
|---|---|---|
| 1. Recalibration (isotonic / λ≈0.1–0.25 market anchor) | **ITERATE — paper with triggers (§6)** | Only lever with positive OOS direction at real fills; n≈21–24 and ±15pp pipeline fragility is not proof |
| 2. Data-richness / tier gate | **DEAD as edge source** | v2 loses to market at every games floor and every tier band, both halves |
| 3. Fill-true backtest infra | **SHIPPED (analysis)** | 688k snapshots → the permanent referee; all future claims priced at captured asks |
| 4. Prop surface | **DEAD-REDIRECT** | Every class, both sides, −9%..−61% at quotes; spreads 0.05–0.88; ban props from fading |
| 5. In-play | **BLOCKED on laptop data** | Pre-registered test must run on `output/cs2_inplay/paper_results.csv`; historical join says the old population had no blanket contrarian edge |

**The honest one-sentence summary:** the GRID population repriced the market faster than the model,
the only measurable edge left is the *direction* (not size) of the model's disagreement, and that
edge is worth trading only if five more weeks of paper data agree — the triggers above make that
decision mechanical instead of hopeful.

---

*Session artifacts: `analysis/_grid_refit_2026-07-05.py` (consolidated reproduction).
No bot code touched, no restarts, LIVE remains paused (`paused.flag` intact).*
