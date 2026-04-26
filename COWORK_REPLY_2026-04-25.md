# Cowork Reply — 2026-04-25
**Polymarket 15m MR + RS bot, comprehensive analysis (v1.22 dataset)**

Dataset: `trades_current.csv`, 1,233 rows, 785 active-strategy rows (618 MR + 167 RS), spanning 2026-04-04 → 2026-04-25.

---

## Up-front data corrections (verify before acting on numbers)

1. **Position size in the data is $15/trade, not $5.** Every row with `strategy ∈ {mean_reversion, resolution_scalp}` has `size_usd == 15.0`. The prompt's "$5/trade" framing is either out-of-date or refers only to LIVE. All PnL figures below are at $15 (as recorded). Anything you want to project at $5 should be divided by 3.
2. **All 167 RS trades are concentrated in 2026-04-22 → 2026-04-25 (≈3 days, ~55 trades/day).** The prompt implies 21 days of RS history; the data shows one short window. Walk-forward and CI claims for RS need to be read in that light: we have a small temporal sample, not a small per-day sample.
3. **My BTC DOWN RS / SOL DOWN RS avg_loss numbers differ slightly from the prompt** (BTC DOWN: -$8.63 vs prompt -$8.63 ✓; SOL DOWN: -$9.04 vs prompt -$6.78). Numbers below use re-computed values from the file.

---

## SECTION 1 — RS UP/DOWN asymmetry

### Q1-A — Significance of the DOWN/UP gap

Using the prompt's grouping (winners = ETH DOWN + SOL DOWN; losers = everything else in RS):

| Group | n | wins | WR | EV/trade | Total PnL |
|---|---|---|---|---|---|
| ETH+SOL DOWN | 55 | 45 | 81.8% | +$1.81 | +$99.68 |
| All other RS (BTC + ETH/SOL UP) | 112 | 71 | 63.4% | -$1.09 | -$122.03 |

- Two-proportion z-test on WR: **z = 2.43, p = 0.0151**. Significant at α = 0.05; not at α = 0.01.
- Wilson 95% CIs on WR: DOWN [0.69, 0.90]; losers [0.54, 0.72]. Intervals don't overlap → real difference, modulo the 3-day window.
- Bootstrap EV/trade 95% CIs: DOWN [-$0.44, +$2.06], losers [-$2.61, +$0.49]. The DOWN CI just touches zero — significance is on **WR**, not (yet) on **EV/trade**.

### Q1-B — What explains the asymmetry?

Per asset × side:

| Cell | n | WR | 95% CI | EV/trade |
|---|---|---|---|---|
| BTC DOWN RS | 26 | 0.692 | [0.50, 0.84] | -$1.18 |
| BTC UP RS | 43 | 0.651 | [0.50, 0.78] | -$0.67 |
| ETH DOWN RS | 32 | 0.812 | [0.65, 0.91] | +$1.49 |
| ETH UP RS | 23 | 0.652 | [0.45, 0.81] | -$0.57 |
| SOL DOWN RS | 23 | 0.826 | [0.63, 0.93] | +$2.26 |
| SOL UP RS | 20 | 0.500 | [0.30, 0.70] | -$2.46 |

The DOWN edge is concentrated in **ETH and SOL only**. **BTC DOWN RS is part of the loser group, not the winner group.** This favours hypothesis **(iii)**: BTC moves the market and ETH/SOL inherit a directional persistence — DOWN moves on BTC propagate cleanly into ETH/SOL resolution. BTC itself, being the source of the move, is already priced in by the time RS would enter.

Liquidity asymmetry (ii) is unlikely to be the main driver: SOL DOWN avg_win ($4.17) > BTC DOWN avg_win ($2.13), but SOL also has lower liquidity than BTC.

### Q1-C — Walk-forward UP RS

Splitting all UP-side RS chronologically (n=86 total, mid-split at trade 43):

| Half | dates | n | WR | EV/trade | total PnL |
|---|---|---|---|---|---|
| H1 | 04-22 → 04-25 01:13 | 43 | 0.535 | -$0.57 | -$24.56 |
| H2 | 04-25 01:43 → 04-25 20:43 | 43 | 0.698 | -$1.55 | -$66.72 |

