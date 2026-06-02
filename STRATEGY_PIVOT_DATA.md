# Strategy Pivot — Data-Driven CS2 Model (autonomous work log)

Started 2026-06-02 while user is at work. Goal: source + download all viable
game data, then assess feasibility of a model-vs-market betting strategy on
Polymarket CS2 markets. NO live trading changes — research only.

## Decision context
- The fade strategy edge is ~0 (win rate tracks price = efficient market).
- Per-wallet analysis: no durable edge. Latency fix (on-chain, 2s) is the last
  pending test of the fade, running passively.
- Pivot under investigation: predict CS2 match outcomes from game data, bet when
  our model disagrees with the Polymarket price.

## Data sources investigated (2026-06-02)
| Source | Access | What it gives | Verdict |
|---|---|---|---|
| **PandaScore** (free token) | ✅ 1000 req/hr | CS2 matches back to 2016: teams, acronyms, winner, scores, league/tournament, times; teams + rosters | **PRIMARY** |
| PandaScore odds / map detail | ❌ paid | bookmaker odds, per-map stats | not on free tier |
| Liquipedia API | ✅ free, no signup | results, rosters, tournaments | backup / supplement |
| HLTV, bo3.gg | ⚠️ Cloudflare | gold-standard stats | fragile to scrape |
| Our Polymarket data | ✅ have it | 52,511 CS2 markets w/ clean team names + game_start + prices + outcomes | join target |
| Polygon blockchain | ✅ have access | Polymarket market resolutions (ground-truth outcomes) | results cross-check |

## Join key (solved)
Polymarket `question` field: "CS2: <Event>: <TeamA> vs. <TeamB>" + `game_start`
timestamp. Join to PandaScore matches by team name/acronym + date.

## Plan / progress
1. [done] Verify PandaScore token + free-tier coverage.
2. [in progress] Download CS2 match history (2022-06 → now) + teams to laptop.
3. [todo] Build team Elo / form ratings from match history.
4. [todo] Join PandaScore matches <-> Polymarket CS2 markets (team+date).
5. [todo] Feasibility test: model win-prob vs Polymarket price; does
   model-disagreement betting beat the vig vs actual outcomes?
6. [todo] Stop, analyze, recommend next step.

## Storage layout
cowork_snapshot/gamedata/pandascore/
  cs2_matches_raw.jsonl   (raw match objects, resumable append)
  cs2_matches.parquet     (flattened)
  cs2_teams.parquet
cowork_snapshot/gamedata/
  polymarket_cs2_markets.parquet  (20,469 H2H markets; 2,673 series, 18,827 resolved)
  prematch_prices.parquet         (pre-match implied prob; 1,723 markets, ~317s before start)
  feasibility_joined.parquet      (model vs market, written by feasibility.py)

## RESULTS SO FAR (2026-06-02, partial data through 2023-06)
- **Elo predicts CS2 outcomes: 61.1% accuracy**, Brier 0.231 (vs 0.25 coin flip),
  log-loss 0.654 (vs 0.693). **Calibration is excellent** across all buckets
  (pred 0.55->actual 0.57, 0.74->0.75, 0.84->0.89). A simple match-level Elo
  is genuinely predictive and well-calibrated.
- Pre-match Polymarket prices extracted for 1,723 series markets.
- ⚠️ 61% accuracy is NOT the same as beating the market — the market price
  already encodes team strength. The real test is feasibility.py (does the
  model find MISPRICINGS vs Polymarket). That needs 2025-2026 PandaScore data,
  which is still downloading. Verdict will be in pipeline.log + sent to Telegram.

## Autonomous tasks running
- **PandaPipeline** (scheduled task): download CS2 history -> flatten ->
  polymarket extract -> elo -> prematch prices -> feasibility. Logs pipeline.log.
- **PandaFeasNotify** (09:25): re-runs feasibility, posts verdict to Telegram.

## NEXT STEPS (after the feasibility verdict)
IF model beats market (positive ROI at higher edge thresholds):
  1. Refine the model: recent-form weighting, Elo K-tuning, home/LAN factor,
     opponent-strength-of-schedule. (Map-level detail would help but is PandaScore-paid.)
  2. Build a PAPER betting bot (reuse infra): for each upcoming CS2 market, compute
     model prob, compare to live Polymarket price, paper-bet when edge > threshold.
  3. Validate paper for 2+ weeks before any live money.
IF model does NOT beat market (flat/negative ROI):
  - CS2 series markets are efficiently priced. Options: (a) odds-based cross-market
    edge (needs a paid odds feed — PandaScore paid tier or The Odds API), or
    (b) accept that Polymarket esports has no exploitable edge and stop.
  - Either way: the fade strategy + this model test will have given a clear answer.

## Data sources NOT yet exhausted (if we want more)
- Liquipedia API (free) — could supplement match history / rosters; redundant with
  PandaScore for now.
- The Odds API / PandaScore paid — bookmaker odds (the higher-probability edge),
  requires payment.
- HLTV/bo3.gg — richer stats (player ratings, map win rates) but Cloudflare-gated.
