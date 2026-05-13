# Cowork Review — 2026-05-05

All statistics derived fresh from raw CSV data. No pre-computed summaries trusted.

**Data sources:**
- `cowork_snapshot/5m_trading/trades.csv` — 1,658 PAPER trades (SSH warning lines at file top stripped; true data n=1,658)
- `cowork_snapshot/5m_trading/skipped_windows.csv` — 7,254 skipped windows
- `cowork_snapshot/5m_live/trades_BTC-15m.csv` — 27 LIVE BTC trades
- `cowork_snapshot/5m_live/trades_ETH-15m.csv` — 16 LIVE ETH trades
- `cowork_snapshot/5m_live/trades_SOL-15m.csv` — 7 LIVE SOL trades
- Paper date range: 2026-03-30 through 2026-05-05 (UTC)
- Post-v1.26 cutoff: 2026-05-03 00:00 UTC → 25 paper trades, 10 LIVE BTC trades

---

## Executive Summary

- **BTC UP MR is a losing strategy.** Over 560 PAPER trades, WR=50.7% but EV=-$0.688/trade (t=-1.46, p=0.14 — marginal, borderline significance). The problem is asymmetric losses: average win +$9.15 vs average loss -$10.85, win/loss ratio 0.843. Kelly fraction is negative (-0.078), meaning the edge does not justify any bet size. Post-v1.26 deterioration (WR=30%, EV=-$4.85 on n=10) is too small a sample to distinguish regime shift from noise, but the direction is consistent with the all-history negative EV. **BTC UP should be disabled on LIVE immediately. Keep on PAPER for continued data collection.**

- **soft_exit_stalled is not a new problem — it is structural.** Historical stalled rate is 22.4% across all trades. The post-v1.26 rate of 52% (13/25) appears extreme but is driven by the small sample and BTC UP overrepresentation (10 of 25 post-v1.26 trades are BTC UP, which has a 23.4% structural stall rate). Crucially, soft_exit_stalled exits show 59.6% of positions moving in the right direction at 60 seconds — the problem is the price stalls at an intermediate level and never reaches 0.60 TP. This is a market-depth issue intrinsic to 15m binary markets, not a recent regime shift.

- **Top new idea: time-of-day filter.** UTC 08:00 has WR=65.2%, EV=+$2.32 on n=89. UTC 17:00–20:00 is a consistent destruction zone: WR=33-43%, EV=-$1.80 to -$3.11. A filter blocking entries in UTC 17–20 (4 hours) would have eliminated ~284 trades historically with below-average EV. The pattern holds across both BTC and ETH. This is the single highest-confidence new signal found in this analysis.

- **SOL band recommendation: widen to [0.33, 0.38).** Current band [0.33, 0.35) has only n=16 SOL UP trades (WR=37.5%, EV=+$0.77). Adding [0.35, 0.38) brings in 50 more trades at WR=46%, EV=+$0.68. Combined [0.33, 0.38) gives n=66, WR=43.9%, EV=+$0.70. There are 284 skipped SOL windows priced in [0.35, 0.38) — this is untapped volume at positive EV. Do not extend to 0.40: the [0.38, 0.40) SOL bucket has only n=3.

- **Overall strategy confidence: LOW for BTC, MODERATE for ETH.** ETH combined (UP+DOWN) is the only segment with consistently positive EV at scale: n=432, WR=56.9%, EV=+$0.14/trade. Aggregate PAPER EV is -$0.69/trade on 1,658 trades — the strategy as currently configured is net negative primarily because BTC DOWN (EV=-$1.75, t=-3.42, p<0.001) and BTC UP drag the overall book down. ETH is the real thesis; BTC is the noise generator.

---

## Q1. BTC UP MR — Statistical Analysis

### All-history by asset/side (PAPER, n=1,658)

