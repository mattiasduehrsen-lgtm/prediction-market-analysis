# Cowork brief: get the IN-PLAY CS2 strategy fully dialed in for live

You previously analyzed this Polymarket CS2 bot project and concluded that **one** strategy survives liquidity + friction + out-of-sample testing: **in-play post-map-1 series repricing** (back the team the thin market over-fades after it loses map 1; +26% backtest, +30% OOS, median $69 fillable, bootstrap 90% CI [+8.5%, +43.9%], mechanism = retail markets overreact to the first map). Everything else (pre-match series model, fade, map model, sports, crypto) is dead — the pre-match "edge" was an unfillable mirage with negative closing-line value.

**This task is narrow: produce the complete validation + production plan to take the in-play strategy from a small backtest (n=75, 31 OOS) to confidently live with real money — or tell me it's not ready and exactly why.** Be rigorous and skeptical; small-n is the central risk. Numbers, not vibes.

## Read first
- `STRATEGY_PIVOT_DATA.md` — full history; see the "COWORK VERDICT" and "in-play" sections.
- `analysis/inplay_backtest.py` — the existing in-play backtest logic.
- `cs2_inplay_bot.py` — the live PAPER bot already running (its design, thresholds, what it logs).

## Data (all local)
- `cowork_snapshot/gamedata/inplay_joined.parquet` — the joined in-play dataset (model_live, market_live, outcome, score state, t1).
- `cowork_snapshot/gamedata/bo3/{games,matches}.jsonl` — per-map results, map names, **per-map begin/end timestamps**, match **tier**, bo_type.
- `cowork_snapshot/esports/scrape/shards/*.parquet` — ALL trades (conditionId, outcome, side, price, size, timestamp). Use this to reconstruct **price trajectories around map completions**.
- `cowork_snapshot/gamedata/feasibility_joined.parquet` — pre-match series-model probs (the input that gets inverted to a single-map p, then updated live).
- `output/cs2_inplay/paper_bets.csv` — live paper bot output incl. `bo3_detect_lag_s` and `book_depth_usd` (may be sparse until live matches accumulate).
- ⚠️ **Data-integrity:** in this env, pandas elementwise `price*size` was intermittently corrupt and corrupts on parquet round-trip. Do dollar math in `numpy.float64`; sanity-check against raw shards (~$114M total volume, ~$10 median trade).

## The analyses I need (concrete, on the data)

### A. The edge window (the make-or-break, do this first)
The whole strategy is the gap between a map completing and the market repricing. Measure it:
1. From the shards, reconstruct the **series-winner price trajectory in the 0-30 min after each map-1 completion** (map-1 completion time ≈ map-2 begin_at from bo3). How fast does the price move from its pre-map-1 level to its new settled level? Minutes or seconds? Plot/quantify the half-life of the repricing.
2. Combined with the paper bot's `bo3_detect_lag_s`, determine the **realistic actionable window**: time we detect map-1 completion → time the price has settled. Is there room to act? At what latency does the edge disappear? This single answer gates everything.

### B. Re-validate the edge on the FULL local dataset
The n=75 was a subset. Rebuild the in-play sample as large as the data allows (all resolved Bo3/Bo5 series with a bo3 timeline + shard prices). Then:
3. Re-run ROI by edge threshold, **with the liquidity filter applied** (fillable $ on our side near the live price), walk-forward OOS, 2¢ friction. Confirm (or refute) the +26%/+30% on the bigger sample.
4. **Direction:** is the edge really only in the contrarian subset (back the map-1 LOSER)? Compare contrarian vs front-running vs both. Recommend which to bet.
5. **State coverage:** post-map-1 only, or also post-map-2 in a 1-1 decider, and Bo5 states? Which states carry the edge?
6. **Segmentation (only if n supports it):** by tier, by favorite/underdog, by how big the pre-match mispricing was. Where is the edge concentrated — and is any slice just overfit noise?

### C. Sizing, capacity, and realistic expectations
7. **Capacity:** from book depth + fill measurements, realistic $ per bet. How many in-play opportunities per week exist in the data? → realistic monthly turnover and $ P&L. Is this worth the operational complexity, honestly?
8. **Sizing:** recommend a fractional-Kelly fraction given the measured edge + variance (the contrarian subset is ~27% win rate = long losing streaks). Give the bankroll math and the max-per-bet cap.

### D. Execution & risk design
9. **Entry mechanics:** limit vs market, at what price relative to `model_live` and the live book; how long to leave an order resting; what to do if unfilled.
10. **Risk controls:** daily-loss cap, max concurrent exposure, a drawdown circuit-breaker appropriate for the variance, and behavior during Polymarket maintenance / bo3 outages / stale data.
11. **Model-input robustness:** the live prob inverts the pre-match series Elo to a single-map p. Is that p good enough, or should the single-map prob come from somewhere better? Note team-matching coverage gaps (bo3 ↔ Polymarket ↔ Elo) that cause skips.

### E. Go/No-Go
12. A concrete **graduation checklist** (paper → live): the exact numeric thresholds on edge-window, paper ROI, paper sample size, and latency that must be met before risking $1, plus a staged sizing ramp.

## Deliverable
A prioritized, decision-ready plan: the edge-window verdict (A) first, then validated parameters (B), capacity/sizing (C), execution+risk spec (D), and the go/no-go checklist (E). If the edge window (A) is too short to capture at our ~free-feed latency, say so plainly — that kills it, and I'd rather know now. Prefer a few well-validated conclusions over a long speculative list.
