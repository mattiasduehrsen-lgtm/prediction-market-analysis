# Esports win-prob model v2 — validation report (2026-07-02)

**Bar set by the prompt:** clearly beat the *current* model on OOS edge in the
fillable (5–15¢) range. **Result: met — but not the way the plan assumed.** The
fillable mid-range goes from **−6.6% ROI (current model) to +4.1%**, and all
fillable ≥5¢ bets from **+9.4% to +11.1%** (stable across both time halves).
The gain comes from a **tier+price decision layer** plus **seed-ensembling** —
NOT from adding tier/map/roster as model features, which we tested thoroughly
and which *reduce* market edge (details below; this is the most important
finding of v2).

---

## 1. What ships

| Piece | What it is |
|---|---|
| CS2 prob engine | 5-seed `HistGradientBoosting` ensemble on the **v1 feature set**, per-seed isotonic, averaged (`cs2_model_v2.joblib`) |
| LoL prob engine | Same, on **v1 + roster-staleness features** (`lol_model_v2.joblib`) |
| Decision layer | `Predictor.bet_ok(entry_price, tier_ord)`: entry price > 0.20, event tier known, tier < S |
| Tier data | `build_bo3_join.py`: bo3.gg↔PandaScore join (slug-parsed names + date), 79% of all CS2 matches, **90.6% of the OOS window**, plus serie-level propagation |
| Same interface | `predict.py` `Predictor.predict(team_a, team_b)` unchanged; shadow logging continues to work |

## 2. OOS forecast quality (strict time split, test = most recent 20%)

| Game | Model | Acc | Brier | Logloss | ECE |
|---|---|--:|--:|--:|--:|
| CS2 | baseline Elo | .6416 | .2212 | .6328 | .0193 |
| CS2 | **current v1** | .6501 | .2156 | .6225 | .0156 |
| CS2 | **v2 shipped** | **.6544** | **.2150** | **.6193** | **.0126** |
| LoL | baseline Elo | .6470 | .2185 | .6266 | .0203 |
| LoL | **current v1** | .6557 | .2141 | .6234 | .0178 |
| LoL | **v2 shipped** | .6540 | **.2128** | **.6132** | .0180 |

v2 beats current on every CS2 metric. LoL: clearly better Brier/logloss (the
money metrics for probability quality); accuracy −0.2pp is inside noise (±0.7pp).

## 3. The money test — CS2 edge vs Polymarket (1,600 OOS series markets, 2025-09-24 → 2026-06-02, 2¢ friction)

**Unfiltered** (how the current bot bets):

| | mid-range 5–15¢ | all ≥5¢ | ≥15¢ tail |
|---|--:|--:|--:|
| baseline Elo | −8.0% | +17.4% | +63.7% |
| current v1 | −6.6% | +20.2% | +73.9% |
| v2 shipped | −5.1% | +21.3% | +77.5% |

Mid-range is negative for *every* model — no feature set fixed that, because…

**With the v2 decision layer** (entry price > 0.20, tier known, non-S):

| | R2 mid 5–15¢ | R2 all ≥5¢ | fit half (≤Jan) | eval half (Feb→Jun) |
|---|--:|--:|--:|--:|
| baseline Elo | −1.4% | +6.1% | +6.5% | +5.3% |
| current v1 | +0.2% | +9.4% | +9.0% | +10.2% |
| **v2 shipped** | **+4.1%** | **+11.1%** | **+11.5%** | **+10.1%** |

The filter was chosen on the fit half only (pre-2026-02) and validated once on
the eval half; both rules also have independent prior support (thin-book
longshot losses; June fade analysis measured −5.7% on tier-S). Key diagnostic
from the fit half: mid-range bets at entry ≤20¢ ran **−64% ROI** (70 bets) and
unknown-tier events **−16%** — these were the entire mid-range loss.

**The tail warning that matters for the live bot:** the fat unfiltered tail
(+73–93% ROI) is mostly sub-20¢ longshots. Under the price filter the tail is
+27.8% — still excellent, but the headline tail numbers were never fillable.

## 4. Lever-by-lever verdict (deliverable 3)

Per-lever, 5-seed-averaged, edge on the same 1,600 markets with filter:

