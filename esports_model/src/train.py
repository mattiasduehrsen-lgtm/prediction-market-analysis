"""
Train + OOS-validate the v2 shipped models vs the CURRENT (v1 single-seed)
model vs the Elo baseline. Strict time-based split (no shuffling); isotonic
calibration fit only on a time-ordered validation tail of the training period.

v2 ship configuration (chosen on edge-vs-price evidence, see REPORT):
  - CS2 prob engine: FEATS_V1 + 5-seed averaging. The v2 context features
    (tier/mapelo/roster) improve match-level metrics but REDUCE market edge
    (the market already prices that public info) -- so they are NOT in the
    CS2 trading model. Tier instead powers the bet FILTER (see predict.py).
  - LoL prob engine: FEATS_V1 + ROSTER + 5-seed averaging (clear Brier/logloss
    gain; no LoL price history yet to test edge, so forecast metrics decide).

Run with --ablate for the per-lever ablation table (single-seed, both games).
"""
import sys, json
from pathlib import Path
import numpy as np, pandas as pd
import pyarrow.parquet as pq
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression

ROOT = Path(__file__).resolve().parents[2]
PS = ROOT / "cowork_snapshot" / "gamedata" / "pandascore"
ART = ROOT / "esports_model" / "artifacts"
N_SEEDS = 5

FEATS_V1 = ["elo_diff", "elo_prob", "delo_diff", "glicko_mu_diff", "glicko_phi_a",
            "glicko_phi_b", "glicko_prob", "loggames_diff", "form10_diff",
            "form10_a", "form10_b", "streak_diff", "rest_a", "rest_b", "rest_diff",
            "h2h_a", "h2h_n", "num_games", "same_region", "patch", "new_a", "new_b",
            "games_a", "games_b"]
TIER = ["tier_ord", "tier_is_s", "tier_known", "bo3_rating", "bo3_stars"]
MAPELO = ["mapelo_veto_prob", "mapelo_mean_diff", "mapelo_best_diff",
          "mapelo_worst_diff", "mapelo_spread", "mapelo_ngames"]
ROSTER = ["phi_infl_a", "phi_infl_b", "phi_infl_diff", "act90_a", "act90_b",
          "act90_diff", "longgap_a", "longgap_b", "postgap_a", "postgap_b"]
FEATS_V2 = FEATS_V1 + TIER + MAPELO + ROSTER
ABLATIONS = {"v1": FEATS_V1, "v1+tier": FEATS_V1 + TIER,
             "v1+mapelo": FEATS_V1 + MAPELO, "v1+roster": FEATS_V1 + ROSTER,
             "v2": FEATS_V2}
SHIP_FEATS = {"cs2": FEATS_V1, "lol": FEATS_V1 + ROSTER}
# decision layer shipped with the model (fit half of market window, validated
# on the eval half; see edge backtest): entry price must be fillable, event
# tier must be known and below S.
BET_FILTER = {"min_entry_price": 0.20, "max_tier_ord": 3, "require_tier_known": True}


def metrics(p, y):
    p = np.clip(np.asarray(p, float), 1e-6, 1-1e-6); y = np.asarray(y, float)
    acc = ((p >= .5) == (y >= .5)).mean()
    brier = np.mean((p-y)**2)
    ll = -np.mean(y*np.log(p)+(1-y)*np.log(1-p))
    return dict(acc=round(float(acc), 4), brier=round(float(brier), 4),
                logloss=round(float(ll), 4))


def ece(p, y, bins=10):
    p = np.asarray(p, float); y = np.asarray(y, float)
    edges = np.linspace(0, 1, bins+1); e = 0.0
    for i in range(bins):
        m = (p >= edges[i]) & (p < edges[i+1] if i < bins-1 else p <= 1)
        if m.sum() > 0:
            e += abs(p[m].mean()-y[m].mean()) * m.sum()/len(p)
    return round(float(e), 4)


def _clf(seed):
    return HistGradientBoostingClassifier(
        max_iter=500, learning_rate=0.03, max_depth=3, l2_regularization=1.0,
        max_leaf_nodes=15, min_samples_leaf=80, early_stopping=True,
        validation_fraction=0.15, random_state=seed)