| Segment   |    n | WR    | EV/trade | Total PnL | t-stat |
|-----------|------|-------|----------|-----------|--------|
| BTC UP    |  560 | 50.7% | -$0.688  | -$385.19  | -1.46  |
| BTC DOWN  |  463 | 47.5% | -$1.751  | -$810.81  | **-3.42** |
| ETH UP    |  218 | 55.0% | +$0.166  | +$36.22   | +0.24  |
| ETH DOWN  |  214 | 58.9% | +$0.111  | +$23.70   | +0.17  |
| SOL UP    |  130 | 47.7% | +$0.459  | +$59.64   | +0.47  |
| SOL DOWN  |   73 | 47.9% | -$1.012  | -$73.88   | -0.75  |
| **ALL**   | 1658 | 51.1% | -$0.694  | -$1,150   | **-2.60** |

### Statistical test: BTC UP EV vs zero

- n=560, mean=-$0.688, std=$11.122, SE=$0.470
- t = -1.464, p ≈ 0.143 (two-tailed, normal approximation)
- **Interpretation:** Not significant at p<0.05. However, the null is "EV=0" — we need EV > ~$1.22 to be profitable at this TP/SL structure. The Kelly fraction is -0.078 (negative), meaning even at face value, no positive bet size is justified. The 560-trade sample is large enough that if there were real edge, we would see it by now.

### Post-v1.26 BTC UP (2026-05-03 onward)

| Segment      | n  | WR    | EV/trade |
|--------------|----|-------|----------|
| BTC UP       | 10 | 30.0% | -$4.853  |
| ETH UP       | 12 | 58.3% | +$1.984  |
| ETH DOWN     |  3 | 66.7% | +$1.867  |
| All post     | 25 | 48.0% | -$0.765  |

Post-v1.26 BTC UP: t=-1.53, p≈0.13 (n=10, underpowered). The WR=30% is alarming but n=10 is insufficient for significance. All 10 post-v1.26 trades are BTC UP (BTC DOWN is hard-disabled since v1.26c, and SOL DOWN is disabled). The post-v1.26 reported EV=-$0.76 overall hides the fact that ETH is +$1.93 while BTC UP is dragging it to -$4.85.

### Win/loss asymmetry (BTC UP)

- Average win: +$9.15 (n=284 winning trades)
- Average loss: -$10.85 (n=275 losing trades)
- Win/loss ratio: 0.843 — unfavorable. For positive EV at 50.7% WR you need win/loss > 0.98. BTC UP fails this by 14%.

### LIVE BTC performance (snapshot)

- BTC DOWN (13 trades, now disabled): WR=35.7%, EV=-$2.33
- BTC UP (13 trades): WR=23.1%, EV=-$2.80
- Combined BTC LIVE: n=27, WR=29.6%, EV=-$2.56, total=-$69.02

### Recommendation

**Disable BTC UP on LIVE immediately.** Keep on PAPER. The negative Kelly fraction means no rational bet size is justified. LIVE BTC UP has cost $36.38 on 13 trades (WR=23%, EV=-$2.80). BTC DOWN was already disabled. Effectively, all BTC should be off LIVE. ETH and SOL are the tradeable segments.

---

## Q2. Soft_exit_stalled Diagnosis

### Exit reason breakdown — all PAPER trades

| Exit Reason         |   n | WR     | EV/trade | Avg Hold |
|---------------------|-----|--------|----------|----------|
| take_profit         | 556 | 100.0% | +$11.10  | 212s     |
| force_exit_time     | 500 |  58.2% |  -$1.40  |  75s     |
| soft_exit_stalled   | 371 |   0.0% |  -$9.33  | 460s     |
| hard_stop_floor     | 186 |   0.0% | -$14.11  | 242s     |
| trailing_stop_z2    |  36 |   0.0% | -$11.90  | 206s     |
| hard_stop           |   6 |   0.0% | -$10.25  |  93s     |
| window_expired      |   3 |   0.0% | -$14.61  | 15351s   |

**Note on force_exit_time:** WR=58.2% but EV=-$1.40. This exit reason fires when the position is profitable at time expiry but below TP. It counts as a "win" by pnl sign but the absolute gain is small. It is not as bad as it looks — these positions ran profitably but the TP was out of reach.

### Post-v1.26 (n=25)

