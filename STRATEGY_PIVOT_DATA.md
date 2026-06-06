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

## ★ BEST USE OF bo3 — IN-PLAY SERIES REPRICING (2026-06-05): PROMISING ★
bo3's unique free value = LIVE match state (current map, series score, map
completion times). Idea: after map 1 of a Bo3, reprice the series-winner market.
- Method: pre-match series-model prob -> invert to single-map p -> after map1,
  P(A wins series | 1-0)=2p-p^2, |0-1)=p^2. Compare to Polymarket price at ~map1
  completion (bo3 map2 begin_at) from trade shards.
- analysis/inplay_backtest.py. n=122 (31 OOS).
- ROI (2c slip): thr0.05 +26.1% (75), thr0.10 +25.3%. WIN RATES 49-56%
  (healthier than pre-match ~41%). OOS: TRAIN +23.3%, TEST +30.0%.
- Market diverges from model's post-map1 prob by ~0.10 avg => market does NOT
  efficiently reprice after a map. Real inefficiency on thin retail live markets.
- CAVEATS: small sample (31 OOS); bo3 live map-completion LATENCY unmeasured
  (if bo3 lags >10min the edge is gone before we act); mid-match liquidity unknown.
- NEXT: PAPER in-play bot — watch bo3 live Bo3s, on map1 completion compute model
  live prob vs live Polymarket price, paper-bet divergence, RECORD bo3 detection
  latency + order-book depth. Resolves the two unknowns with zero risk.
- DEPLOYED 2026-06-05: cs2_inplay_bot.py (watchdog task CS2InplayBot) +
  analysis/evaluate_inplay.py (CS2InplayEval, 30min). Paper-bets when model live
  series prob diverges from live Polymarket price by >0.05; logs bo3_detect_lag_s
  + book_depth_usd. Output: output/cs2_inplay/paper_bets.csv + paper_summary.json.
  Math + bo3 reachability validated. Waiting on live matches to accumulate data.
  WATCH: paper_summary.json -> roi_pct (does +30% backtest hold?),
  median_bo3_lag_s (fast enough to act?), median_book_depth_usd (can we fill?).

## ★★ COWORK VERDICT (2026-06-05) — independent deep analysis ★★
Reproduced all numbers from local data (679,714 deduped trades, 870 live orders).
- **Pre-match series model edge is a LIQUIDITY MIRAGE.** The +18.8% OOS was on
  single-print prices, not fillable liquidity. Filter to $ actually tradeable on
  our side within 3c, 30min pre-match: median $0 (74% of bet-markets had ZERO).
  Cross-tab: everything +13.8% but ALL fillable subsets NEGATIVE and worse with
  more liquidity (>=$5 -9.4%, >=$50 -10%, >=$100 -15%). Capped-fill backtest -6.5%.
- **Negative closing-line value** confirms it independently: model-side price
  drifts -2.25% to close; only 31% move our way. Smart money disagrees. = not an edge.
- **Live fade = honest zero** (-0.06% on 416 resolved). Backtest agreed (~0). No gap.
  Slippage is zero (limit orders) BUT 46% of orders never fill, selectively in the
  underdog band the model wants -> we miss the GOOD fills.
- **Paper model bot -14.5%**: drifted into handicap markets (-23.5%, n=69) the model
  was never validated for; series subset +20% but n=11.
- **THE ONE SURVIVOR: in-play post-map-1 repricing.** Passes walk-forward + friction
  + LIQUIDITY (median $69 fillable, ROI IMPROVES with liquidity: >=$100 -> +40.6%).
  +26.1% (n=75), OOS +30%. Mechanism: thin markets OVERREACT to map 1; value is in
  the CONTRARIAN subset (back the map-1 LOSER, +37.2%). Bootstrap 90% CI [+8.5%,
  +43.9%], P(ROI>0)=99.3%. Caveats: small n; bo3 latency is the KILL SWITCH; small
  capacity (~$25-50/bet); high variance (needs fractional Kelly).
- **VERDICT:** (1) in-play = the only edge, continue on paper, watch bo3_detect_lag_s,
  go live small only if latency <1-2min holds + ≥30 more bets. (2) pre-match series
  model = STOP as a standalone bet, KEEP as the feeder/input to in-play. (3) fade,
  follow, map, sports, crypto, arb = all STOP (efficient where liquid, unfillable
  where inefficient).
- **DATA-INTEGRITY NOTE:** pandas elementwise price*size was intermittently corrupt
  in this env (constant ~6.1e6; parquet round-trip corrupts). Use numpy.float64 for
  price*size, don't persist the product to parquet.

## ★ EDGE-WINDOW RESULT (2026-06-05) — latency is NOT the kill switch ★
analysis/inplay_latency.py: in-play ROI vs ENTRY DELAY after map-1 completion
(prices carry-forward from shards; paper bot had 0 logged in-play bets, so this
shard reconstruction is how we measured the window).
  delay 0s +17.4% | 60s +23.6% | 5m +26.0% | 10m +36.0% | 15m +28.4% | 30m +8.8%
  avg|market-model| ~0.09->0.13 (does NOT close over the window).
- The edge does NOT decay in the first ~15 min — thin markets are STICKY after a
  map result (attention shifts to map 2). Window dies ~30 min as the post-map-1
  STATE goes stale (map 2 progressing), not because the market corrected.
- IMPLICATION: bo3 polling at 60s + a few min detection lag is FINE. We need ~10
  min, not seconds. The feared latency kill-switch is largely resolved.
- Caveats: small n (70-86); sample composition shifts with delay (carry-forward);
  fillability at the delayed price still to confirm.

## ★ IN-PLAY BOT FIX (2026-06-06) — the operational blocker Cowork flagged ★
Paper bot had logged 0 in-play bets. ROOT CAUSE: detection keyed live status off
bo3 /matches sorted -start_date = returns UPCOMING (future) matches, and its
id/status/range filters are all IGNORED by the API. So live matches were never in
the status dict -> every match skipped -> live_series=0 forever.
FIX (cs2_inplay_bot.py): detect entirely from the /games feed (which carries live
state + winners + timestamps). Post-map-1 = exactly 1 map done (has winner) + a
map live (state current/started). Auto-excludes Bo1 + deciders. Assume Bo3 (W=2).
Added debug events: live_detected / skip_model_unmatched / skip_no_pm_market so
the next live match shows where it falls through.
- Model coverage on recent live teams: 96% match Elo (66/69). The "9%" Cowork
  cited was the historical Polymarket-market<->bo3-timeline<->price join, NOT the
  model leg. Real LIVE limiter = whether Polymarket LISTS the (often low-tier)
  bo3 match -> will show as skip_no_pm_market.
- Status: deployed; CS2 quiet now (0 live games) so not yet confirmed end-to-end.
  Will start logging real bets (+ bo3_detect_lag_s + book_depth) when a live Bo3
  that Polymarket also lists reaches map 2.

## Data sources NOT yet exhausted (if we want more)
- Liquipedia API (free) — could supplement match history / rosters; redundant with
  PandaScore for now.
- The Odds API / PandaScore paid — bookmaker odds (the higher-probability edge),
  requires payment.
- HLTV/bo3.gg — richer stats (player ratings, map win rates) but Cloudflare-gated.