def fit_predict(tr, va, te, feats, seed=0):
    clf = _clf(seed)
    clf.fit(tr[feats], tr["actualA"])
    iso = IsotonicRegression(out_of_bounds="clip").fit(
        clf.predict_proba(va[feats])[:, 1], va["actualA"])
    return clf, iso, iso.transform(clf.predict_proba(te[feats])[:, 1])


def fit_ensemble(tr, va, te, feats, n_seeds=N_SEEDS):
    """Per-seed model + per-seed isotonic; average the CALIBRATED probs
    (measurably better than average-raw-then-calibrate on both games)."""
    clfs, isos, ps = [], [], []
    for s in range(n_seeds):
        clf, iso, p = fit_predict(tr, va, te, feats, seed=s)
        clfs.append(clf); isos.append(iso); ps.append(p)
    return clfs, isos, np.mean(ps, 0)


def load(game):
    df = pq.read_table(ART / f"{game}_features.parquet").to_pandas()
    df["begin_at"] = pd.to_datetime(df["begin_at"], utc=True)
    df = df.sort_values("begin_at").reset_index(drop=True)
    eh = pq.read_table(PS / f"{game}_elo_history.parquet").to_pandas()[["match_id", "pred_pA"]]
    return df.merge(eh, on="match_id", how="left")


def split(df, test_frac=0.2):
    n = len(df); cut = int(n*(1-test_frac)); val_cut = int(cut*0.85)
    return df.iloc[:val_cut], df.iloc[val_cut:cut], df.iloc[cut:], cut


def run(game):
    df = load(game)
    tr, va, te, cut = split(df)
    yte = te["actualA"]
    feats = SHIP_FEATS[game]

    res = {"game": game, "n_total": len(df), "n_test": len(te),
           "test_start": str(te["begin_at"].iloc[0].date()),
           "ship_feats": ("FEATS_V1" if feats == FEATS_V1 else "FEATS_V1+ROSTER"),
           "baseline_elo": metrics(te["pred_pA"], yte) | {"ece": ece(te["pred_pA"], yte)}}

    # current production model: single-seed v1
    _, _, p_cur = fit_predict(tr, va, te, FEATS_V1, seed=0)
    res["current_v1"] = metrics(p_cur, yte) | {"ece": ece(p_cur, yte)}
    # shipped v2
    _, isos, p_ship = fit_ensemble(tr, va, te, feats)
    res["ship_v2"] = metrics(p_ship, yte) | {"ece": ece(p_ship, yte)}

    # refit ensemble on train+val for the shipped bundle (iso kept from val tail)
    trva = df.iloc[:cut]
    clfs = [_clf(s).fit(trva[feats], trva["actualA"]) for s in range(N_SEEDS)]
    import joblib
    joblib.dump({"clfs": clfs, "isos": isos, "feats": feats, "game": game,
                 "bet_filter": BET_FILTER, "n_seeds": N_SEEDS},
                ART / f"{game}_model_v2.joblib")

    te_out = te[["match_id", "begin_at", "actualA"]].copy()
    te_out["model_prob"] = p_ship          # shipped v2
    te_out["v1_prob"] = p_cur              # current production (single-seed v1)
    te_out["base_prob"] = te["pred_pA"].values
    te_out.to_parquet(ART / f"{game}_oos_preds_v2.parquet", index=False)
    te_out.to_parquet(ART / f"{game}_oos_preds.parquet", index=False)  # compat
    return res


def run_ablations(game):
    df = load(game)
    tr, va, te, _ = split(df)
    yte = te["actualA"]
    out = {}
    for name, feats in ABLATIONS.items():
        _, _, p = fit_predict(tr, va, te, feats)
        out[name] = metrics(p, yte) | {"ece": ece(p, yte)}
        print(f"  {name:<11}: {out[name]}")
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    ablate = "--ablate" in sys.argv
    allres = {}
    for g in (args or ["cs2", "lol"]):
        r = run(g); allres[g] = r
        print(f"\n=== {g.upper()}  test n={r['n_test']:,} from {r['test_start']}  (ship={r['ship_feats']}) ===")
        for k in ("baseline_elo", "current_v1", "ship_v2"):
            print(f"  {k:<12}: {r[k]}")
        if ablate:
            print(f"  --- ablations (single-seed) ---")
            allres[g]["ablations"] = run_ablations(g)
    (ART / "validation_v2.json").write_text(json.dumps(allres, indent=2))