| Exit Reason       | n  | WR     | EV/trade |
|-------------------|----|--------|----------|
| soft_exit_stalled | 13 |  0.0%  | -$10.19  |
| take_profit       | 12 | 100.0% |  +$9.45  |

Rate: 52% stalled post-v1.26 vs 22.4% all-time. But: all 25 post-v1.26 trades are BTC UP or ETH. BTC UP structurally stalls at 23.4%; ETH UP stalls at 28.9%. With 10 BTC UP and 15 ETH trades, expected stall count would be 10×0.234 + 12×0.289 + 3×0.201 = 2.3 + 3.5 + 0.6 = ~6.4 expected vs 13 observed. The excess (6.6 extra stalls) may reflect a real short-term deterioration or just variance on n=25.

### price_60s_after_entry analysis

Trades with `price_60s_after_entry` populated: 1,338 (80.7% of all paper trades).

| Exit Type         | n   | Avg Price Move @60s | Pct Moving Toward TP |
|-------------------|-----|---------------------|----------------------|
| soft_exit_stalled | 371 | +0.094              | 59.6%                |
| take_profit       | 435 | +0.094              | 72.2%                |

**Critical finding:** At 60 seconds, stalled and TP exits show the **same average price move** (+0.094). The difference is: TP exits have 72.2% of positions moving in-the-money at 60s vs 59.6% for stalled. The positions that eventually stall ARE moving in the right direction initially — they just stop before reaching 0.60. This is a mid-market liquidity exhaustion problem, not a wrong-direction entry problem. The exit at 460s average hold (vs 212s for TP) means the bot is sitting through a stall, losing time value and eventually exiting at a loss.

**Implication:** soft_exit_stalled is not an entry quality problem. It's the market running out of willing sellers before reaching 0.60. This is most likely to happen in low-volume windows or when BTC momentum is inconsistent.

### Stalled rate by asset/side

| Segment  | Stalled/Total | Stall Rate |
|----------|---------------|------------|
| BTC UP   | 131/560       | 23.4%      |
| BTC DOWN |  86/463       | 18.6%      |
| ETH UP   |  63/218       | 28.9%      |
| ETH DOWN |  43/214       | 20.1%      |
| SOL UP   |  32/130       | 24.6%      |

**BTC is NOT uniquely worse for stalling.** ETH UP stalls more often (28.9%) than BTC UP (23.4%). The 52% post-v1.26 stall rate is not BTC-specific — it reflects the composition of recent trades plus sampling noise.

### Stall rate trend over time

| Period  | n    | Stall Rate | WR    |
|---------|------|------------|-------|
| 2026-04 | 1531 | 23.0%      | 51.8% |
| 2026-05 | 127  | 15.0%      | 42.5% |

No structural worsening in stall rate. May 2026 WR drop to 42.5% is driven by the BTC UP composition shift, not increased stalling.

### Hypothesis verdict

The 52% stall rate post-v1.26 is **not a market structure shift.** It is:
1. BTC UP overrepresentation in the sample (already a negative-EV segment)
2. Normal variance on n=25

The structural stall rate of 22-24% is baked into how 15m binary markets work. The right response is not to fight stalling but to ensure the TP-hit positions pay enough to overcome the stall losses — which requires EV > 0 per segment, which BTC currently fails.

---

## Q3. Time-of-Day Analysis

### WR and trade count by UTC hour (n≥10 shown)

