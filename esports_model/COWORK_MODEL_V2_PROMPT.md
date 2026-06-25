# Cowork prompt — push the esports win-prob model further (v2)

> Paste into Cowork. Continues the model in `esports_model/`. Data in
> `cowork_snapshot/gamedata/pandascore/` and `cowork_snapshot/gamedata/`.

## Context

We have a working CS2/LoL win-prob model (`esports_model/`) that beats the Elo
baseline **only modestly** out-of-sample (CS2 +0.85pp acc; edge over Elo is clearest
only at ≥15¢ market disagreements). It's now running in **shadow mode** in the live
bot — logging its call next to the Elo filter on every CS2 fade (`shadow_compare`
events) without trading on it. Your job: **make the model meaningfully better than the
Elo baseline**, especially in the fillable mid-range (not just the high-variance tail).

Same rules as before: be relentless, assume gains are findable, validate strictly
out-of-sample (time split, no leakage), and optimize for **edge vs the Polymarket
price**, not just accuracy. Don't tell us it can't be done — iterate until it's better.

## The three biggest levers (ranked by the v1 report)

1. **Tournament tier / event strength — THE #1 missing feature.** `serie.tier` is empty
   in 100% of free PandaScore. S-tier LAN vs B-tier online is hugely predictive. Get it
   from **Liquipedia or HLTV** (event tier/prize pool/LAN-flag), join by event name +
   date, and add tier + LAN flag as features. This is the single highest-value addition.
2. **CS2 map-level Elo.** We already built `cowork_snapshot/gamedata/cs2_map_elo_history.parquet`
   and `cs2_map_elo_final.parquet`. Fold per-map ratings into the series model (e.g.
   map-Elo aggregated to a series-win prob, or as features) — series outcomes hinge on
   the veto. Test whether it beats the current decayed-Elo features.
3. **Roster-change detection.** `games[].players` is empty (free tier), so proxy roster
   turnover from name/acronym churn + long gaps, and *inflate uncertainty / discount old
   games* after a likely change. The #1 source of model error is teams that look strong
   on stale rosters. (If a player-data source is cheap, rank it for us.)

Also worth trying: opponent-adjusted form, patch-aware LoL features (meta shifts),
Bo-format-specific calibration, and an ensemble that blends the model with a light
market prior.

## Validate against the live shadow data (when it has accrued)

The bot is logging `shadow_compare` (Elo vs model decision) and these resolve over
time. Once there's a sample, check: on the fades where the two models **disagree**,
which one is right more often / more profitable? That's the real-money test of whether
any v2 gain matters. Until then, keep using the OOS edge-vs-price backtest
(`backtest_cs2.py`) as the proxy.

## Deliverables

1. Updated `src/features.py` (new features, no leakage) + retrained model, same
   `Predictor` interface.
2. OOS validation vs the **current** model (not just baseline Elo) — acc/Brier/logloss/
   calibration, both games, and the **edge-vs-price** backtest with dose-response.
   Show the mid-range edge (5–15¢) improves, not just the >15¢ tail.
3. For each lever: did it help, by how much, and at what data cost. Rank what to acquire.

The bar: clearly beat the **current** model on OOS edge in the fillable range. If a
lever doesn't help, drop it and try the next — don't stop at parity.
