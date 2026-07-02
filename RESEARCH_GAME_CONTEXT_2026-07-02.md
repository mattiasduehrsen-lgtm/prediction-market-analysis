# Game-context data research — rosters, maps, tiers (2026-07-02)

**Question:** can we capture the context that moves odds — "donk isn't playing this
match" (roster), "they're strong on Mirage" (map), "this is a B-tier event" (tier)?
All findings verified hands-on against live APIs and our own data this session.

---

## 1. Tournament tier — SOLVED, free, and it was under our nose

The #1 gap in the win-prob model (`serie.tier` is empty in 100% of free PandaScore;
the v2 plan assumed we'd have to scrape Liquipedia/HLTV). **bo3.gg carries it natively:**

- Every bo3 match object has **`tier` (s/a/b/c/d) + `tier_rank`**, and its `tournament`
  object adds `event_level`, `event_scope`, `event_type`, city/country (LAN inference).
- Coverage in our local dump: **22,083 / 22,098 matches tiered (99.9%)** —
  s:1,099 · a:604 · b:7,419 · c:11,960 · d:1,001.
- We already know tier matters for the FADE too: the June analysis measured our edge
  at **−5.7% on tier-S** (sharp, GRID-covered events) vs positive on lower tiers.

**Use:** (a) join bo3→PandaScore matches (team names + date) to add `tier` + LAN as
v2 model features — the #1 lever, now free; (b) optional live-bot tier guard
(down-weight/skip tier-S fades). NOTE: `Bo3Download` was deleted as a spent one-shot;
re-create as a **weekly** task when implementing (script `analysis/bo3_download.py`
still in repo; data cutoff currently ~Jun 4).

## 2. Rosters ("donk isn't playing") — partially solved, free

- **`teams/{slug}` on bo3.gg returns the current 5-man roster** (nicknames, coach
  flags) **plus `from_transfers` (roster-change history!), team `rank`, `rank_diff`,
  `six_month_earned`** (prize money = strength proxy). All free, no key.
- **Per-match lineups (who actually played THIS match) are NOT in the bo3 API**
  (probed: `games/{id}` has only `players_count`; `game_rosters`/`players_stats`/
  `game_players` all 404). The site shows lineups, so HTML scraping is possible but
  brittle. GRID (paid) and HLTV (Cloudflare) have it; PandaScore paid tier has it.
- **LoL:** Leaguepedia + Oracle's Elixir publish per-game player data free
  (industry-standard for pro LoL; not yet probed — follow-up).

**Use (the 80/20):** a daily **roster-change detector** — poll bo3 team rosters for
teams appearing in our matched markets; diff vs yesterday; emit
`roster_changed_recently(team, days_since_change)`. This captures the *tradeable*
form of the signal (post-transfer/stand-in teams are where the model is most wrong —
the report's #2 error source) without needing per-match lineups. Feed it to
(a) the live bot as an uncertainty guard, (b) v2 as a feature.

## 3. Maps ("strong on Mirage") — data already in hand; honest value measured

From our own 28k map records (`cs2_map_elo_history.parquet`, both teams ≥8 games on
the map, n=4,680):

| predictor | Brier | acc |
|---|---|---|
| overall Elo (`p_overall`) | 0.2430 | 57.1% |
| map-specific Elo (`p_map`) | 0.2446 | 56.1% |
| blend (25–50% map) | **0.2425** | 57.3% |

- **Map-specific Elo alone is WORSE than overall Elo** — per-team-per-map samples are
  too thin. A light blend helps only marginally (−0.0005 Brier). **Do not complicate
  the series model for this.**
- BUT the map genuinely moves the number: **median |p_map − p_overall| = 4.7¢, p90 =
  12¢.** That's irrelevant-to-small for series pricing and **large for map markets**
  (`-game1`/`-game2` winner), of which GRID lists thousands.
- Veto/pick data: match detail has **`match_maps`** — empty pre-veto on the sample
  probed; likely populates near match start. `games[].map_name` confirms played maps
  post-hoc (how our map-Elo was built).

**Use:** target the **map-winner markets** with `blend(p_overall, p_map)` once
`PropEdgeScan` (running daily on captured real quotes) shows whether that class is
soft. Don't ship a map feature into the series model.

## 4. Bonus finds (logged for later)

- **`game_rounds`** per game: round-by-round `end_reason`, sides, durations,
  `round_map_data` — enough to build round-level in-play win probability later.
- bo3 `rating`/`stars` per match (attention proxy), `streams[].viewers_number`
  (liquidity proxy?), `winner/loser_clan_score` per map (margin for MoV-Elo).
- bo3 API quirk (cost us an hour): responses use **`results`**, not `data`.

## Ranked implementation plan

1. **Tier feature** (free, #1 model lever, 99.9% coverage): weekly `Bo3Download`
   revival → bo3↔PandaScore join → tier+LAN into v2 features → hand to Cowork v2
   pass (this replaces the Liquipedia-scraping lever in `COWORK_MODEL_V2_PROMPT.md`).
2. **Roster-change detector** (daily, free): bo3 team-roster diffs → live-bot
   uncertainty guard + v2 feature.
3. **Map-market pricing** (conditional): wait for `PropEdgeScan` calibration data;
   if the map-winner class is soft, price it with the blend.
4. **LoL player data** (follow-up): probe Oracle's Elixir / Leaguepedia.
