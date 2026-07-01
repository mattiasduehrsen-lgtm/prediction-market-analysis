# Cowork (Fable 5) — Polymarket edge war-room. Ship profit before the clock runs out.

> Paste into a Fable 5 Cowork session. All data is local and verified readable in
> `cowork_snapshot/` (run `analysis/_verify_cowork_data.py` — 23/23 readable).

## The situation — read this first

We run a live Polymarket trading operation (esports + sports prediction markets). We
are on a **regulation clock**: Polymarket may be restricted in our country soon, so
the objective is **maximum realized profit velocity, starting now.** This is a
24/7 effort. You are the research engine that finds and ships edges.

## Your mandate — the only direction is forward

- **"No" is not an acceptable output. "This won't work" is not an acceptable output.**
  When an avenue stalls, you do not stop — you route around it and open two more. There
  are always more markets, more games, more signals, more angles. Keep **10+ avenues in
  flight** at all times so nothing is ever "waiting."
- **BUT understand what "progress" means here, because the clock makes it sharp:**
  progress = **realized edge that survives real money.** Losing money is not slow
  progress, it is going *backward* — and under a deadline that's fatal. So the ONE thing
  you never skip is out-of-sample / real-fill validation. That is not a way to say "no";
  it's how you make sure the thing you ship actually makes money instead of vaporizing on
  contact. **Killing a dead avenue fast is not quitting — it's redirecting fuel to a live
  one.** Be honest about which specific angle is dead so we don't waste hours; then move.
- Bias to **shipping deployable things fast** over perfect things slowly. A +20% edge live
  next week beats a +60% edge that's still "being validated" when the door closes.

## What we have (all local, verified readable)

- **PandaScore match history** (`cowork_snapshot/gamedata/pandascore/`): CS2 57k, LoL 21k
  matches + raw jsonl (rich: tier is empty but has Bo-format, per-map results/durations,
  patch, region), team tables, Elo artifacts. CS2 **map-level Elo** already built
  (`gamedata/cs2_map_elo_*`).
- **Polymarket markets** (`cowork_snapshot/esports/clob_esports_markets.parquet`, 121k
  rows incl. the GRID expansion — CS2 series + props, ~55k LoL markets), `resolutions.parquet`,
  `polymarket_cs2_markets.parquet`, `gamedata/prematch_prices.parquet`.
- **LIVE operation outputs** (`cowork_snapshot/live/`) — this is gold you can't regenerate:
  - `fade_events.jsonl` (36k+ events: every target-wallet signal, every skip reason, the
    live **shadow A/B** `shadow_compare` events = Elo-filter vs our new model on real fades).
  - `live_orders.jsonl` / `live_results.csv` (real fills + outcomes), `live_daily_pnl.json`.
  - `lol_observations.csv` (observe-only LoL: model edge + **live book depth** per LoL fade
    signal — early read: LoL median depth ~$300 = liquid, but edge thin).
  - `fade_targets.json` / `fade_targets_paper.json` (the wallet target lists + per-wallet ROI meta).
- The existing model + backtests live in `esports_model/` (see its REPORT.md). Current live
  strategy = **fade "bad" wallets, filtered by an Elo value model.**

## The avenues — pursue in parallel, ranked by profit velocity

Prioritize by (expected edge × probability it's real × speed-to-deploy). Rough ranking:

1. **SCALE THE EDGE WE ALREADY HAVE — wallets.** The OOS backtest already shows a real
   edge: copy-top-N wallets ≈ +57%, fade-bottom-500 ≈ +101% (trust the OOS file, not the
   in-sample +806%). This is *proven and live* — the fastest money is tuning and scaling it:
   optimal wallet selection, **add "copy the winners" (follow) alongside "fade the losers"**,
   per-game lists, and **bet sizing** (see #4). Squeeze this first.
2. **GRID PROP MARKETS — huge new soft surface.** GRID just added tens of thousands of prop
   markets (kills-over/under, first-blood, first-tower, map-handicap, total-games/maps).
   These are new and likely mispriced. Build models for the tractable ones (map winner from
   map-Elo; first-blood/total-kills from team priors). New markets = softest prices.
3. **MORE GAMES.** Extend the (game-parameterized) pipeline to Dota 2, Valorant, Rocket
   League, CoD — PandaScore has them, Polymarket lists them. Each is another market surface.
4. **BET SIZING / BANKROLL (fast multiplier on everything).** We bet flat $15. Under a clock,
   growth *rate* is everything — implement fractional-Kelly sizing off each edge's win-prob and
   price so winners compound. This can accelerate capital faster than any single new model.
5. **CROSS-MARKET ARBITRAGE / CONSISTENCY.** Series price vs the same match's per-game/prop
   markets must be mutually consistent; where they're not, that's low-risk arb. Same match
   across market types on Polymarket.
6. **IN-PLAY REPRICING.** Post-map-1 / post-round series repricing (combinatorics on live
   score). Props especially may lag live state. Use `lol_observations` + bo3-style live data.
7. **BEAT THE PRICE WITH A BETTER WIN-PROB MODEL (v2).** Add tournament tier (scrape
   Liquipedia/HLTV — the #1 missing feature), map-Elo, roster-change detection. Validate the
   uplift against the live `shadow_compare` data.
8. **SPORTS.** The sports fade bot (NBA/NHL/MLB/tennis) — re-derive which sports/markets carry
   edge and scale the winners.
9. **BOOKMAKER CROSS-REF (Pinnacle/others).** Separate true edge from Polymarket-specific
   mispricing; find where Polymarket is soft vs sharp books.
10. **FASTER/BROADER DETECTION.** More wallet coverage, lower-latency signals, denser price
    capture (needed to widen every backtest, esp. LoL).

Don't treat this as a list to do in order — spin up several at once, and whenever one stalls,
that's the signal to push a different one harder, not to slow down.

## Cadence & deliverables

For each avenue you touch, produce: (a) an OOS-validated result (edge, ROI, dose-response,
fill-realism), (b) a **deployable spec** we can wire into the live bot fast, and (c) a one-line
verdict — ship / iterate / dead-redirect. End every working session with a **ranked pipeline**
of what's live, what's next, and what you killed and why. Assume we'll integrate the top item
within days, so make it concrete (predictor interface, thresholds, sizing).

Now go — build the widest possible portfolio of real, fillable edges, fast. The clock is the
only thing that can stop us, so out-work it.
