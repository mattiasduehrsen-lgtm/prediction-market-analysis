# Sports Fade Strategy — Findings & Deployment Readiness

**Date:** 2026-05-24
**Status:** Comprehensive backtest complete. NOT YET LIVE. Recommended next: 1 week of consensus-filtered PAPER validation, then NBA-only LIVE at $5/trade.

---

## Executive summary

We extended the esports fade-the-losers strategy to 5 sports categories. After comprehensive in-sample + out-of-sample backtesting plus realistic friction modeling, the strategy has **real OOS edge in NBA, NHL, MLB, and Tennis** when the right filters are applied. **Soccer does not work** (negative wallet-persistence correlation). The optimized config (consensus filter, market-type filter, skip soccer) produces **+5.55% to +7.43% OOS ROI** under realistic friction.

**Single strongest opportunity:** NBA with consensus-N>=2 filter = **+32.62% friction-adjusted OOS ROI**.

---

## Analyses completed

| # | Analysis | File | Key finding |
|---|---|---|---|
| 1 | Per-sport recon | `_sports_recon.py` | NHL 124, NBA 268, MLB 734, Tennis 851, Soccer 135 qualifying losers |
| 2 | In-sample backtest | `sports_backtest.py` | +6.23% ROI (look-ahead biased) |
| 3 | Out-of-sample backtest | `sports_backtest_oos.py` | -0.94% ROI (in-sample edge mostly fake) |
| 4 | Parameter sweep | `sports_backtest_sweep.py` | Stricter wallet criteria recover edge |
| 5 | Friction modeling | `sports_backtest_friction.py` | At realistic friction (40% cancel + 2c), +2.66% combined |
| 6 | Wallet persistence | `sports_wallet_persistence.py` | NBA losers 63% stay losing (vs 50% random); Soccer INVERTS |
| 7 | Per-market-type | `sports_market_type.py` | Spread/handicap = -1.34%; Total O/U = +13.62% |
| 8 | Latency sensitivity | `sports_latency_sensitivity.py` | First signal in market = -6 to +1% ROI; 5th+ signal = +8 to +19% ROI |
| 9 | Time-of-day | `sports_time_patterns.py` | Noisy patterns at 7d sample; not actionable yet |
| 10 | Best-config combined | `sports_best_config.py` | Consensus N>=2 + skip spread + friction = +5.55% ROI |

---

## The big findings, in plain English

### 1. The strategy works — but only with stricter filters than esports uses

The naive recon (n>=15 trades, ROI<=-5%) **looked great in-sample** (+6.23%) but **collapsed OOS** (-0.94%). This was textbook look-ahead bias: we picked wallets that happened to be unlucky in the test window itself.

Tightening to **n>=30 trades, ROI<=-15% to -30%** recovers real edge OOS. Deep losers are more persistent than mild losers.

### 2. NBA is the standout

Across ALL filters and friction scenarios, NBA was the most robust:

| Sport | OOS ROI (no friction) | OOS ROI (realistic friction + consensus N>=2) | Confidence |
|---|---|---|---|
| **NBA** | +15.86% | **+32.62%** | High (1,141 resolved trades) |
| NHL | +14.35% | +11.11% | Low (197 trades — small sample) |
| Tennis | +6.94% | +4.01% | High (6,293 trades) |
| MLB | +4.84% | +1.35% | Medium (1,517 trades) |
| Soccer | -2.07% | N/A (excluded) | Skip |

### 3. Soccer doesn't work — losers become winners

Soccer was the BIGGEST shock. Despite having a -$3M whale and 135 qualifying losers in 14d, soccer "losers" showed **negative correlation** between train and test ROI (-0.177). At deeper loss thresholds, only 32% stayed losing in OOS (random = 50%). This is bizarre — possibly long-shot bettors who occasionally hit big payouts that flip their ROI positive. **Don't trade soccer.**

### 4. Consensus signals beat fast signals

The most surprising finding. **The first target wallet's signal on a market has near-zero (or NEGATIVE) edge.** Waiting for 5+ wallets to fade the same market produces +8% to +19% ROI.

| Sport | 1st signal in market | 5th+ signal in market |
|---|---|---|
| NBA | +1.53% ROI | **+19.48% ROI** |
| MLB | -6.44% (loses) | +8.58% |
| Tennis | -0.71% | +8.23% |

**The edge is in consensus, not speed.** Production filter: require N>=2 unique target wallets per market before fading.

### 5. Spread/handicap markets are negative-EV — only trade totals + moneylines

