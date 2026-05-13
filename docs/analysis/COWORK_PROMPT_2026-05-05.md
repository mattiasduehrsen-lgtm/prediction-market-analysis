# Cowork Deep Dive — 2026-05-05

## Your role

Quantitative trading analyst. We are in trouble. Planned improvements are not delivering. Previous deep dives (April 25, May 1) produced filter recommendations that were applied (v1.26a/b/c), but the post-v1.26 live performance is -$0.76 EV/trade on 25 trades versus the projected +$1.22. We need fresh eyes, honest critique of whether this strategy is salvageable, and genuinely new ideas.

Be blunt. The previous analysis said "keep MR with filters and it's profitable." We need to know if that's still true with fresh data, and if not, what to do next.

---

## Snapshot location

```
C:\Users\home user\Desktop\prediction-market-analysis\cowork_snapshot\
```

Contents:
- `5m_trading/trades.csv` — **1661 total PAPER trades** (40 columns; pure MR after v1.26a killed RS)
- `5m_trading/skipped_windows.csv` — every window evaluated and not entered
- `5m_live/trades_BTC-15m.csv`, `_ETH-15m.csv`, `_SOL-15m.csv` — 51 LIVE trades total (all MR, real money)
- `bot/signal_5m.py`, `bot/market_5m.py`, `bot/main.py` — current source
- `PATCH_HISTORY.md`, `STRATEGY_HISTORY.md` — full version history
- `bot_recent.log` — recent bot activity

---

## Current bot state (as of v1.26c, 2026-05-03)

### Active strategies
PAPER + LIVE run only `mean_reversion` on BTC/ETH/SOL 15m windows. RS was killed v1.26a.

### Active filter stack (what must pass for an entry)
1. Price in `[0.32, 0.40]` ENTRY band (global)
2. Asset-specific price bands:
   - BTC-15m: `[0.38, 0.40]` only (floor raised v1.21)
   - ETH-15m: `≥0.35`, skip dead zone `[0.38, 0.39)` (v1.22)
   - SOL-15m: `[0.33, 0.35]` only (very narrow)
3. BTC DOWN: **hard disabled** (v1.21)
4. SOL DOWN: **hard disabled** (v1.21)
5. Cross-window filter (v1.26c): `cw in [-0.15,-0.02] ∪ [+0.02,+0.10]` — blocks flat/near-zero and extreme windows
6. Spread cap: ETH ≤0.03 (v1.22)
7. Liquidity ≥ $15k (market must not be thin)
8. secs_into_window ≤ 30s for ETH (v1.22)
9. Crash regime filter (v1.26b): `|btc_pct_change_at_entry| ≤ 0.10`
10. GBM collapse model: skip if collapse_prob ≥ threshold
11. BTC DOWN regime filter: skip if BTC hasn't bounced from window start
12. DECEL filter: btc_momentum_decel computed, printed, used by advisor

---

## Critical context: what went wrong since May 1

### Operations failures (not strategy)
- v1.26a deployed May 2 with cross-window filter using wrong band edges (+0.03 instead of Cowork-recommended +0.02). Bot produced **zero trades for ~24 hours** until the bug was caught.
- PAPER bot process was dead for **~35 hours** (May 2 10:21 AM → May 3 21:51 PM) because restart sequence omitted `PolyBotPaper` task. Only recovered when zero-trade issue was investigated.
- Net result: only **25 new MR trades** since May 1 analysis instead of expected ~100.

### Post-v1.26 performance (25 trades, 2026-05-03 to 2026-05-05)

```
All MR (n=25): WR=48%  PnL=-$19.12  EV=-$0.76/trade
  avg_win=$9.45  avg_loss=$-10.19

BTC UP  (n=10): WR=30%  PnL=-$48.53  exits: 7 soft_exit_stalled, 3 take_profit
ETH UP  (n=14): WR=64%  PnL=+$34.34  exits: 5 soft_exit_stalled, 9 take_profit  
ETH DOWN (n=1): WR=100% PnL=+$7.50
SOL     (n=0):  zero trades (price consistently outside [0.33,0.35] band)

Exit mix: 52% soft_exit_stalled, 48% take_profit
```

**Previous (May 1) Cowork projected EV: +$1.22/trade on filtered MR.**
**Observed: -$0.76/trade on 25 live trades.**

Sample is too small for statistical significance, but the direction is concerning — especially BTC at 30% WR.

---

## Questions for this deep dive

### Q1. Is BTC UP MR still worth running?

The May 1 analysis said BTC UP MR has EV ≈ +$0.05/trade (t-stat=0.07, statistically indistinguishable from zero). Collect 200 more trades before deciding, was the recommendation. Now with 10 more live observations at 30% WR / -$48:
- Is BTC UP worth the variance it contributes?
- Does the cross-window filter or entry band constraint change its character?
- Should we disable BTC UP MR on LIVE (while keeping on PAPER for monitoring), or disable entirely?

