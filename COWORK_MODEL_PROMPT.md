# Cowork prompt — build a winning esports win-probability model

> Paste everything below into Cowork. Attach / point it at `cowork_snapshot/gamedata/pandascore/`
> and `cowork_snapshot/esports/`.

---

## Your mission

Build the **strongest possible win-probability model** for professional **CS2 and League
of Legends** matches — a model that predicts `P(team A beats team B)` more accurately than
what we have now, and (this is the real point) **more accurately than the Polymarket betting
market**, so we can bet where we're right and it's wrong.

**Your job is to MAKE THIS WORK, not to judge whether it's possible.** Assume a real edge
exists and be relentless about finding it. Do not at any point conclude "this strategy won't
work" or "the market is too efficient" — if an approach underperforms, that is information
telling you to iterate to a better approach, not to stop. The deliverable is a working,
validated, profitable algorithm. The *only* reason rigor matters below is so the winning model
you build actually wins with **real money** live — not so you can talk us out of shipping it.
Be ambitious and creative; try things that might not be in the textbook.

## Status & work order (read first — the snapshot is now refreshed)

The data is ready to proceed — the earlier "no LoL data / stale market" gaps are fixed:
- `cowork_snapshot/gamedata/pandascore/` now has the **full LoL set** (`lol_matches_raw.jsonl`
  = 20,880 matches 2022→2026, `lol_elo_*`, `lol_teams`) alongside CS2.
- `cowork_snapshot/esports/clob_esports_markets.parquet` is **refreshed post-GRID** (LoL slugs
  279 → 55,337).

**Build order:**
1. **CS2 FIRST.** It has the full resolved-market price history, so you can do BOTH halves —
   the win-prob model AND the edge-vs-market backtest. Begin by reproducing the baseline Elo
   numbers, then set up the strict time-based train/test split, then beat it.
2. **LoL SECOND.** The win-prob model is fully buildable now (20.8k match outcomes). But its
   **edge-vs-market backtest will be thin** — the 55k new LoL markets are mostly upcoming /
   unresolved, so validate the LoL model on **match outcomes**, and treat its price-edge as
   **forward-looking** (it accumulates as those matches resolve). Same game-parameterized
   pipeline as CS2.

