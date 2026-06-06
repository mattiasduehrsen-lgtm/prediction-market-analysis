# Cowork deep-analysis brief: find an edge on Polymarket esports — or tell us to stop

You are analyzing a Polymarket trading bot project. I want a **rigorous, skeptical, creative** review of everything we've tried, and either (a) a genuinely new angle we haven't considered, or (b) an honest conclusion that there's no exploitable edge and we should stop. Do not flatter the work or invent edges that won't survive friction. I would rather hear "stop" than chase noise.

## Read these first (full history is here)
- `STRATEGY_PIVOT_DATA.md` — the running log of everything tried in the current research arc, with verdicts.
- `PATCH_HISTORY.md` — chronological changes (v1.x) with reasoning.
- `STRATEGY_HISTORY.md` — older architecture/strategy record.

## What the bot does now
Trades Polymarket **CS2 (Counter-Strike) esports** markets only. Two live ideas:
1. **Fade + model hybrid (LIVE, small $):** detect a "persistent loser" wallet's trade on-chain (~2-4s via Alchemy), and fade it (bet the other side) ONLY if a team-strength Elo model also says our side is underpriced by >0.07.
2. **Series Elo model (the one real edge):** rate teams by Elo from match history, bet series-winner markets when our probability diverges from the Polymarket price.

## Every strategy tried, and the verdict (these are the shortcomings)
1. **15-minute crypto mean-reversion (BTC/ETH/SOL up/down):** abandoned. No durable edge.
2. **Cross-market arbitrage (Kalshi vs Polymarket):** retired long ago.
3. **Fade "persistent loser" wallets (esports):** edge ≈ 0. Win rate tracks entry price almost exactly → efficiently priced market. Deep-dived 415 live trades: trade-weighted edge −1.3%.
4. **Per-wallet selection:** no durable signal. Wallets profitable to fade in one period are ~break-even the next (persistence correlation only +0.20). A market maker (95k trades) was being faded by accident and caused most losses — now filtered.
5. **Latency:** found 99.7% of signal latency was Polymarket's data-api being ~220s stale. Fixed with an on-chain (Polygon/CTF TransferSingle) listener at ~2-4s. Edge improved but is still marginal — speed alone didn't save the fade.
6. **Sports fade (MLB/NBA/NHL/Tennis):** failed live despite good paper ROI. Hypothesis: traditional sportsbooks + arbitrage bots keep those Polymarket prices efficient.
7. **Series Elo model:** the ONLY thing that backtests robustly. ~63% accuracy, beats Polymarket series prices: +19.7% ROI at 0.10 edge threshold, **+18.8% out-of-sample after 2¢ friction.** Fade+model combo backtested +30%. BUT: low trade volume (~a few/day after all filters), it mostly bets underdogs (~41% win rate, high variance), and **live fill/liquidity is unproven.**
8. **Per-map model (Team A is a "Mirage team"):** REJECTED. Map-specific Elo does NOT beat plain team strength at predicting map outcomes (Brier slightly worse), and loses out-of-sample (−14%). Why: the veto removes each team's worst maps, compressing map-specific skill gaps; good teams are good everywhere.
9. **In-play series repricing (current bet):** after a map completes, the Polymarket series price mis-reprices by ~10 points vs our calibrated update. Backtest +30% OOS but TINY sample (31 OOS bets); bo3 detection latency and mid-match liquidity unproven. A paper bot is now collecting live data on these two unknowns.

## Recurring failure patterns (the meta-problem)
- **Backtests look good, live underperforms.** Repeatedly (MLB, early fade). The series model has not yet been proven with live money.
- **Thin liquidity.** Esports markets are small; the very mispricings we find may be unfillable at size, and we may be the one slow trader getting picked off.
- **Low frequency.** After quality filters, very few bets — slow to validate, hard to compound.
- **Efficient where it's liquid, illiquid where it's inefficient.** The classic prediction-market bind.
- **We are retail:** Polymarket only, no paid data feeds (we use free PandaScore + bo3.gg APIs + our own on-chain listener), small bankroll, ~2-4s latency (not the sub-second of pro firms). We cannot win a pure speed race against sharps.

## Data you can use (all local)
- `cowork_snapshot/esports/clob_esports_markets.parquet` — ~55k CS2 markets (teams in `question`, `game_start`, `closed`, tokens).
- `cowork_snapshot/esports/resolutions.parquet` — market outcomes (winning_outcome).
- `cowork_snapshot/esports/scrape/shards/*.parquet` — ~800 files of ALL historical trades (proxyWallet, conditionId, outcome, side, price, size, timestamp). This is the full order-flow + price history.
- `cowork_snapshot/gamedata/pandascore/cs2_matches.parquet`, `cs2_elo_*.parquet` — match history + series Elo.
- `cowork_snapshot/gamedata/bo3/{games,matches,teams}.jsonl` — 137k per-map results (map_name, winner, round scores, timestamps), match tiers, live-capable API.
- `cowork_snapshot/gamedata/{polymarket_cs2_markets,prematch_prices,feasibility_joined,inplay_joined}.parquet` — joined model-vs-market datasets.
- `output/esports_fade/{live_results.csv,live_orders.jsonl,fade_events.jsonl}` — our actual live trades + every decision/skip event.
- `output/cs2_model/`, `output/cs2_inplay/` — paper-bot results.

## What I want from you
Think hard and be creative, but every idea must be **backtestable on the data above with an out-of-sample split, realistic friction, and a liquidity check.** Specifically:

1. **Is there an edge angle we've missed?** Examples to consider (not exhaustive — invent your own): providing liquidity instead of taking it (market-making the spread on thin markets); closing-line value / line-movement following; bet-sizing/Kelly to fix the low-frequency-high-variance problem; tier/region segmentation (is our edge concentrated somewhere?); timing of entry (how early/late to bet); exploiting predictable price paths during a series; correlated/同-event markets on Polymarket; fading specific *recreational* order-flow signatures vs sharp flow; calibration-arbitrage on extreme prices.

2. **Diagnose the backtest→live gap.** Using our live trades (`live_results.csv` + `live_orders.jsonl`) vs the backtests, quantify *why* live underperforms (slippage? adverse selection? we move the price? fills only when we're wrong?). This may matter more than a new strategy.

3. **The liquidity question, head-on.** Using the trade shards, measure realistic fillable size and spread on these markets at the moments we'd bet. If the edge is real but unfillable, say so.

4. **A verdict.** Rank the viable options by expected value *after* friction and liquidity. If the honest answer is "the series model is the only thing, here's how to maximize it" — say that. If it's "no durable edge, stop" — say that too, with the evidence.

Show your work (numbers, not vibes). Prefer a small number of well-validated conclusions over a long list of speculative ideas.