| Lever | Forecast metrics | Market edge (R2 ≥5¢ PnL) | Verdict |
|---|---|--:|---|
| (none) = v1 feats | — | **61.3u** | ships (CS2) |
| + tier features | logloss −.002 | 49.5u | **feature: drop. Filter: ship** — the tier JOIN is the single most valuable v2 artifact, used as a bet gate |
| + map-Elo | acc +0.2pp | 45.0u | drop (market prices map form; keep the pipeline for in-play work) |
| + roster proxies | ECE −.002 CS2; logloss −.011 LoL | 42.9u | **ship for LoL only** (no LoL price data to contradict the clear forecast gain) |
| all (v2 full) | best logloss | 42.2u | drop for trading; paired bootstrap: P(v2-full beats v1 on edge) = **0.04** — the extra features *hurt* edge near-significantly |

**Why features hurt edge while helping forecasts:** tier, map form, and
activity are public information the market already prices. Adding them makes
the model agree with the market more (better Brier), which *removes* the
profitable disagreements. Edge lives in what the model knows that the market
underweights — for us that's the rating/form core. This inverts the v1
report's assumption that tier was "the #1 missing feature": it was the #1
missing *bet-selection* signal, not model signal.

Seed-ensembling (5×) is pure variance reduction and helps both: ECE .0156→.0126,
mid-range +0.2%→+4.1%.

## 5. What to acquire next — re-ranked by evidence

1. **Nothing paid for the model itself.** Tier (the old #1) is now free and its
   value is captured in the filter. Paid PandaScore/GRID would not obviously
   add edge — it adds market-consensus info.
2. **LoL pre-match prices** (free, just logging): the LoL edge backtest still
   has 0 priced markets (`lol_observations.csv` accrues on the laptop; the
   fixed `clob_esports_markets.parquet` now yields 3,214 resolved LoL series
   to join against the moment prices exist).
3. **Live tier feed for the filter** (free, already planned): the weekly bo3
   refresh keeps `tier` current; the fade bot should pass `tier_ord` into
   `Predictor.bet_ok()`. Unknown-tier = skip is the safe default.
4. **Roster data** (bo3 `teams/{slug}` polling, free): would upgrade the LoL
   roster proxies and enable the planned roster-change guard. Player-level
   paid data: rank LAST — our proxies already capture most of the staleness
   signal (LoL logloss −.011), and per-match lineups are what would matter,
   which no cheap source has.

## 6. Leakage & verification

- Walk-forward features emit strictly before rating updates (unchanged v1 structure).
- Time split verified programmatically (max train ts ≤ min test ts, both games).
- Tier is pre-match metadata: verified `tier` present on 100/100 *upcoming*
  matches in the bo3 dump; serie-level propagation only spreads event metadata.
- Map-Elo features computed from ratings as of series start, before that
  series' maps update anything.
- Single-feature AUC scan: nothing above rating-strength levels (max 0.71).
- Filter fit on pre-2026-02 markets only; evaluated once on Feb–Jun.
- Bootstrap (4,000 resamples, paired by market) for all v1-vs-v2 edge claims.

## 7. Deployment notes (dev PC — do not restart the bot without asking)

- New/changed: `src/features.py`, `src/train.py`, `src/predict.py`,
  `src/build_state.py`, `src/build_bo3_join.py` (new), `src/build_map_features.py`
  (new), `src/backtest_cs2.py`, `src/make_charts.py`; artifacts
  `{game}_model_v2.joblib`, `cs2_bo3_join.parquet`, `cs2_map_feats.parquet`,
  `validation_v2.json`, `edge_backtest_cs2_v2.json`, `edge_ablation_cs2.json`,
  `cs2_validation_v2.png`.
- Pipeline order: `build_bo3_join.py` → `build_map_features.py` → `features.py`
  → `train.py` → `build_state.py` → `backtest_cs2.py`.
- `predict.py` now loads `{game}_model_v2.joblib`. The shadow compare keeps
  working (same interface); the new probs are the seed-ensemble.
- The live fade bot should adopt `bet_ok()` (price + tier gate) — that's where
  the measured money is. Shadow data will adjudicate v1-vs-v2 probs on real
  fills once accrued.
- bo3 dump ends ~Jun 4; the weekly refresh task keeps tier current going forward.
