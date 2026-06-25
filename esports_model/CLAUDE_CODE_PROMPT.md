# Handoff: esports win-probability model (built in Cowork → continue in Claude Code)

You are picking up work on the `prediction-market-analysis` repo. A Cowork session built a
CS2 + League-of-Legends win-probability model that beats the current Elo baseline and beats the
Polymarket price out-of-sample. Everything lives in **`esports_model/`** in this repo. Your job
is to verify it on this machine and then do the next task I pick (see "What I want next").

## ⚠️ Before you run anything

1. **Hardcoded path.** Every script has `ROOT = Path("/sessions/.../mnt/prediction-market-analysis")`
   — that's the Cowork sandbox path and does **not** exist here. Replace it with a repo-relative
   path, e.g. `ROOT = Path(__file__).resolve().parents[2]` (so it resolves to the repo root on
   both the dev PC `C:\Users\home user\Desktop\prediction-market-analysis` and the laptop
   `C:\Users\matti\Desktop\prediction-market-analysis`). Do this first or nothing runs.
2. **Don't touch the live bot.** Per `CLAUDE.md`: never restart PolyBot/PolyBotPaper without my
   explicit confirmation; never stop PAPER data collection. This model work is offline and does
   not touch the trading loop unless I ask you to integrate it.
3. **Use `uv` / the repo's Python 3.11.** Deps: pandas, pyarrow, scikit-learn, joblib, matplotlib.

## What was built

A single game-parameterized pipeline (`cs2` / `lol`):

- `src/features.py` — walk-forward feature build (no leakage; features emitted strictly before
  each match, ratings updated after). Features: standard Elo, **time-decayed Elo** (180-day
  half-life + margin-of-victory K), **Glicko-2 rating *and* deviation φ** (uncertainty for
  new/rusty teams), last-10 form, streak, rest days, head-to-head, Bo-format, same-region, LoL
  patch. → `artifacts/{game}_features.parquet`
- `src/train.py` — HistGradientBoostingClassifier + isotonic calibration on a strict time-based
  split (train = oldest 80%, calibrate on a time-ordered tail of train, test = newest 20%).
  → `artifacts/{game}_model.joblib`, `validation.json`, `{game}_oos_preds.parquet`
- `src/build_state.py` — dumps final per-team rating state for serving →
  `artifacts/{game}_team_state.parquet`, `{game}_h2h.parquet`, `{game}_state_meta.json`
- `src/backtest_cs2.py` — edge-vs-market backtest (joins OOS model probs to Polymarket series
  prices) → `artifacts/edge_backtest_cs2.json`
- `src/predict.py` — **the production predictor**. Loads only the artifacts above.
- `src/make_charts.py` → `artifacts/cs2_validation.png` · full writeup in `esports_model/REPORT.md`

Data source = `cowork_snapshot/gamedata/pandascore/{cs2,lol}_*` (PandaScore free tier, ~57k CS2 /
~21k LoL matches 2022→2026) and `cowork_snapshot/esports/` (Polymarket markets + prices). Note
this is a **snapshot**; a live deployment must pull fresh PandaScore + Polymarket and re-run
`features → train → build_state`.

## The predictor interface

```python
from esports_model.src.predict import Predictor
p = Predictor("cs2")                      # or "lol"
p.predict("Vitality", "NRG")
# {'ok': True, 'model_prob_a': 0.876, 'model_prob_b': 0.124,
#  'elo_prob_a': 0.948, 'glicko_prob_a': 0.930, 'games_a': 288, 'games_b': 296}
# unknown team -> {'ok': False, 'error': "unknown team(s): [...]"}
```

## Results (strict OOS, no shuffling)

| Game | Baseline Elo (acc / Brier) | This model (acc / Brier / log-loss / ECE) |
|------|---------------------------|-------------------------------------------|
| CS2  | 0.642 / 0.221 | **0.650 / 0.216 / 0.622 / 0.016** |
| LoL  | 0.647 / 0.219 | **0.656 / 0.214 / 0.623 / 0.018** |

**CS2 edge vs Polymarket** (1,600 OOS series markets, 2¢ friction): ROI rises monotonically with
the bet threshold — +9% (all) → +20% (5¢ gap) → +38% (10¢) → +74% (15¢); dose-response shows the
edge concentrates in >15% disagreements. Monotonicity = the edge is real, not noise.

**Verified:** label-permutation test (shuffled labels collapse to base-rate 0.55 acc / 0.248
Brier — no leakage); train/test have zero temporal overlap; the market itself is well-calibrated
(so it's a fair fight).

## Honest caveats — don't oversell these

- The model beats the **baseline Elo's** edge only **modestly** (clearest at ≥15¢ disagreement).
  Most "beat the market" profit is available to Elo too; our advantage is calibration + the tails.
- High-threshold ROI rests on a few hundred **underdog** bets — high variance, and thin
  Polymarket books may not fill at the quoted price. Treat ≥15¢ numbers as the optimistic end.
- `serie.tier` (tournament strength) is **empty in 100% of free-tier data** — the single biggest
  missing feature. Player rosters (`games[].players`) are also empty.

## Known blocker

`cowork_snapshot/esports/clob_esports_markets.parquet` synced **truncated** (valid PAR1 header,
no footer — incomplete copy). It blocks the **LoL** edge-vs-market backtest only (the LoL
win-prob model is fully validated on outcomes). Re-sync that one file from the source machine,
then a `backtest_lol.py` (clone of `backtest_cs2.py`) will run.

## What I want next (I'll tell you which)

1. **Make it runnable here** — fix the `ROOT` paths, re-run `features → train → build_state →
   backtest_cs2`, confirm you reproduce the numbers above.
2. **LoL edge backtest** — re-sync the truncated market file, write `backtest_lol.py`.
3. **Integrate as the live value filter** — we already run a wallet-fade esports strategy with
   Elo as a value filter; swap in `Predictor` and A/B it. (Follow `CLAUDE.md`: bump
   `src/bot/version.py`, log in `PATCH_HISTORY.md` + `STRATEGY_HISTORY.md`, ask before restart.)
4. **Harden the predictor** — add a team-name alias table (e.g. LoL "JDG"→"JD Gaming"), and a
   scheduled rebuild of `build_state` from fresh PandaScore pulls.
5. **Push model quality** — CS2 map-level Elo into the feature set, roster-change detection from
   name/acronym churn, and scrape tournament tier (Liquipedia/HLTV) to fill the biggest gap.

Start by reading `esports_model/REPORT.md`, then wait for me to pick a task.