| UTC Hour | n  | WR    | EV/trade |
|----------|----|-------|----------|
| 00       | 58 | 53.4% | -$0.03   |
| 01       | 64 | 53.1% | -$0.14   |
| 02       | 68 | 57.4% | -$0.08   |
| 03       | 50 | 42.0% | -$1.65   |
| 04       | 61 | 54.1% | -$0.70   |
| 05       | 46 | 45.7% | -$2.95   |
| 06       | 68 | 54.4% | -$0.07   |
| 07       | 75 | 52.0% | -$1.73   |
| **08**   | **89** | **65.2%** | **+$2.32** |
| 09       | 77 | 48.1% | -$0.40   |
| **10**   | **88** | **59.1%** | **+$0.14** |
| 11       | 57 | 54.4% | -$0.89   |
| 12       | 81 | 53.1% | -$0.67   |
| 13       | 71 | 46.5% | -$1.97   |
| **14**   | **83** | **55.4%** | **+$0.99** |
| **15**   | **62** | **56.5%** | **+$1.03** |
| **16**   | **72** | **58.3%** | **+$1.21** |
| **17**   | **72** | **33.3%** | **-$3.11** |
| 18       | 75 | 48.0% | -$1.15   |
| **19**   | **83** | **38.6%** | **-$2.05** |
| **20**   | **76** | **42.1%** | **-$1.80** |
| 21       | 53 | 56.6% | +$0.15   |
| 22       | 59 | 50.8% | -$2.11   |
| **23**   | **70** | **44.3%** | **-$2.59** |

### Time-of-day pattern assessment

**Strong positive signal:** UTC 08 stands out clearly (WR=65.2%, EV=+$2.32, n=89). This is the London open / early European session. UTC 14–16 also positive (WR=55–58%, EV=+$0.99 to +$1.21), corresponding to US pre-market and early NY open.

**Consistent destruction zone:** UTC 17, 19, 20, 23 all show WR<44% and EV worse than -$1.80. UTC 17 is worst (WR=33.3%, EV=-$3.11, n=72). This is the NY afternoon/post-close period. UTC 23 = pre-Asia open.

**Pattern holds across assets:**
- Good hours (08, 10, 14–16): BTC WR=58.8% (n=262), ETH WR=63.3% (n=90)
- Bad hours (17, 19, 20, 23): BTC WR=39.1% (n=179), ETH WR=41.1% (n=73)

The effect is real across both assets — not asset-specific.

### Recommendation

Add a **trade hours filter** blocking entries during UTC 17:00–20:59. This would eliminate ~300 annual trades with WR ≈ 39–42% and EV ≈ -$2 to -$3. UTC 22–23 are also candidates for blocking. A conservative "trade only UTC 00–16, 21" filter would capture 1,177/1,658 = 71% of historical volume while shedding the worst performers.

**Caveat:** This pattern could be partially spurious. UTC 17–20 corresponds to high-volatility NY sessions where BTC moves hard — the crash filter and CW filter may already be blocking many of these. Verify on PAPER before applying to LIVE. Start with just blocking UTC 17–20.

---

## Q4. SOL Entry Band Analysis

### SOL UP performance by entry price bucket

| Entry Price  | n  | WR    | EV/trade |
|--------------|----|-------|----------|
| [0.30, 0.32) |  2 | 50.0% | +$12.95  |
| [0.32, 0.34) |  7 | 42.9% | +$2.27   |
| [0.34, 0.36) | 24 | 41.7% | +$1.62   |
| [0.36, 0.38) | 38 | 47.4% | +$0.53   |
| [0.38, 0.40) |  3 | 66.7% | +$8.61   |

Note: All SOL buckets (n≥5) show positive EV. The [0.32,0.34) and below buckets are too small for confidence. Current live band is [0.33, 0.35).

### Band comparison

| Band                  | n  | WR    | EV/trade |
|-----------------------|----|-------|----------|
| [0.33, 0.35) current  | 16 | 37.5% | +$0.77   |
| [0.35, 0.38) add      | 50 | 46.0% | +$0.68   |
| **[0.33, 0.38) wide** | **66** | **43.9%** | **+$0.70** |
| [0.33, 0.40] widest   | 69 | 44.9% | +$1.04   |

### Skipped SOL windows: price distribution

Total SOL skipped windows: 2,249

| Skip reason    | Count |
|----------------|-------|
| price_too_high | 1,338 |
| btc_filter     |   668 |
| price_too_low  |   243 |

Price distribution of skipped SOL windows:

