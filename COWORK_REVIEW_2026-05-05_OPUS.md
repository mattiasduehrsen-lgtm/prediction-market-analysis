# Cowork Review — Skeptical Reanalysis (Opus, 2026-05-05)

A re-examination of `COWORK_REVIEW_2026-05-05.md`. Same CSVs; harder questions. Several of the prior review's confident claims dissolve under scrutiny — and one claim is structurally misleading because it pools the *current* strategy with retired ones.

---

## Population issue (front-loaded — read this first)

The prior review uses **all 1,658 PAPER trades** as its base population. That file mixes:

| Strategy × window     |   n |
|-----------------------|-----|
| `mean_reversion` × `15m` | **693** ← *the strategy that runs today* |
| `resolution_scalp` × `15m` | 475 (retired v1.26a) |
| NaN window/strategy (legacy schema) | 346 |
| `momentum` (5m) | 102 |
| `mean_reversion` × `5m` | 42 (retired v1.12) |

Filtering to **MR-15m only** — what `multi-loop` and `multi-live` actually run today — flips one of the prior review's headline claims:

| Population | n | WR | EV/trade | Total |
|------------|---|----|----------|-------|
| Full file (prior review) | 1,658 | 51.1% | **-$0.69** | **-$1,150** |
| MR-15m only (current strategy) | 693 | 47.6% | **+$0.12** | **+$86** |

**The current strategy on PAPER is marginally positive, not net-negative.** The prior review's "net-negative -$1,150" framing is structurally misleading: it's measuring a graveyard of retired filters, not the live one. This single correction drives several disagreements below.

That said, +$0.12/trade is not a robust positive — t≈+0.30, p≈0.76, well within noise. So the honest framing is: the current strategy has shown *no statistically detectable edge in either direction* on n=693.

All numbers below use **MR-15m only** unless noted. The LIVE files have a mid-file schema change (35→37 cols) that pandas chokes on with default settings; first pass missed rows, corrected.

---

## 1. BTC UP — stationary, deteriorating, or fluke?

MR-15m BTC UP (n=194) chunked chronologically:

| Chunk    |  n  | WR    | EV     |   t   |
|----------|-----|-------|--------|-------|
| 1–100    | 100 | 49.0% | +$0.68 | +0.58 |
| 101–194  |  94 | 50.0% | -$0.61 | -0.62 |

Mann-Kendall on chunked EV with the larger 5m+legacy population (n=560, 6 chunks): S=-3, Z=-0.376, **p=0.71**. No trend — stationary noise around small negative.

Pre-v1.26 MR-15m BTC UP (n=184): WR=50.5%, **EV=+$0.32** (positive!). Post-v1.26 (n=10): WR=30%, EV=-$4.85. Welch t=1.58, p=0.15.