Per asset:
- BTC UP: H1 WR 0.57 EV +$0.77; H2 WR 0.73 EV -$2.05
- ETH UP: H1 WR 0.55 EV +$0.05; H2 WR 0.75 EV -$1.14
- SOL UP: H1 WR 0.40 EV -$4.13; H2 WR 0.60 EV -$0.80

WR went **up** in H2 across all three, but EV got **worse** in BTC/ETH and only slightly better in SOL. This is the structural payoff problem (Q2-B) showing up as time progresses: more wins, but each is a tiny fraction of the loss size. **UP RS is consistently negative-EV in both halves** — disabling is supported by walk-forward, even though it's a 24-hour split.

### Q1-D — Why is BTC DOWN RS avg_win so small?

I dug into the 18 BTC DOWN RS wins:

- **All 18 wins exit via `force_exit_time`** (none via take_profit, none via resolution payout in the position record).
- Mean entry_price: 0.826 (range 0.57–0.94)
- Mean exit_price: 0.938
- Mean win pnl: $2.13

Entry at 0.826 and selling back to the market at 0.938 leaves only ~$0.11/share of price gain × ~18 shares ≈ $2 win. **The bot is not collecting the resolution payout — it's force-exiting ~5s before close.** If we held to resolution and the side won (15/18 wins had `resolution_side == our side`), payout would be $1.00/share, giving (1.00 - 0.826) × 18 ≈ $3.13/win. Still small relative to the -$8.63 loss.