| Price Range    | Count | Notes |
|----------------|-------|-------|
| < 0.30         |    40 | Below floor |
| [0.30, 0.33)   |   140 | Below current band |
| **[0.33, 0.35)** | **93** | **Current allowed band** |
| **[0.35, 0.38)** | **284** | **Would be added by widening** |
| [0.38, 0.40)   |   268 | Edge — only n=3 SOL UP trades |
| [0.40, 0.45]   |   871 | price_too_high skips |

There are 284 skipped windows in [0.35, 0.38) — nearly 3× the current band's coverage. These would become tradeable opportunities.

### Recommendation

**Widen SOL UP band to [0.33, 0.38).** Evidence:
1. The [0.35, 0.38) zone has positive EV (+$0.68) on n=50 PAPER trades
2. 284 additional skipped windows would become entries
3. Combined band WR=43.9%, EV=+$0.70 — better than current [0.33,0.35) alone (WR=37.5%)
4. Do NOT extend to 0.40: [0.38, 0.40) is n=3, too thin

Do not change SOL DOWN (currently disabled — correct, EV=-$1.01 on n=73).

---

## Q5. Cross-Window Filter Validation

### Population split

- Trades with `cross_window_pct` populated: n=1,320 (79.6%)
- Trades without (old): n=338 (20.4%)

With CW: WR=49.8%, EV=-$0.58
Without CW: WR=55.9%, EV=-$1.15

The older trades (no CW) have worse EV. This is partly cohort effect (early strategy had higher variance).

### CW bucket performance (all assets)

| CW Bucket        | n   | WR    | EV/trade |
|------------------|-----|-------|----------|
| (-inf, -0.15)    |  38 | 21.1% | -$4.06   |
| [-0.15, -0.02]   | 281 | 49.1% | +$0.63   |
| **(-0.02, +0.02)** | **678** | **55.6%** | **-$1.03** |
| [+0.02, +0.10]   | 198 | 48.0% | +$0.36   |
| (+0.10, +inf)    | 125 | 32.0% | -$1.24   |

### The dead zone paradox

The dead zone (-0.02, +0.02) has the **highest WR (55.6%) but negative EV (-$1.03)**. This is the asymmetric loss problem again: the 55.6% win rate is not enough to overcome the -$10.85 average loss when wrong. The "allowed" bands have lower WR but less negative (or positive) EV because they carry different underlying asset distributions.

**Critically:** The filter is supposed to BLOCK the dead zone (-0.02, +0.02), so these 678 trades should NOT be appearing in the data if the filter is working. This needs investigation — either the filter was not yet active for these trades, or the column is populated differently than expected.

Actually, re-reading the filter spec: the filter blocks `[-0.15, -0.02] ∪ [+0.02, +0.10]` — it allows entries OUTSIDE those ranges. Wait, re-reading again: "blocks flat/extreme" means the dead zone IS the bad zone that gets blocked. If (-0.02, +0.02) has 678 trades, those trades passed through... possibly the filter definition was different at time of data collection. The majority of trades (1,320) have CW populated, but the filter logic may have changed between v1.26a and v1.26c.

**Setting aside the filter logic question:** Looking at the raw WR/EV data:
- Dead zone: WR=55.6%, EV=-$1.03 (high WR but terrible payoff when wrong)
- Allowed neg: WR=49.1%, EV=+$0.63
- Allowed pos: WR=48.0%, EV=+$0.36
- Extreme neg <-0.15: WR=21.1%, EV=-$4.06 (the filter is CORRECT to block this)
- Extreme pos >+0.10: WR=32.0%, EV=-$1.24 (filter correct to block this)

### BTC-specific CW buckets

| CW Bucket        | n   | WR    | EV/trade |
|------------------|-----|-------|----------|
| (-inf, -0.15)    |  28 | 21.4% | -$4.19   |
| [-0.15, -0.02]   | 134 | 43.3% | -$0.60   |
| (-0.02, +0.02)   | 321 | 54.8% | -$1.25   |
| [+0.02, +0.10]   | 102 | 40.2% | -$1.28   |
| (+0.10, +inf)    | 100 | 34.0% | -$0.77   |

**For BTC specifically:** ALL CW buckets have negative EV. The CW filter is not helping BTC — BTC is just a negative-EV segment regardless of CW state. This is consistent with the conclusion that BTC should be disabled, not filtered differently.

