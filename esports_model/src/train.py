"""
Train + OOS-validate the improved win-prob model vs the Elo baseline.
Strict time-based split (no shuffling). Isotonic calibration fit on a
time-ordered validation tail of the training period only.
"""
import sys, json
from pathlib import Path
import numpy as np, pandas as pd
import pyarrow.parquet as pq
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression

ROOT = Path(__file__).resolve().parents[2]   # esports_model/src/ -> repo root
PS = ROOT / "cowork_snapshot" / "gamedata" / "pandascore"
ART = ROOT / "esports_model" / "artifacts"

FEATS = ["elo_diff", "elo_prob", "delo_diff", "glicko_mu_diff", "glicko_phi_a",
         "glicko_phi_b", "glicko_prob", "loggames_diff", "form10_diff",
         "form10_a", "form10_b", "streak_diff", "rest_a", "rest_b", "rest_diff",
         "h2h_a", "h2h_n", "num_games", "same_region", "patch", "new_a", "new_b",
         "games_a", "games_b"]


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


def run(game, test_frac=0.2):
    df = pq.read_table(ART / f"{game}_features.parquet").to_pandas()
    df["begin_at"] = pd.to_datetime(df["begin_at"], utc=True)
    df = df.sort_values("begin_at").reset_index(drop=True)
    # baseline pred from elo_history for identical rows
    eh = pq.read_table(PS / f"{game}_elo_history.parquet").to_pandas()[["match_id", "pred_pA"]]
    df = df.merge(eh, on="match_id", how="left")

    n = len(df); cut = int(n*(1-test_frac))
    val_cut = int(cut*0.85)
    tr, va, te = df.iloc[:val_cut], df.iloc[val_cut:cut], df.iloc[cut:]
    Xtr, ytr = tr[FEATS], tr["actualA"]
    Xva, yva = va[FEATS], va["actualA"]
    Xte, yte = te[FEATS], te["actualA"]

    clf = HistGradientBoostingClassifier(
        max_iter=500, learning_rate=0.03, max_depth=3, l2_regularization=1.0,
        max_leaf_nodes=15, min_samples_leaf=80, early_stopping=True,
        validation_fraction=0.15, random_state=0)
    clf.fit(Xtr, ytr)
    # isotonic calibration on the time-ordered validation slice
    raw_va = clf.predict_proba(Xva)[:, 1]
    iso = IsotonicRegression(out_of_bounds="clip").fit(raw_va, yva)
    p_te = iso.transform(clf.predict_proba(Xte)[:, 1])

    base = te["pred_pA"].values
    res = {
        "game": game, "n_total": n, "n_test": len(te),
        "test_start": str(te["begin_at"].iloc[0].date()),
        "baseline_elo": metrics(base, yte) | {"ece": ece(base, yte)},
        "model":        metrics(p_te, yte) | {"ece": ece(p_te, yte)},
    }
    # refit on train+val for the shipped model; save
    clf.fit(df.iloc[:cut][FEATS], df.iloc[:cut]["actualA"])
    import joblib
    joblib.dump({"clf": clf, "iso": iso, "feats": FEATS},
                ART / f"{game}_model.joblib")
    # attach OOS predictions for the edge backtest
    te_out = te[["match_id", "begin_at", "actualA"]].copy()
    te_out["model_prob"] = p_te; te_out["base_prob"] = base
    te_out.to_parquet(ART / f"{game}_oos_preds.parquet", index=False)
    return res


if __name__ == "__main__":
    allres = {}
    for g in (sys.argv[1:] or ["cs2", "lol"]):
        r = run(g); allres[g] = r
        print(f"\n=== {g.upper()}  test n={r['n_test']:,} from {r['test_start']} ===")
        print(f"  baseline Elo : {r['baseline_elo']}")
        print(f"  MODEL        : {r['model']}")
    (ART / "validation.json").write_text(json.dumps(allres, indent=2))