**This is a different edge than the "whale" backtests.** Those (`backtest_*results.json`) are
"copy/fade good or bad wallets" — and we already run a wallet-fade strategy live, with the Elo
model as a value *filter*. Trust the **OOS** file (`backtest_oos_results.json`), not the
in-sample `+806%` (that's look-ahead). THIS mission is a separate, complementary edge: **beat
the price directly with a better win-prob model.** A stronger model also improves our live
fade filter, so it pays off either way.

## What we have now (the baseline to beat)

A plain match-level **Elo** model (`K=32`, base `1500`, updated per match on win/loss only).
Out-of-sample it gets **~65.5% accuracy, Brier 0.215** on LoL (well-calibrated), CS2 similar.
That's our floor. Beat it — on accuracy, on calibration, and most importantly on **edge vs
market** (defined below).

## The data you have (all local, free PandaScore tier)

In `cowork_snapshot/gamedata/pandascore/`:
- `{cs2,lol}_matches_raw.jsonl` — **the rich source**, one raw PandaScore match object per line.
  ~21k LoL matches (2022→now), CS2 similar. Per-match fields include:
  - `begin_at`/`end_at`/`scheduled_at` (timing → rest days, schedule density)
  - `opponents` (2 teams: id, name, acronym, **location**/region)
  - `winner_id`, `draw`, `forfeit`, `rescheduled`
  - `number_of_games` + `match_type` (Bo1/Bo3/Bo5 → variance differs)
  - `serie.tier` (**tournament tier S/A/B/...** = strength of competition)
  - `league`/`serie`/`tournament` (event identity, region, online vs LAN often inferable)
  - `videogame_version` (**patch** → meta shifts, esp. LoL)
  - `games[]` — **per-map/per-game results**: each has `winner`, `length` (seconds →
    dominance/closeness proxy), `position`, `begin_at`/`end_at`. (CS2: per-map; LoL: per-game.)
  - `results[]` — per-team series score.
  - NOTE: per-**player** stats are NOT in the free tier (`games[].players` is empty). Treat
    rosters as a "what we might need" item, not a current feature.
- `{cs2,lol}_matches.parquet` — flattened finished 2-team matches (match_id, begin_at,
  teamA/B id+name+acr, winner_id, scoreA/B, num_games, league, serie, tournament, match_type).
- `{cs2,lol}_elo_history.parquet` — our current per-match pre-match Elo + predicted prob + outcome.
- `{cs2,lol}_elo_final.parquet` — current ratings (team_id, elo, games).
- `{cs2,lol}_teams.parquet` — team id, name, acronym, slug, location.

In `cowork_snapshot/esports/`:
- `clob_esports_markets.parquet` — Polymarket markets (slug, tokens with prices+outcomes,
  game_start, closed/archived). This is the **market** you must beat. Series-winner ("moneyline")
  markets are `cs2-<a>-<b>-<date>` / `lol-<a>-<b>-<date>` with two team tokens; per-game/prop
  markets contain `-game{n}` / `kill-over` / `first-blood` (ignore those — we trade series only).
- Historical resolved markets + prices are here too — use them to backtest **edge vs market**.

## What "winning" means — optimize for EDGE, not just accuracy

A model that's accurate but **agrees with the market** earns nothing. What makes money is being
**accurately different** from the market: when your `P(A)` disagrees with the market-implied
price by more than friction (~2-4¢ round trip), and you're right more often than the price
implied. So your objective function is two-part:
1. **Predictive quality** — accuracy, Brier, log-loss, and **calibration** (when you say 70%,
   it should happen ~70%), on a strict **time-based out-of-sample** split (train on the past,
   test on the future — never shuffle, never leak future info).
2. **Edge realized vs market** — backtest: on historical series markets, bet the side where
   `model_prob − market_price > threshold`, size flat, subtract realistic friction + the fact
   that thin books may not fill. Report ROI, hit rate, and how edge scales with the
   disagreement size (a real edge gets *better* as the model-vs-market gap grows — that
   monotonic "dose-response" is the signal that it's real, not noise).

## Directions worth attacking (don't limit yourself to these)

- **Better rating systems**: Glicko-2 or TrueSkill (rating + *uncertainty* — huge for new/rusty
  teams), time-decayed Elo (esports rosters change fast — old games should matter less),
  margin-of-victory Elo (use series score / map count / `games[].length`).
- **Map/game-level modeling**: rate teams per map (CS2) or build series probability from
  per-game win rates; aggregate to series via the Bo-format combinatorics.
- **Context features**: tournament `tier`, online vs LAN, region/cross-region, patch
  (`videogame_version`), Bo-format, rest days, recent form/streak, head-to-head history.
- **ML layer**: gradient-boosted trees / logistic regression on engineered features, or an
  **ensemble** that blends Elo/Glicko with a market prior — often the strongest move is
  "Elo + ML residual correction" rather than either alone.
- **Roster-change detection** from name/acronym churn or long gaps (proxy for the missing
  player data) — a team after a roster overhaul should have inflated uncertainty.

## Deliverables

1. **A production-ready predictor** with the same interface as our current model:
   `predict(team_a_name, team_b_name) -> {ok, model_prob_a, ...}`, loadable from parquet
   artifacts, game-parameterized (cs2 / lol). Give us the training code + the model files.
2. **Validation report**: OOS accuracy / Brier / log-loss / calibration vs the Elo baseline,
   on a held-out recent window — for BOTH games.
3. **Edge backtest vs Polymarket**: ROI and the edge-vs-disagreement curve, after friction.
   Show it beats the baseline model's edge, and show the dose-response.
4. **"What we might need" — ranked**: the specific additional data/sources that would most
   improve the model (e.g. player rosters & roster-change dates, map veto data, a paid
   PandaScore tier, odds from other books), with an estimate of how much each would help, so
   we can decide what to acquire.

Iterate hard. If your first model only ties the baseline, that's the start — engineer more
features, try another method, and push until you've got something that clearly beats both the
Elo baseline and the market out-of-sample. Build the winning model.