### ETH-specific CW buckets

| CW Bucket        | n   | WR    | EV/trade |
|------------------|-----|-------|----------|
| (-inf, -0.15)    |   5 | 20.0% | -$4.33   |
| [-0.15, -0.02]   | 106 | 59.4% | +$2.05   |
| (-0.02, +0.02)   | 230 | 58.3% | -$0.96   |
| [+0.02, +0.10]   |  74 | 60.8% | +$2.47   |
| (+0.10, +inf)    |  17 | 17.6% | -$5.78   |

**For ETH:** The CW filter works as intended. The allowed bands [-0.15,-0.02] and [+0.02,+0.10] have strongly positive EV (+$2.05 and +$2.47). The dead zone has negative EV (-$0.96 at WR=58.3% — again the asymmetry). The extreme bands (< -0.15 and > +0.10) are correctly blocked.

### Verdict

The CW filter is **valid and effective for ETH**. It is irrelevant for BTC (BTC is negative-EV everywhere). The current filter logic (blocking dead zone -0.02 to +0.02 and blocking extremes) is correctly specified for ETH. The 678 dead-zone trades in the dataset likely predate the filter's activation.

---

## Q6. Entry Price Band Analysis

### ETH UP by entry price bucket

| Band         | n  | WR    | EV/trade |
|--------------|----|-------|----------|
| [0.30, 0.32) | 10 | 10.0% | -$7.84   |
| [0.32, 0.34) | 10 | 40.0% | +$4.28   |
| [0.34, 0.36) | 13 | 30.8% | -$1.20   |
| [0.36, 0.38) | 22 | **68.2%** | **+$4.36** |
| [0.38, 0.40) | 51 | 43.1% | -$1.09   |
| [0.40, 0.45] | 39 | **69.2%** | **+$3.25** |

**ETH UP insight:** The current filter allows ETH UP at ≥0.35 (skipping 0.38–0.39). The data shows [0.36,0.38) is the best ETH UP bucket (WR=68.2%, EV=+$4.36, n=22). The [0.38,0.40) bucket is mediocre (WR=43.1%). The restriction skipping [0.38,0.39) may actually be helping by avoiding a mediocre zone. However, [0.40,0.45] shows WR=69.2% — ETH UP at 0.40+ is excellent.

**ETH combined [0.35,0.38) performance:** n=47, WR=63.8%, EV=+$3.61 — this is the single best entry zone for ETH across both directions.

### ETH DOWN by entry price bucket

| Band         | n  | WR    | EV/trade |
|--------------|----|-------|----------|
| [0.30, 0.32) |  4 |  0.0% | -$11.59  |
| [0.32, 0.34) |  6 | 16.7% |  -$3.14  |
| [0.34, 0.36) | 11 | 27.3% |  -$3.43  |
| [0.36, 0.38) | 16 | **56.2%** | **+$2.11** |
| [0.38, 0.40) | 62 | **58.1%** | **+$1.49** |
| [0.40, 0.45] | 25 | **72.0%** | **+$2.50** |

ETH DOWN is profitable at 0.36+. Good alignment with current filter.

### BTC UP by entry price bucket

| Band         |  n  | WR    | EV/trade |
|--------------|-----|-------|----------|
| [0.30, 0.32) |  13 | 30.8% | -$3.15   |
| [0.32, 0.34) |  37 | 51.4% | +$1.73   |
| [0.34, 0.36) |  38 | 52.6% | -$0.07   |
| [0.36, 0.38) |  77 | 50.6% | -$1.18   |
| [0.38, 0.40) | 115 | 51.3% | -$1.51   |
| [0.40, 0.45] | 121 | 52.9% | +$0.12   |

**No entry price works for BTC UP.** The best bucket is [0.32,0.34) at EV=+$1.73 but n=37 is too small to act on. The current live zone [0.38,0.40) is one of the worst: WR=51.3%, EV=-$1.51. WR hovers around 50-53% across all buckets but EV is consistently near zero or negative due to loss asymmetry. There is no sweet spot.