### Q2. Why is soft_exit_stalled dominating exits (52%)?

Soft_exit_stalled fires at 420s remaining (7 minutes left in a 15m window) if price is ≤ 0.25. It's meant to cut extended losers. But 52% of exits being soft-stop rather than take_profit suggests we're entering positions that aren't reverting. 
- Has the soft_exit_stalled threshold (0.25) become too conservative? Too aggressive?
- Is this a market structure shift post-crash (May 1 crash may have changed Polymarket participants' pricing behavior)?
- Look at the `price_60s_after_entry` and `hold_seconds` distribution for soft_exit_stalled vs take_profit exits. Are soft exits stalling from the start, or reversing late?

### Q3. Fresh ideas — what are we NOT trying?

The current strategy is: enter when cheap side is 32–40¢, hope for mean reversion within 15 minutes. The filter stack is growing but the core alpha hypothesis hasn't changed. 

Suggest 2-3 genuinely different approaches that the data might support, for example:
- **Time-of-day bucketing**: Are there specific UTC hours where MR WR is significantly better/worse? (The entry timestamp is in `opened_at`.)
- **Directional momentum within window**: If the cheap side has been moving toward 0.50 for the last 60s (`cheap_side_velocity > 0`), is it a better entry than a static cheap side?
- **Entry price bands with asymmetric edges**: Is 0.38–0.40 actually the sweet spot, or would 0.35–0.38 perform better for ETH UP specifically?
- **Liquidity bands**: The liquidity filter cuts below $15k but is there an upper bound — i.e., does high liquidity ($30k+) predict lower WR?
- **Window start imbalance**: `up_price_at_window_start` is captured. Does a more extreme window start (e.g., UP < 0.40 at open) predict better or worse MR?

### Q4. SOL is collecting zero trades

SOL UP MR has the best historical EV/trade (+$1.72). But SOL's entry band is `[0.33, 0.35]` — only 2¢ wide. Prices haven't been in that band post-crash.
- What is the historical WR/EV by price band for SOL? Is there a justification to widen the band to `[0.33, 0.38]` or `[0.33, 0.40]`?  
- What is the distribution of SOL UP prices in the full skipped_windows.csv? How often is SOL in [0.33, 0.40] vs always extreme?
- Should SOL UP entry band be widened to match ETH's looser constraint?

### Q5. Cross-window filter — is it actually helping?

v1.26c implemented `[-0.15,-0.02] ∪ [+0.02,+0.10]` for all assets. Compare:
- ETH: pre-v1.22 (no cw filter), post-v1.22 (ETH-specific filter), post-v1.26c (generalized filter). What does OOS show?
- BTC: previously used global `[-0.15,+0.10]` filter. Now uses union with dead zone. What's the effect on BTC WR?
- The `cross_window_pct` column is populated in recent trades. Show the WR/PnL breakdowns by cw bucket.
- Is the dead zone `(-0.02, +0.02)` truly dead for BTC and SOL? Or was it validated only on ETH?

### Q6. What would make the strategy more durable?

Given:
- The strategy is vulnerable to crash regimes (May 1)
- SOL entry band is too tight to get trades
- BTC UP is statistically zero EV
- ETH is the only clearly profitable sub-strategy

Is there a path to a simpler, more robust strategy? For example:
- **ETH-only LIVE bot** (drop BTC and SOL from LIVE until each validates independently)
- **Tighter trade selection** — enter only when 3+ confirming signals align (cw in range AND cheap_side_velocity > 0 AND spread tight)
- **Regime switch** — classify each 15m window into "trending" vs "ranging" using cross_window_pct + btc_pct_change_at_entry. Enter only in ranging regime.

---

## Deliverables

1. **Executive summary** (5 bullets): BTC UP verdict, soft_exit_stalled diagnosis, top new idea, SOL band recommendation, confidence in current strategy overall.
2. **BTC UP MR analysis**: statistical test at n=209 (all history), recommendation.
3. **soft_exit_stalled diagnosis**: WR/PnL by exit type, price trajectory analysis.
4. **SOL entry band analysis**: WR/EV by price bucket, recommendation.
5. **Cross-window filter OOS validation**: did it help BTC and SOL?
6. **Top 2 new ideas** with projected impact (even rough estimates from the available data).
7. **LIVE risk assessment**: should we resume LIVE trading now, or wait for more data?

---

## Ground rules

- Re-derive all statistics from `trades.csv`. Don't trust summary files.
- Sample sizes are small (25 new trades). Be explicit about confidence levels.
- `opened_at` is the entry timestamp. `cross_window_pct` and `btc_pct_change_at_entry` are populated.
- Treat the BTC 30% WR post-v1.26 as alarming until proven otherwise.
- Default position size: PAPER = $15, LIVE = $5.
- If the honest answer is "pause LIVE until you have 150 more trades," say so.