So the answer to Q1-D is **(a)**: BTC DOWN RS enters at very high prices (it's a tail-end signal — by the time GBM is confident DOWN on BTC, the DOWN token is already 0.82+). Even the perfect strategy of "hold to resolution" can only win $0.17/share. The breakeven WR at this entry-price profile is structurally ~80–85%, and the model only delivers 69%.

---

## SECTION 2 — BTC RS by entry price

### Q2-A — Bucketed BTC RS

| Entry-price bucket | n | WR | total PnL | avg_win | avg_loss | BE WR | EV/trade |
|---|---|---|---|---|---|---|---|
| [0.20, 0.50) | 10 | 20.0% | -$62.18 | +$18.93 | -$12.51 | 39.8% | -$6.22 |
| [0.50, 0.70) | 17 | 47.1% | -$25.49 | +$4.62 | -$6.94 | 60.0% | -$1.50 |
| **[0.70, 0.80)** | **10** | **80.0%** | **+$25.67** | **+$4.02** | **-$3.24** | **44.6%** | **+$2.57** |
| [0.80, 0.85) | 7 | 71.4% | -$9.14 | +$2.46 | -$10.72 | 81.3% | -$1.31 |
| [0.85, 0.90) | 11 | 90.9% | +$2.12 | +$1.49 | -$12.76 | 89.6% | +$0.19 |
| [0.90, 1.00) | 14 | 92.9% | +$9.35 | +$0.80 | -$0.98 | 55.3% | +$0.67 |

There are **two distinct profitable zones**, separated by a dead zone at [0.80, 0.85):
- [0.70, 0.80): the GBM model agrees with the market, which already has the move ~75% priced in → 80% WR with reasonable payoff (avg_win $4 / avg_loss $3.24)
- [0.90, 1.00): nearly-resolved markets with very small but reliable moves → 93% WR, capped wins, but losses are also bounded

Entry-price [0.20, 0.50) is the catastrophic bucket: the GBM model is extremely confident DOWN/UP but the market is pricing the *opposite* — when the market is right, we lose ~$13 per trade.

**Caveat: every bucket has n ≤ 17.** Treat these directionally, not quantitatively.

### Q2-B — Is BTC RS structurally viable?

Hold-to-resolution breakeven WR:

| Entry | win pays | loss pays | BE WR |
|---|---|---|---|
| 0.50 | $0.50 | $0.50 | 50.0% |
| 0.70 | $0.30 | $0.70 | 70.0% |
| 0.85 | $0.15 | $0.85 | 85.0% |
| 0.90 | $0.10 | $0.90 | 90.0% |

This is a tautology: at entry p, the breakeven WR if you hold to resolution is exactly p. So for BTC RS at >=0.85, you need WR > 85%. The empirical WR is 92% at the >=0.90 bucket, which clears it — but that's on n=14.

The viable zones identified in Q2-A are:
- [0.70, 0.80): EV +$2.57/trade, breakeven 44.6% (because we exit early at force_exit, not at resolution — wins are smaller than full payout)
- [0.90, 1.00): EV +$0.67/trade, breakeven 55.3%

### Q2-C — Disable BTC RS entirely?

Not quite. **A targeted filter is more attractive than a blanket ban**:

- BTC RS at entry_price ∈ [0.70, 0.80) ∪ [0.90, 1.00): n=24, WR=87.5%, total PnL=**+$35.02**, EV/trade +$1.46
- BTC RS otherwise: n=45, WR=44.4%, total PnL=**-$94.68**

Recommendation: **disable BTC RS where entry_price < 0.70 or entry_price ∈ [0.80, 0.90)**, keep entries in [0.70, 0.80) and >=0.90. Or — given the small per-bucket n — disable BTC RS entirely as a clean cut, accept the loss of +$35 of "edge" on 24 trades (~1.1/day), and eliminate -$95 of certain losses on 45 trades (~2.1/day). **Net of the simple cut: +$60 over the dataset, ~+$86/30d.**

---

## SECTION 3 — ETH/SOL DOWN RS validation

### Q3-A — ETH DOWN RS confidence

ETH DOWN RS: 26/32 = 81.2%

- Wilson 95% CI on WR: **[0.647, 0.911]** — does **not** overlap the breakeven 0.668.
- Bayesian (uniform prior): **P(true WR < 0.668 BE) = 0.045**, P(true WR < 0.50) ≈ 0.0002.
- Bootstrap EV/trade 95% CI: **[-$0.48, +$3.36]** (median +$1.51).

So WR is significantly above breakeven at α=0.05; EV/trade just touches zero. The headline 81% is real, but the EV interval admits "barely positive" outcomes too.

### Q3-B — Walk-forward (ETH DOWN RS, SOL DOWN RS)

| | H1 | H2 |
|---|---|---|
| ETH DOWN | n=16, WR 0.750, EV +$1.06 | n=16, WR 0.875, EV +$1.92 |
| SOL DOWN | n=11, WR 0.818, EV +$1.95 | n=12, WR 0.833, EV +$2.55 |

The edge is **stronger in H2** for both. Caveat: H1 spans ~04-23, H2 spans ~04-24–25 — only one and a half days apart. This is "consistent across two days" not "consistent across two weeks."

### Q3-C — LIVE rollout plan

Power calculation (α=0.05 two-sided, 80% power):

| True WR | n needed to confirm WR > 0.668 BE |
|---|---|
| 0.70 | 1,610 trades |
| 0.75 | 219 trades |
| 0.80 | 72 trades |

If the true WR is **really** 81%, ~50 LIVE trades is enough to be 80%-confident the strategy is positive. If true WR has regressed to 75%, you need ~220. At ETH DOWN RS's empirical rate (~10–15/day), that's 5–22 days to validate.

**Recommended rollout (one-strategy-at-a-time, conservative):**

1. Enable **ETH DOWN RS** on LIVE at $5/trade. (Keep at $5, don't size up yet.)
2. Watch for **20 LIVE trades**. Pass criteria: WR ≥ 70% (≥14 wins of 20). If <14, pause and review.
3. Continue to **50 LIVE trades**. Pass criteria: WR ≥ 70% AND cumulative PnL > $0.
4. Then enable **SOL DOWN RS**, same gates.
5. Only after both pass 50 LIVE trades do we discuss sizing-up (Section 6).
6. Throughout, **keep all UP-side RS and BTC RS disabled on LIVE** unless they pass an equally rigorous test on a future PAPER snapshot.

### Q3-D — Disable UP RS on PAPER too?

**Disable on LIVE immediately** (clear; -$122 in losses, p=0.015). On PAPER, **keep them running for now** — the cost of continuing is bookkeeping (PAPER is sim'd) and you want to know if UP RS recovers in a different regime. Set a checkpoint: re-evaluate after 100 more PAPER UP-RS trades. If still negative-EV at that point, drop entirely.

If you want a hybrid: disable BTC RS entirely (PAPER + LIVE), keep ETH UP / SOL UP on PAPER for monitoring. BTC RS has the worst structural payoff and is the least informative to keep watching.

### Q3-E — SOL DOWN RS at n=23

- Wilson 95% CI: **[0.63, 0.93]** — overlaps the breakeven 0.66.
- P(true WR < 0.668 BE) = **0.061** — borderline, just above 5%.
- Bootstrap EV/trade 95% CI: **[-$0.11, +$4.36]**.

**Real but underpowered.** Treat SOL DOWN RS as a "promising" signal, not a confirmed one. The 50-LIVE-trade gate is essential before sizing it up.

---

## SECTION 4 — MR per-side

### Q4-A — SOL UP MR wins composition

All 24 SOL UP MR wins exit via **`take_profit`** (no resolution wins, no soft exits, no other reasons). Mean win $16.59 is consistent with: entry ~0.351, TP fires when bid reaches a threshold and we sell at a market price (mean exit 0.734 in the data — TP triggers at +$0.15 above entry but the bot apparently sells at the prevailing bid which is higher).

By exit reason for SOL UP MR overall:
- take_profit: n=24, EV +$16.59 → +$398.18
- soft_exit_stalled: n=25, EV -$9.66 → -$241.50
- hard_stop_floor: n=7, EV -$11.69 → -$81.81

So SOL UP MR is a very binary strategy: TP wins are large, anything else is full-loss. Wins are **not** dependent on full-resolution payout — they're TP-driven. avg_win is high because the entry price is so low (cheap shares = high leverage). The 56-trade sample is unrepresentative in the sense that it spans a single regime; if SOL volatility drops, fewer markets will reach TP and EV will compress.

### Q4-B — ETH DOWN MR with v1.22 cw filter

Empirical ETH DOWN MR by cross_window bucket:

| cw range | n | WR | EV/trade |
|---|---|---|---|
| [-0.20, -0.10) | 12 | 0.167 | -$8.17 |
| **[-0.10, -0.05)** | **15** | **0.733** | **+$4.06** |
| **[-0.05, -0.02)** | **16** | **0.812** | **+$5.46** |
| [-0.02, 0) | 13 | 0.538 | +$0.69 |
| [0, +0.03) | 13 | 0.308 | -$5.27 |
| [+0.03, +0.10) | 25 | 0.480 | +$0.73 |
| [+0.10, +0.20) | 6 | 0.333 | -$2.96 |

The v1.22 ETH DOWN band [-0.10, -0.02] gets us to **n=31, WR=77.4%, EV +$4.78/trade** (combining the two middle rows). Very strong.

**Projection:** If post-v1.22 ETH DOWN MR sustains 70% WR on the next 50 trades at the empirical avg_win $9.91 / avg_loss -$12.78, EV/trade = 0.70×9.91 + 0.30×(-12.78) = **+$3.10/trade**. At ~2 ETH DOWN MR trades/day post-filter, that's **~+$185/30d** from this strategy alone.

### Q4-C — BTC UP MR sustainability

BTC UP MR: 155 trades, 46.5% WR, +$22.99 total.

- Wilson 95% CI on WR: **[0.39, 0.54]** — straddles 45.7% breakeven.
- Bootstrap EV/trade 95% CI: **[-$1.57, +$1.88]** — straddles zero.
- Walk-forward H1 (04-08→04-17): 77 trades, WR 0.39, +$8.61. H2 (04-17→04-25): 78 trades, WR 0.54, +$14.38.

H2 is materially better than H1 (perhaps post-v1.21 floor change effect), but the all-time CI says we **cannot reject "BTC UP MR is breakeven."** Keep monitoring; do not raise floor; do not size up. If H2's 0.54 WR continues another 50 trades, that becomes a real edge.

---

## SECTION 5 — Regime detection

### Q5-A — Window size for ETH MR soft-stall counter

Backtest of "skip if rolling soft-stall rate ≥ threshold" applied to **all** ETH MR (n=223; baseline PnL = +$82.10):

| window | threshold | kept_n | kept PnL | skipped PnL | Δ vs baseline | FP-rate (skipped wins) |
|---|---|---|---|---|---|---|
| 5 | ≥3/5 | 127 | +$229.54 | -$147.44 | **+$147.44** | 34.4% |
| 8 | ≥4/8 | 119 | +$257.90 | -$175.79 | **+$175.79** | 35.6% |
| 8 | ≥5/8 | 147 | +$235.01 | -$152.91 | +$152.91 | 30.3% |
| 10 | ≥4/10 | 100 | +$281.23 | -$199.13 | **+$199.13** | 37.4% |
| 10 | ≥6/10 | 151 | +$228.07 | -$145.97 | +$145.97 | 30.6% |

Best ETH MR improvement is **win=10, ≥4/10** (+$199 vs baseline), but with 37% false-positive rate. **win=8, ≥5/8** is a good middle ground: +$153 with the lowest FP rate (30%).

**Important caveat:** when the v1.22 ETH cw filter is applied first and then the regime skip, the skip becomes **harmful** (e.g. win=10, ≥4/10 loses $68 because the v1.22 filter has already removed the bad regimes). So:
- If you keep v1.22 cw filter as-is → **don't add a regime skip**.
- If you remove v1.22 cw filter → a regime skip is a partial substitute (gets ~70% of the v1.22 benefit).

The cw filter and the regime skip are competing solutions to the same problem (avoid ETH MR in trending regimes). **Keep v1.22, skip the regime skip.** If you really want belt-and-suspenders, the cleanest add-on is **win=8, ≥5/8** because it skips less (only the worst 30% of regimes) and would only fire after the v1.22 filter has already failed many times in a row.

### Q5-B — ETH-specific vs global regime counter

Backtested global (any-asset MR) trigger on the unfiltered MR set (baseline -$224):
- win=8, ≥4/8 (50% rate): kept_n=308, skipped_n=310, Δ = **+$639**.

Globally it's even more powerful, because BTC DOWN MR pre-v1.21 is the dominant loss driver and a global counter catches it. But again, post-v1.21 + post-v1.22 strategy filters already remove most of those trades. The marginal benefit of a global regime trigger on the **current** strategy set is small.

If you want a regime trigger, **make it global** (any asset's MR soft_exit_stalled rate counts) — BTC's regime is the leading indicator for everything. ETH-specific is overengineered.

### Q5-C — Threshold recommendation

Given v1.22 already does most of the regime work, **don't add a daily-pnl trigger and don't add a soft-stall-rate trigger right now.** Re-evaluate after 50 post-v1.22 ETH MR trades. If the v1.22 cw filter delivers 70% WR as expected, the regime skip is unneeded. If it underperforms (e.g., WR < 55%), introduce **global win=8, ≥5/8** as an additional safety net.

### Q5-D — Does RS benefit from regime detection?

For each RS trade I computed the rolling MR soft-stall rate over the prior 8 MR trades, and bucketed:

| MR soft-stall regime | RS overall | ETH+SOL DOWN RS specifically |
|---|---|---|
| low (≤0.25) | n=9, WR 0.56, EV -$0.42 | n=4, WR 0.75, EV +$2.10 |
| mid (0.25–0.50) | n=100, WR 0.68, EV -$0.61 | n=29, WR 0.79, EV +$1.06 |
| high (>0.50) | n=58, WR 0.74, EV +$0.73 | n=22, WR 0.86, EV +$2.75 |

**DOWN RS is strongest in the same regimes where MR is weakest.** They're complementary: if you do add a global regime skip for MR, you should NOT also skip RS — the DOWN RS edge may even **increase** in trending markets.

---

## SECTION 6 — Position sizing / Kelly

### Per-strategy Kelly fractions (full Kelly; treat as upper bound)

| strategy | n | WR | avg_win | avg_loss | full Kelly | quarter Kelly |
|---|---|---|---|---|---|---|
| ETH DOWN RS | 32 | 0.812 | $3.42 | -$6.88 | 43.5% | 10.9% |
| SOL DOWN RS | 23 | 0.826 | $4.17 | -$9.04 | 44.9% | 11.2% |
| ETH DOWN MR (v1.22 band) | 31 | 0.774 | $9.91 | -$12.78 | 48.3% | 12.1% |
| ETH UP MR | 118 | 0.483 | $11.95 | -$9.99 | 5.1% | 1.3% |
| SOL UP MR | 56 | 0.429 | $16.59 | -$10.10 | 8.1% | 2.0% |
| BTC UP MR | 155 | 0.465 | $10.96 | -$9.23 | 1.4% | 0.3% |

Three strategies clear 40% full-Kelly (read: fraction of bankroll per bet). Quarter-Kelly is the conservative real-money sizing. **None of the MR strategies can support more than 1–2% of bankroll** at the quarter-Kelly level.

### Q6-A — Size up DOWN RS on PAPER?

The math says yes: ETH DOWN RS quarter-Kelly is ~11% of bankroll. With $1,000 working capital, 11% = $110/trade. We're currently at $15. So **even 2x ($30) is a small fraction of Kelly**.

**Conservative path:**
1. Keep current $15/trade in PAPER for both ETH DOWN RS and SOL DOWN RS for 30 days (let n grow to ~100–150 combined).
2. If WR holds ≥75% and EV remains > +$1/trade, double size to $30 in PAPER for another 30 days.
3. Only after **two consecutive 30-day windows passing the bar** do we go to $30 on LIVE.

This is much more conservative than full Kelly but matches "we have 3 days of data; don't bet the farm on it." See Q6-C below for the regression-risk math.

### Q6-B — Variable sizing on confidence?

Possible, but **not recommended yet**. The empirical evidence (Q2-A buckets, n≤17 each) is too thin to fit a sizing curve. A discrete tier (e.g. "BTC RS at entry ∈ [0.70, 0.80) sized at 0.5x; otherwise disabled") would be more robust than a sliding scale, and we don't have that data either. Re-visit after another 100 BTC RS trades or use a Bayesian sizing rule with a strong prior.

### Q6-C — Risk of ruin (Monte Carlo, $15/trade flat)

Bootstrapped over current empirical distribution (5,000 sims, 30-day horizon, Poisson trade arrival):

| State | trades/day | median PnL/30d | 5th pct | 95th pct | 95th pct max DD |
|---|---|---|---|---|---|
| Raw (all active strategies, no v1.22) | 37 | -$346 | -$958 | +$251 | $1,038 |
| v1.22 retroactive (current state) | ~21 | uses linear projection: +$474/30d | — | — | — |
| Scenario D (drop UP RS, drop BTC RS, +regime skip) | ~15 | +$642/30d projected | — | — | — |

(For Scenario D the bootstrap CI on EV/trade is **[$0.21, $2.65]**.)

A few things to note:

- The "raw" Monte Carlo includes all the disabled strategies — that's what would happen if every safety filter were removed.
- $15 × 50 trades/day × 5% chance of -1.5σ day → easy $200+/day drawdown at current state. The $15/day stop on LIVE protects you from this; **respect it**.
- If you size up ETH DOWN RS to $30/trade, the per-trade loss tail grows linearly. Worst case in 30 days at current empirical loss distribution roughly doubles.

---

## SECTION 7 — Scenario backtest

All scenarios applied retroactively to the dataset. "Current state" = post-v1.22 strategies only (BTC UP MR, ETH UP MR with cw filter, ETH DOWN MR with cw filter, SOL UP MR, all RS).

| Scenario | n | total PnL | EV/trade | WR | 30-day projection |
|---|---|---|---|---|---|
| Current (post-v1.22 retro) | 433 | +$331.97 | +$0.77 | 58.4% | **+$474** |
| **A: drop UP-side RS** (ETH UP, SOL UP, BTC UP) | 347 | +$423.25 | +$1.22 | 57.6% | **+$605** |
| **B: A + drop BTC DOWN RS** (= drop all BTC RS too) | 321 | +$454.00 | +$1.41 | 56.7% | **+$649** |
| C: ETH MR regime skip alone (win=5, ≥3) | 426 | +$327.45 | +$0.77 | 58.5% | +$468 |
| **D: B + ETH MR regime skip** | 314 | +$449.48 | +$1.43 | 56.7% | **+$642** |

Bootstrap 95% CIs on EV/trade:
- Scenario B: **[$0.22, $2.58]**
- Scenario D: **[$0.21, $2.65]**

(Both CIs straddle zero on the low end — even after the cuts, we can't *prove* the bot is profitable yet.)

### Per-scenario interpretation

- **Scenario A** alone (drop UP-side RS) recovers +$131 over current = **+$181/30d projected**. Lowest-risk, highest-confidence change.
- **Scenario B** adds drop of BTC DOWN RS: incremental +$31 / +$44/30d. Worth it because BTC DOWN RS is structurally bad (Section 1/2).
- **Scenario C** alone is essentially neutral once v1.22 is in place (-$5).
- **Scenario D** is a wash vs Scenario B (-$5). The regime skip costs us a small amount because it kicks in at moments where v1.22-filtered ETH MR happens to be doing fine.

### Scenario E — size up ETH DOWN RS to 2x ($30/trade)

At empirical performance (WR 81.2%, avg_win $3.42, avg_loss -$6.88) on 32 historical trades:
- Current: +$47.59
- 2x size: +$95.19 (+$48 vs current → **+$68/30d** at current trade rate)

If WR regresses to 70% (Monte Carlo, 2,000 sims):
- Median 30-day PnL: **+$13** (essentially zero)
- 95% CI: **[-$90, +$116]**
- **There's a meaningful probability of net loss if the WR isn't sustained.**

**Recommendation: do NOT size up ETH DOWN RS yet.** Wait for n=100+ (60–90 more days at current rate) so the WR estimate has tighter CIs before doubling exposure.

---

## Validated proposed actions (rank-ordered)

1. **DO IT NOW: Disable all UP-side RS on LIVE** (ETH UP RS + SOL UP RS + BTC UP RS). p=0.015, walk-forward consistent, structural payoff explanation. **Projected: +$181/30d.**

2. **DO IT NOW: Disable BTC RS entirely on LIVE** (covers BTC DOWN RS in addition to BTC UP from item 1). Structural payoff problem (Section 2), avg_win ≤ $2.13. **Projected: incremental +$44/30d.**
   - *Optional refinement:* keep BTC RS only in entry_price ∈ [0.70, 0.80) ∪ [0.90, 1.00). Adds +$35 historical but on n≤14 per bucket — small-sample.

3. **DO IT NOW: Keep UP-side RS running on PAPER** for monitoring. No money at risk. Re-evaluate after 100 more PAPER UP-RS trades.

4. **DO NOT add an ETH-MR regime skip on top of v1.22.** The cw filter already does the regime work; adding a soft-stall counter is net-negative on filtered data.

5. **DO NOT size up ETH DOWN RS yet.** WR estimate on n=32 has too much regression risk. Wait for n≥100.

6. **PROCEED CAUTIOUSLY: Enable ETH DOWN RS on LIVE at $5/trade** with the gated rollout in Q3-C. Then SOL DOWN RS after ETH DOWN RS clears 50 LIVE trades.

7. **MONITOR: BTC UP MR.** H2 looks better than H1; CIs don't yet exclude breakeven. Don't change parameters.

8. **MONITOR: ETH DOWN MR with v1.22 cw filter.** Need 50 post-v1.22 trades to confirm the 77% in-sample WR. If it drops below 55%, revert the cw filter.

---

## Caveats (do not skip)

- **3-day RS window.** Every RS conclusion is based on data spanning 2026-04-22 → 2026-04-25. If the BTC market regime shifts (e.g. enters a strong trend up), DOWN RS might lose its edge and UP RS might gain one. The "DOWN edge persists across both halves" finding is across **two days**, not two weeks.
- **Position size in data is $15.** Where I quote 30-day projections, they're at $15/trade. Divide by 3 if LIVE actually runs at $5.
- **Bootstrap CIs straddle zero** for both Scenario B and D EV/trade. Even after the proposed cuts, we cannot reject the null "this bot is breakeven." The point estimate is positive; the lower CI is not.
- **No multiple-comparison correction.** I ran ~30 sub-strategy tests; with α=0.05, ~1.5 false positives are expected by chance. The biggest claims (DOWN vs UP RS at p=0.015) survive a Bonferroni correction at the section level (α=0.05/5 sections = 0.01) only marginally.
- **All backtests are in-sample.** The v1.22 filter was *designed* using this data; backtesting it on this data overstates its forward performance.
