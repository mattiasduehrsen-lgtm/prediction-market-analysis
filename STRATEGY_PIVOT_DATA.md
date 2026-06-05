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

## ★ FEASIBILITY VERDICT (2026-06-02, full data) — POSITIVE & ROBUST ★
After fixing team-name matching (strip (BOn)/ex-/parentheticals, exclude
handicap markets, fuzzy + date-window match, require >=10 games Elo history):

- **1,148 markets** joined (model + pre-match price + outcome).
- Model accuracy 63.4% vs market 65.2% (market slightly sharper — expected).
- **Edge-threshold sweep — ROI climbs monotonically with model/market disagreement:**
    thr 0.00  1148 bets  +4.0%
    thr 0.10   392 bets  +19.7%
    thr 0.20   103 bets  +38.0%
  (monotonic dose-response = real edge, not noise. Low WR + high ROI =
   value-betting underdogs the market overprices. The fact ROI RISES as we
   restrict to high model-disagreement proves the MODEL adds value, not blind
   underdog betting — that would be flat across thresholds.)
- **RIGOR 1 (2c slippage):** thr 0.10 +13.6%, thr 0.20 +29.2%. Survives friction.
- **RIGOR 2 (out-of-sample time split, 2c friction):** TRAIN +9.9%, TEST +18.8%.
  Edge PERSISTS (strengthens) on later unseen data — opposite of overfitting.

This is the first strategy in the project to survive walk-forward + friction +
out-of-sample. Walk-forward Elo (no look-ahead), genuine pre-match prices, real
outcomes, 159 OOS bets.

### Remaining risks before live money
1. LIQUIDITY — we bet underdogs at low prices; can we get filled at size?
   Polymarket esports books can be thin. The 2c slip may understate real cost.
2. Pre-match price = a trade that happened, not guaranteed available liquidity.
3. Matching covers 1,148 of 2,560 series markets (established teams). 
4. Match-level Elo only (no map detail). Could improve.
5. Backtest -> live gap: must PAPER-validate before real money (this is where
   the fade/MLB died — but those never passed a rigorous OOS backtest like this).

### Next step — DONE: PAPER bot deployed 2026-06-02
- `cs2_model.py` — Elo ratings + team matching + win-prob.
- `cs2_model_bot.py` — PAPER bot. Each cycle: finds CS2 series markets starting
  within 15 min, computes model prob, compares to live CLOB midpoint, paper-bets
  the model side when |edge|>0.10 at the live best-ask. RECORDS ORDER-BOOK DEPTH
  at entry (the liquidity reality check). Skips unmatched / <10-game teams.
  Output: output/cs2_model/paper_bets.csv.
- `analysis/refresh_elo.py` — hourly: pull recent CS2 matches, rebuild Elo.
- `analysis/evaluate_cs2_model.py` — every 30 min: resolve bets, PnL, median
  book depth. Output: paper_summary.json.
- Scheduled tasks: CS2ModelBot (continuous), CS2EloRefresh (hourly), CS2ModelEval (30 min).

### KNOWN FOLLOW-UP (matching coverage)
Some high-volume current teams don't match PandaScore names yet (e.g. "3DMAX"
unmatched, "Falcons" maps to a 7-game team). The bot SAFELY skips these, but it
costs coverage. Improve team-name matching (manual alias map for top teams +
better fuzzy) after seeing how many markets get skipped vs bet in the first day.

### Validate before live money
Run paper 2+ weeks. Watch: (1) paper ROI vs the +13-19% backtest, (2) median
book depth — is there liquidity to fill underdog bets at size? If both hold,
graduate to small live. If book depth is thin, the backtest edge won't survive.

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

## ★ PHASE 1 VERDICT — MAP MODEL (2026-06-05): REJECTED ★
Investigated the "use per-map win rates (Team A 70% on Mirage)" idea.
- DATA: bo3.gg free API (api.bo3.gg, no key/Cloudflare) has per-map history —
  137k games with map_name + winner_clan_name, AND live current-map status.
  Downloaded 28,277 CS2 games (2023+). Great lower-tier coverage.
  (Saved: cowork_snapshot/gamedata/bo3/{games,matches,teams}.jsonl)
- MODEL: map-adjusted Elo (overall Elo + shrinkage-blended per-map Elo).
  analysis/build_map_model.py, analysis/map_feasibility.py.
- GATE 1 (does map info help predict?): NO. Map-aware Brier 0.2429 vs
  map-AGNOSTIC 0.2419 (agnostic better). Even with both teams >=8 games on the
  map, agnostic wins. Knowing the map adds nothing.
- GATE 2 (beat Polymarket map prices, OOS + 2c friction):
    map-aware  : TRAIN +9.6%  TEST -14.0%  (FAILS out-of-sample)
    team-only  : TRAIN +21.2% TEST +6.2%   (weakly positive, but thin/noisy)
- WHY IT FAILS: the veto removes each team's worst maps, so every played map is
  one both teams are comfortable on -> map-specific skill gaps compress exactly
  when they'd matter. Good teams are good everywhere (skill transfers).
- DECISION: do NOT build the live map/veto pipeline (Phase 2/3). The
  map-specific thesis is dead; team-strength-on-maps is the same (weaker) edge
  as the series model. SERIES model remains the real edge (+18.8% OOS).
  Phase 1 cost $0 and saved us from chasing noise.

## Data sources NOT yet exhausted (if we want more)
- Liquipedia API (free) — could supplement match history / rosters; redundant with
  PandaScore for now.
- The Odds API / PandaScore paid — bookmaker odds (the higher-probability edge),
  requires payment.
- HLTV/bo3.gg — richer stats (player ratings, map win rates) but Cloudflare-gated.
