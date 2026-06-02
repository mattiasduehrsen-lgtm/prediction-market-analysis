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