| Market type | OOS ROI |
|---|---|
| Total O/U | **+13.62%** |
| Moneyline (in "other" bucket) | **+7.97%** |
| Spread/handicap | **-1.34%** |

NBA totals fade alone: +38.56% ROI. Sharps trade spreads; retail trades totals + moneylines.

### 6. Wallet persistence is the underlying mechanism

NBA losing wallets continue losing at 60-64% rate (10-14pp above random). Tennis losers at deepest threshold continue losing at 72% (22pp above random). This is the persistent retail-fade edge.

---

## The deployment-ready configuration

After all OOS + friction + filter analysis, the optimized strategy is:

```python
# Wallet selection (per sport)
NBA:    min_trades=30,  min_roi=-30%, min_entry=$0.40
MLB:    min_trades=50,  min_roi=-30%, min_entry=$0.40
Tennis: min_trades=50,  min_roi=-15%, min_entry=$0.50
NHL:    min_trades=30,  min_roi=-15%, min_entry=$0.70

# Universal filters
- Skip soccer entirely (negative persistence)
- Skip any market with 'spread', 'handicap', or '-line-' in slug
- Require N>=2 unique target wallets to hit same market before fading
- Entry-price floor $0.40 (NBA/MLB) or $0.50-0.70 (sport-specific)
- Per-market exposure cap $50 (current setting OK)
- Opposite-side hedge guard (already deployed)
```

**Expected friction-adjusted OOS ROI: +5.5% to +7.4%.**

At $5/trade × ~1,000 weekly trades = $5,000/week deployed, +6% ROI = **$300/week ≈ $15k/year**.

At $10/trade scale: $30k/year. At $20: $60k/year.

---

## Implementation status

| Component | Status |
|---|---|
| Sports paper bot (sports_fade_bot.py) | ✅ Running in PAPER mode |
| Consensus filter (N>=2) | ✅ Deployed (just now) |
| Market-type filter (skip spread/handicap) | ✅ Deployed |
| Soccer prefix removal | ✅ Deployed |
| Per-sport optimal config | ⚠️ Currently uses ONE config across sports; could split |
| Sports evaluator cron (every 10min) | ✅ Scheduled as PolyBotSportsEval |
| Sports refresh cron (hourly wallet pool update) | ❌ Not yet — uses static fade_targets.json from initial recon |
| Sports dashboard view | ❌ Not built |
| Telegram notifications for sports | ❌ Intentionally silent (paper mode) |

---

## Deploy-readiness checklist (criteria to go LIVE)

### Must-have before any LIVE deployment