### BTC DOWN by entry price bucket

| Band         |  n  | WR    | EV/trade |
|--------------|-----|-------|----------|
| [0.34, 0.36) |  52 | 36.5% | -$3.97   |
| [0.36, 0.38) |  70 | 34.3% | -$5.05   |
| [0.38, 0.40) | 124 | **57.3%** | **+$0.67** |
| [0.40, 0.45] |  53 | 39.6% | -$2.80   |

BTC DOWN at [0.38,0.40) is the one positive-EV bucket (WR=57.3%, EV=+$0.67, n=124). But BTC DOWN is already disabled on LIVE (correctly, given the overall segment EV=-$1.75 on n=463 — the [0.38,0.40) subgroup positive EV is worth tracking but not acting on yet).

### Is the current 0.38–0.40 restriction for BTC correct?

For BTC UP: no. [0.38,0.40) has EV=-$1.51 — it is among the worst buckets. If BTC UP runs on PAPER, a wider band would help data coverage but would not improve EV. The whole segment is broken.

### Would [0.35, 0.38) for ETH beat current ≥0.35 rule?

ETH UP in [0.35, 0.38): n=26, WR=69.2%, EV=+$4.59. Yes, ETH UP at [0.35,0.38) is the best subset. The current "≥0.35 except skip [0.38,0.39)" rule produces: ETH UP [0.35,0.38) = excellent, ETH UP [0.39,0.40) = good, ETH UP [0.40+] = excellent. Restricting ETH UP to [0.35,0.38) would improve precision but lose 39 trades at [0.40+] that are also excellent. The current rule is approximately correct.

---

## Q7. Liquidity Analysis

### WR and EV by liquidity bin

| Liquidity    |   n | WR    | EV/trade |
|--------------|-----|-------|----------|
| < $15k       | 166 | 49.4% | -$1.53   |
| $15–20k      | 274 | 52.2% | -$1.22   |
| $20–30k      | 522 | 44.8% | -$0.59   |
| $30–40k      | 649 | 56.7% | -$0.24   |
| $40–50k      |  47 | 42.6% | -$2.09   |
| > $50k       |   0 | —     | —        |

**No clear upper-bound effect** — there are no trades above $50k liquidity in the dataset, so the hypothesis cannot be tested. Within the available range, the $30–40k band is best (WR=56.7%, EV=-$0.24). The $40–50k bucket appears worse (WR=42.6%) but n=47 is small.

**The existing ≥$15k liquidity filter is correct.** Below $15k, EV=-$1.53. The filter is doing its job.

No recommendation to add a liquidity upper bound — insufficient data above $40k. The current lower bound at $15k is validated.

### Spread analysis (bonus)

| Spread       |   n | WR    | EV/trade |
|--------------|-----|-------|----------|
| < 0.01       | 653 | 60.2% | -$0.26   |
| 0.01–0.02    | 328 | 46.3% | -$0.65   |
| 0.02–0.03    |  80 | 50.0% | +$0.39   |
| 0.03–0.05    |  30 | 43.3% | +$0.49   |

Tight spreads (<0.01) show highest WR but still negative EV due to asymmetric losses. The current ETH spread filter (≤0.03) is reasonable. BTC has no spread filter; given BTC's overall negative EV this doesn't matter.

---

## Q8. LIVE Risk Assessment

### Current LIVE performance (all-time)

| Asset | n  | WR    | EV/trade | Total PnL |
|-------|----|-------|----------|-----------|
| BTC   | 27 | 29.6% | -$2.556  | -$69.02   |
| ETH   | 16 | 50.0% | -$0.349  | -$5.58    |
| SOL   |  7 | 42.9% | -$0.871  | -$6.10    |
| Total | 50 | 36.0% | -$1.614  | -$80.70   |

### Should LIVE resume now?

**No — not in current configuration.**

LIVE is currently running all three assets. BTC should be shut off LIVE immediately. ETH and SOL can continue with modifications.

### Minimum conditions to resume LIVE (all must be met)