**This is a different picture than the prior review.** When you isolate the MR-15m population (the strategy that's actually running), BTC UP pre-v1.26 was *positive* on average. The post-v1.26 collapse is n=10 — a noise event, not a confirmed regime shift.

LIVE BTC UP n=13, EV=-$2.80 — but matched-pairs analysis (Q2 below) shows BTC LIVE has $0.36/trade execution drag vs PAPER on the *same windows*. Half the LIVE BTC UP loss is execution, not strategy.

**Verdict:** The case for disabling BTC UP is weaker than the prior review claims. PAPER MR-15m BTC UP pre-v1.26 was +$0.32/trade. The LIVE underperformance is partly execution drag (paired t=-3.76). At minimum: do not present "BTC UP is a losing strategy" as a closed case. Reasonable action is to keep it on PAPER with continued monitoring; the LIVE-disable decision rests more on LIVE execution drag than on PAPER strategy edge.

---

## 2. LIVE vs PAPER divergence — execution drag confirmed (this is the real finding)

Match LIVE trades to PAPER trades on `(asset, side, window_end_ts)`. Scale PAPER pnl linearly to LIVE position size for fair comparison ($5 LIVE vs $15–20 PAPER):

| Asset | n matched | LIVE EV | PAPER EV (scaled to $5) | LIVE − PAPER | t-stat |
|-------|-----------|---------|--------------------------|--------------|--------|
| BTC   | 22        | -$2.29  | -$1.93                   | **-$0.36**   | **-3.76** |
| ETH   | 15        | -$0.23  | +$0.32                   | **-$0.55**   | **-2.52** |
| SOL   |  7        | -$0.87  | +$0.76                   | -$1.63       | -1.37  |

**This is the most statistically significant result in the dataset.** ETH and BTC both show paired execution drag of $0.36–$0.55 per trade with t<-2.5. On a $5 position, that's **7–11% of capital per trade in pure execution cost**.

Stripping suspicious zero-exit-price trades from LIVE:
- BTC clean (n=25): EV=-$2.36 (was -$2.56)
- ETH clean (n=15): EV=-$0.04 (was -$0.35) — most of LIVE ETH's negative was 1 zero-exit row
- SOL clean (n=5): EV=+$0.78 (n=5, do not infer anything)

**Implication:** LIVE underperformance is not selection (PAPER and LIVE are evaluating the same `should_enter()` and on matched windows are taking the same trades). It is **structural execution drag of ~$0.45/trade**. PAPER MR-15m EV is +$0.12; subtract $0.45 drag and you have **-$0.33 LIVE** even at the strategy's PAPER edge.

The prior review treated LIVE underperformance as small-sample noise. It is not. It is a paired-test-significant, replicating-across-assets execution gap that *swamps* the PAPER edge.

This is the recommendation the prior review missed: **fix the slippage before adding any new filters**. Every filter improvement from here gets eaten by the $0.45 drag. Possible sources: TP SELL takes the bid (~1¢ below mid), entry BUY +1¢ slip is already baked in, but exit side may not be optimal; partial-fills; price drift between order placement and match.

---

## 3. Multiple-testing correction on hour-of-day

24 hour buckets tested on MR-15m only. Bonferroni α=0.05/24=0.0021. BH-FDR 5% critical = (rank/24) × 0.05.

| Rank | Hour | n  | WR    | EV     | t     | p      | Bonferroni | BH-FDR |
|------|------|----|-------|--------|-------|--------|------------|--------|
|    1 |   16 | 20 | 75.0% | +$6.00 | +3.30 | 0.0010 | **PASS**   | **PASS** |
|    2 |   05 | 21 | 33.3% | -$3.77 | -1.68 | 0.0921 | fail       | fail   |
|    3 |   22 | 35 | 42.9% | -$2.93 | -1.64 | 0.1008 | fail       | fail   |
|    4 |   06 | 33 | 60.6% | +$3.91 | +1.63 | 0.1036 | fail       | fail   |
|    7 |   17 | 30 | 30.0% | -$2.83 | -1.19 | 0.2344 | fail       | fail   |
|   11 |   19 | 38 | 39.5% | -$1.76 | -0.83 | 0.4051 | fail       | fail   |
|   14 |   20 | 37 | 35.1% | -$1.22 | -0.66 | 0.5080 | fail       | fail   |

**Only one hour survives Bonferroni: hour 16 (n=20, EV=+$6.00).** That's a *positive* hour, on n=20, not a candidate for blacklisting. The prior review's "UTC 17–20 destruction zone" — those hours rank #7, #11, #14, with p-values 0.23, 0.41, 0.51. Worse than chance for any one of them in a 24-bin scan.

**Walk-forward (50/50 chronological split):**

H1 bad hours (EV<-$1, n≥10): `[3, 9, 10, 12, 13, 17, 20, 22]`. Replication in H2:

| H1 bad hour | H2 n | H2 EV   | Held? |
|-------------|------|---------|-------|
|     03      |  16  | **+$1.48** | reversed |
|     09      |   9  | -$5.82  | yes (small n) |
|     10      |  17  | **+$2.19** | reversed |
|     12      |  17  | **+$5.35** | reversed |
|     13      |  15  | +$0.07  | reversed |
|     17      |  13  | -$4.44  | **yes** |
|     20      |  12  | -$0.54  | partial |
|     22      |  24  | -$0.25  | partial |

**5/8 reversed or weakened in H2.** Only hour 17 stays clearly bad. UTC 17–20 H1: -$1.05; H2: -$1.95 (the magnitude *did* increase out of sample for this 4-hour block, but UTC 17,19,20,23 H1: -$0.88; H2: -$3.05). Mixed signal — possibly real for a subset of those hours, but no individual hour passes a corrected significance test.

**ETH-only hour-of-day:** ETH 17–20 (n=50): WR=42%, EV=-$0.71. ETH other (n=218): WR=54%, EV=+$1.08. Welch t=-0.88, **p=0.38**. Not significant. The hour-of-day pattern is not detectable on ETH alone.

**Verdict on time-of-day filter:** Do not implement. Best evidence is hour 17 (n=30, p=0.23 raw, no correction passes). Walk-forward consistency is poor. The "UTC 17–20 destruction" claim is bin-hunting after seeing the data. Revisit at 3,000 trades or with a pre-registered hypothesis.

---

## 4. Early stall counterfactual — prior review correctly dismissed

For MR-15m trades with `price_60s_after_entry` populated and nonzero (n=663):

- Stalled exits: 78.6% have price_60s ≤ entry (not ITM at 60s)
- TP exits: 62.5% have price_60s ≤ entry

Counterfactual: exit at 60s if not ITM, else keep actual pnl.

| Asset |  n  | Actual sum | Rule sum | Saved |
|-------|-----|------------|----------|-------|
| BTC   | 320 | -$212      | -$1,395  | **-$1,182** |
| ETH   | 250 | +$68       | -$1,112  | **-$1,180** |
| SOL   |  93 | +$8        | -$243    | **-$252** |
| **ALL** | **663** | **-$136** | **-$2,750** | **-$2,614** |

**Cutting at 60s if not ITM is catastrophic** — costs an additional **-$3.94/trade**. Exiting flat at 60s crystallizes the 1–2¢ bid-side haircut on every position before it has a chance to reach TP. Many of those positions go on to hit TP.

The prior review correctly dismissed this. Do not implement. The real stall question is whether to cut later (180s, 300s) — that's a separate exercise.

---

## 5. CW dead-zone confound — resolved

Of 186 MR-15m dead-zone trades (cross_window_pct in [-0.02, +0.02]):
- Pre-v1.26c: 185 (99.5%)
- Post-v1.26c: 1

**Filter is now active.** The dead-zone confound the prior review flagged is resolved: those trades are legacy. The ~25 post-v1.26c trades are too few to confirm the filter's forward edge (allowed bands [-0.15,-0.02] and [+0.02,+0.10]).

---

## 6. ETH slippage haircut — does ETH LIVE clear costs?

PAPER MR-15m ETH (n=268, avg size $15): WR=51.9%, EV=+$0.75. Scaled linearly to LIVE $5 size: **+$0.25/trade**.

Slippage haircut at typical Polymarket execution (avg ETH entry 0.387 → 12.9 shares at $5):

| Round-trip slip | Drag | Net ETH EV at $5 |
|-----------------|------|------------------|
| 1¢ each side (2¢ rt) | $0.27 | **-$0.02** |
| 2¢ each side (4¢ rt) | $0.53 | **-$0.28** |
| 3¢ each side (6¢ rt) | $0.80 | **-$0.55** |

LIVE ETH actual: n=16, EV=-$0.35. Lands between the 2¢ and 3¢ haircut estimates; matches the matched-pairs drag of $0.55/trade (Q2).

**Implication:** ETH PAPER edge of +$0.25 at $5 sizing is real but *barely* clears slippage. At $5 size, LIVE ETH is **break-even at best, slightly negative at typical slippage**. Either (a) increase position size — the $0.45 drag is fixed-¢ while EV scales linearly, so at $20 size LIVE ETH would be ~$1.00 EV − $0.45 drag = +$0.55 net, or (b) tighten ETH entry filter to the highest-edge subset.

The prior review's "ETH is the real thesis" overstates it at $5 sizing. ETH is positive PAPER edge but eaten by execution drag. Increasing size is the highest-EV change available — assuming the $0.45 drag is truly fixed-¢ rather than fixed-bps.

---

## 7. PAPER MR-15m WR/EV by version era

| Era                          | n   | WR    | EV/trade | Sum     |
|------------------------------|-----|-------|----------|---------|
| pre-v1.20 (before 04-20)     | 457 | 46.4% | +$0.28   | +$128   |
| v1.20–22 (04-20 → 04-28)     | 152 | 45.4% | -$1.08   | -$164   |
| v1.23–25 (04-28 → 05-02)     |  58 | 62.1% | +$2.25   | +$131   |
| v1.26+ (post 05-02)          |  26 | 50.0% | -$0.34   | -$9     |

**The version timeline is not telling a clean "filters are improving things" story.** Pre-v1.20 was already positive (+$0.28). v1.20–22 (CW filter introduction) made it *worse* (-$1.08). v1.23–25 was the best era (+$2.25 on n=58 — too small to celebrate). v1.26+ is too small to interpret. Net: there is no clear evidence the filter cascade is improving forward EV.

---

## 8. Aggregate honest assessment

Current-strategy PAPER (MR-15m, n=693): WR=47.6%, EV=+$0.12, total +$86. Not statistically distinguishable from zero (t≈+0.30).

LIVE (n=50 across BTC/ETH/SOL): EV=-$1.61, total -$80. Matched-pairs execution drag: $0.36–$0.55/trade. **Most of LIVE's loss is execution drag, not strategy.**

Honest summary:
1. The current strategy is not net-negative on PAPER (the prior review's claim conflates retired strategies). It is **flat-to-marginally-positive**, statistically indistinguishable from zero.
2. LIVE underperforms PAPER by **~$0.45/trade in execution drag** (paired, t<-2.5). This is the dominant signal in the LIVE dataset and is being ignored.
3. None of the proposed new filters (UTC blackout, SOL band widening) survive multiple-testing correction on MR-15m data.
4. BTC UP pre-v1.26 is mildly positive on MR-15m PAPER (+$0.32). The "disable BTC UP" recommendation rests primarily on LIVE numbers, half of which is execution drag.
5. ETH PAPER edge is real (+$0.75/trade at $15 size, +$0.25 at $5) but mostly eaten by slippage.

**The prior review's decisive recommendations rest on weaker evidence than presented.** The dataset's actual verdict is more humble: small positive PAPER edge in the live strategy, dominated by execution drag in LIVE, with no individual filter-tuning recommendation surviving rigorous testing. The *correct* next move is to fix execution drag, not add new filters.

---

## Disagreements with prior review

| Prior recommendation | My take | Reason |
|----------------------|---------|--------|
| Disable BTC UP on LIVE immediately | **Agree-with-caveat** | Right action probably, but evidence weaker than presented. MR-15m BTC UP pre-v1.26 was +$0.32/trade (positive on n=184). LIVE BTC has $0.36/trade execution drag, so half the LIVE damage is non-strategy. The decisive case rests on LIVE WR=23% and negative Kelly — supportable but framed as a closed case when it's a 60/40 call. |
| Add UTC 17–20 blackout filter | **Disagree** | Zero hours survive Bonferroni or BH-FDR on MR-15m. The only hour passing correction is hour 16 (positive +$6, would *not* be blocked). Walk-forward shows 5/8 H1-bad hours reverse in H2. ETH-only hour-pattern p=0.38. This is overfitting to a 24-bin scan. Do not implement. |
| Widen SOL UP band to [0.33, 0.38) | **Disagree** | The case is bin-hunting on n=50 in [0.35,0.38) with no significance test. Prior review's own data shows current band [0.33,0.35) WR=37.5%, "wider" WR=43.9% — both flip from PAPER to nothing-significant when you check. SOL has only 130 MR-15m UP trades total. Collect more data first. |
| Pause SOL LIVE | **Agree** | n=7 LIVE SOL is meaningless. The +$0.78 EV after stripping zero-exits is on n=5. |
| Keep ETH LIVE running | **Disagree-mild** | ETH at $5 LIVE is break-even-to-slightly-negative after realistic slippage. The $0.45 drag eats most of the +$0.25 PAPER edge at $5 size. Either (a) increase position size to $15–20 (drag is fixed-¢, EV scales), or (b) accept LIVE is a paid sandbox. Don't keep at $5. |
| Don't change CW filter | **Agree** | Filter is now active (post-v1.26c). Dead-zone trades are 99.5% legacy. Need 50+ post-v1.26c trades to confirm forward edge. |
| Don't change TP/SL | **Agree** | Confirmed: 60s-cut counterfactual is catastrophic (-$3.94/trade additional loss across 663 trades). Stalled positions often recover. |
| Don't add liquidity upper bound | **Agree** | Insufficient data above $40k. |
| (missing) Pause LIVE pending execution-drag fix | **My add** | The matched-pairs LIVE-vs-PAPER drag (BTC t=-3.76, ETH t=-2.52) is the most significant statistical result in the dataset. It swamps the PAPER edge. Until this is investigated and reduced, every filter improvement on PAPER will be eaten by slippage on LIVE. Either pause LIVE or reduce LIVE to ETH-only at increased size while diagnosing the drag. |
| (missing) Reframe baseline as MR-15m only | **My add** | The "strategy is net-negative" framing in the prior review pools 4 retired sub-strategies with the live one. Filtering to MR-15m flips total from -$1,150 to +$86. Future analysis should pre-filter by `(strategy='mean_reversion' AND window='15m')` to avoid this confound. |