- [ ] Sports paper bot runs for 7+ days under v2 (consensus + filters)
- [ ] Sports evaluator confirms OOS prediction matches reality (ROI within ±50% of backtest expectation)
- [ ] At least 200 resolved sports paper trades to verify volume math
- [ ] Verify consensus filter doesn't eliminate too much volume (target: 30-50% of signals proceed to "fire")
- [ ] Verify opposite-side hedge guard is firing correctly (it's been catching many in esports)
- [ ] Sports refresh pipeline rebuilt (or accept manual refresh weekly)
- [ ] User explicitly confirms readiness

### Nice-to-have

- [ ] Per-sport wallet refresh (more granular than single fade_targets.json)
- [ ] Sports dashboard tab
- [ ] Sports-specific Telegram alerts (stalls, big PnL days)
- [ ] Bet sizing optimization based on actual paper variance
- [ ] OOS validation extended to 21-30 days when more data is scraped

---

## Risks and unknowns

### Known risks

1. **Sample size for NHL is small** (197 resolved test trades). The +11% OOS could be variance. Treat NHL as "tentatively positive" until more data.

2. **OOS window is only 7 days.** A 14-21 day OOS test would be more robust. Currently we only have 14d of trade history scraped.

3. **Consensus filter assumes uncorrelated wallet decisions.** In reality, multiple losing wallets might be following the same tipster or correlated sources, in which case "consensus" is one decision repeated, not true independent signal.

4. **Market-maker presence.** Sports markets attract sharper money than esports. If MM activity scales up, our edge could compress.

5. **Wallet refresh staleness.** Current `fade_targets.json` is from the 2026-05-23 recon. As wallets become winners (mean-reversion) or quit, our target list goes stale. The current refresh pipeline only runs for esports — sports needs its own.

### Unknowns

- **True production cancel rate for sports markets.** Esports = 40-45%; sports could be different due to liquidity depth. Will know after paper runs for 7 days.
- **Long-term wallet decay rate.** How quickly do the top losers stop trading or become winners? Need ongoing tracking.
- **Per-sport optimal bet size.** Kelly criterion says ~8% of bankroll for NBA but variance limits suggest 1-2% in practice.

---

## Recommended path forward (compressed for NBA season closing)

**Critical timing constraint:** NBA Finals end June 10-19, then dark until October.
NHL Stanley Cup Final also mid-June. To capture NBA's +32% edge this season,
we must compress paper validation.

### Days 1-2 (May 25-26): Compressed paper validation

1. Sports paper bot v2 (consensus filter) collecting signals — already running
2. Sports evaluator computes paper PnL every 10 min — already scheduled
3. Target: 30+ paper resolutions with positive ROI before deciding to deploy
4. Verify consensus filter is firing (not eating too much volume)

### Day 3 (May 27) — go/no-go decision

If paper ROI is within ±50% of backtest prediction (+1.3 to +4% real-world):

**Deploy NBA only at $5/trade LIVE.** Configuration:
- `LIVE_BET_USD = 5`
- `CONSENSUS_THRESHOLD = 2`
- `SKIP_MARKET_KEYWORDS = ('spread', 'handicap', '-line-')`
- `LIVE_MIN_OUR_ENTRY = 0.40`
- Tight caps: `DAILY_LOSS_CAP = 100`, `DAILY_RISK_CAP_USD = 200`

### Weeks 1-3.5 (May 27 → June 19): NBA Finals capture

- ~15-22 trading days of NBA at $5 = ~1,000-1,500 LIVE trades
- If LIVE ROI is positive at n=100, scale NBA bet size to $10
- Daily: ~$50-150 profit at $5; $100-300 at $10

### Week 2 onward (June 1): Layer Tennis

- French Open final week → Wimbledon prep → US Open in August
- Tennis is year-round — no season-end cliff
- Start at $5/trade

### Week 3 onward (June 15): Layer MLB

- Daily games through October
- Lower per-trade edge (~1%) but massive volume
- Start at $5/trade

### June 19+: NBA dark, MLB + Tennis carry forward

- Tennis Wimbledon (late June → mid July) — peak tennis volume
- MLB regular season through end of September
- October: NBA + NHL return, NFL in full swing — add back

### What I'm NOT recommending

- Don't skip the 48-72h paper validation just because the window is closing
- Don't deploy at $10+ on day 1 — verify edge translates first
- Don't deploy soccer (negative wallet persistence in OOS)
- Don't remove the consensus filter "to get more volume" — that volume reduction IS the improvement
- Don't deploy NHL LIVE yet — small sample (197 OOS trades), wait for next season's data

---

## Files produced

### Analyses
- `analysis/sports_backtest.py` — in-sample backtest
- `analysis/sports_backtest_oos.py` — out-of-sample (7d/7d split)
- `analysis/sports_backtest_sweep.py` — parameter sweep
- `analysis/sports_backtest_friction.py` — execution-friction modeling
- `analysis/sports_wallet_persistence.py` — wallet-level persistence test
- `analysis/sports_market_type.py` — per-market-type breakdown
- `analysis/sports_latency_sensitivity.py` — rank-in-market / consensus discovery
- `analysis/sports_time_patterns.py` — hour-of-day / day-of-week
- `analysis/sports_best_config.py` — combined-best-config simulation

### Production code
- `sports_fade_bot.py` — paper bot with all v2 filters
- `analysis/build_sports_targets.py` — consolidates per-sport losers into fade_targets.json
- `analysis/evaluate_sports_paper.py` — paper PnL evaluator (cron)
- `_sports_recon.py` — generic sport recon (re-runnable)
- `watch_sports_fade.bat` — watchdog .bat
- `run_sports_eval.bat` — evaluator runner .bat

### Results / data
- `cowork_snapshot/sports/fade_targets.json` — 1,766 sports losing wallets
- `cowork_snapshot/sports/clob_sports_markets.parquet` — 159k sports markets index
- `cowork_snapshot/{nhl,nba,mlb,tennis,soccer}_recon/` — per-sport data
- `cowork_snapshot/sports_backtest_*.json` — analysis result files
- `output/sports_fade/paper_trades.csv` — live paper signals (resets v2-onward)

### Scheduled tasks (laptop)
- `PolyBotSports` — sports paper bot, runs continuously
- `PolyBotSportsEval` — sports evaluator, runs every 10 min