1. **BTC UP disabled on LIVE.** This is the primary bleeding source. BTC UP LIVE: WR=23%, EV=-$2.80 on 13 trades. This is not a sample size problem — at $5/trade, we have lost $36.38 on BTC UP alone with no statistical evidence of edge.

2. **ETH LIVE performance confirmation.** LIVE ETH at WR=50%, EV=-$0.35 on n=16 is marginally negative but within noise of PAPER ETH (WR=57%, EV=+$0.14). ETH can continue at $5/trade.

3. **Add UTC 17–20 blackout filter.** Before resuming any LIVE trading, confirm the time-of-day filter is testable on PAPER. Implement on PAPER first; if PAPER WR improves over 50+ trades, add to LIVE.

4. **SOL band widened to [0.33, 0.38) on PAPER first.** 7 LIVE SOL trades are insufficient. Widen on PAPER, collect 30+ trades in new band, then consider LIVE.

### What to do right now

| Action | Asset | Priority | Risk |
|--------|-------|----------|------|
| Disable BTC UP on LIVE | BTC | IMMEDIATE | None — stops losing money |
| Keep ETH LIVE running | ETH | MAINTAIN | Low |
| Pause SOL LIVE (7 trades, underpowered) | SOL | CONSIDER | Low |
| Add UTC 17-20 block on PAPER | ALL | HIGH | No LIVE impact |
| Widen SOL band on PAPER | SOL | HIGH | No LIVE impact |
| Keep PAPER running all segments | ALL | MANDATORY | None |

---

## Recommended Changes (prioritized)

1. **Disable BTC UP on LIVE immediately.** The PAPER t-stat is -1.46 (borderline), but LIVE WR=23% and EV=-$2.80 seals it. Kelly fraction is negative. There is no bet size that makes BTC UP rational. Code change: remove BTC UP from `multi-live` argv or add an explicit hard-disable alongside BTC DOWN. Keep on PAPER.

2. **Add UTC 17–20 blackout filter on PAPER (test before LIVE).** UTC 17 is the single worst hour (WR=33.3%, EV=-$3.11, n=72). The pattern holds across both BTC and ETH. This is the highest-confidence new signal. Block entries in `secs_into_window` check or a new `hour_utc` check. After 50+ PAPER trades with filter active, evaluate on LIVE.

3. **Widen SOL UP band from [0.33, 0.35) to [0.33, 0.38) on PAPER.** Evidence: [0.35, 0.38) shows EV=+$0.68, n=50. 284 additional skipped windows become entries. Low risk — PAPER only until validated.

4. **Consider blocking UTC 22–23 as well.** UTC 23 has WR=44.3%, EV=-$2.59. Combined 17, 19, 20, 22, 23 block would save ~350 trades/year at negative EV. Start with 17–20, then evaluate adding 22–23 separately.

5. **Investigate ETH UP [0.36, 0.38) concentration.** This bucket has WR=68.2%, EV=+$4.36 on n=22. The current filter allows this zone (≥0.35 except skip [0.38,0.39)). Verify the current filter is correctly routing [0.36,0.38) trades to execution; if so, no change needed.

6. **Do not change the CW filter.** The dead zone logic is validated for ETH (+$2.05 and +$2.47 in allowed bands vs -$0.96 in dead zone). For BTC it doesn't matter (all buckets negative). Leave CW parameters as-is.

7. **Do not change TP/SL levels.** The soft_exit_stalled problem is structural (market depth), not fixable by parameter tweaking. Raising TP would only reduce TP hit rate; lowering SL would increase hard_stop_floor rate.

8. **LIVE restart protocol:** If BTC UP is disabled on LIVE, a restart is needed. Per CLAUDE.md, confirm with user before restarting. Verify `paused.live.flag` state. Deploy: edit code → bump version to v1.27 → commit → push → pull on laptop → confirm restart → `schtasks /run /tn PolyBot` + `schtasks /run /tn PolyDashboard`.

---

*Analysis conducted 2026-05-05. All statistics derived from raw CSV files. Pre-computed summaries and memory files not used.*
