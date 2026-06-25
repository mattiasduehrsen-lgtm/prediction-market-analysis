import json, math
from pathlib import Path
import numpy as np, pandas as pd, pyarrow.parquet as pq
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]   # esports_model/src/ -> esports_model
ART = ROOT / "artifacts"

fig, ax = plt.subplots(1, 3, figsize=(16, 4.6))

# (1) calibration CS2 model vs baseline
pr = pq.read_table(ART / "cs2_oos_preds.parquet").to_pandas()
for col, lab, c in [("base_prob", "Baseline Elo", "#888"), ("model_prob", "Our model", "#2b6cb0")]:
    xs, ys = [], []
    for lo in np.arange(0, 1, 0.1):
        m = (pr[col] >= lo) & (pr[col] < lo + 0.1)
        if m.sum() > 30:
            xs.append(pr[col][m].mean()); ys.append(pr.actualA[m].mean())
    ax[0].plot(xs, ys, "o-", color=c, label=lab)
ax[0].plot([0, 1], [0, 1], "--", color="k", lw=.8)
ax[0].set_title("CS2 OOS calibration"); ax[0].set_xlabel("predicted P(A)"); ax[0].set_ylabel("actual A win rate"); ax[0].legend()

# (2) edge ROI vs threshold
eb = json.loads((ART / "edge_backtest_cs2.json").read_text())
md = pd.DataFrame(eb["model"]); bd = pd.DataFrame(eb["baseline"])
ax[1].plot(md.threshold, md.roi_pct, "o-", color="#2b6cb0", label="Our model")
ax[1].plot(bd.threshold, bd.roi_pct, "s--", color="#888", label="Baseline Elo")
ax[1].axhline(0, color="k", lw=.8)
ax[1].set_title("CS2 edge vs market: ROI by threshold"); ax[1].set_xlabel("min |model-market| to bet"); ax[1].set_ylabel("ROI %"); ax[1].legend()
for _, r in md.iterrows():
    ax[1].annotate(f"n={int(r.n)}", (r.threshold, r.roi_pct), fontsize=7, xytext=(0, 6), textcoords="offset points")

# (3) dose-response
dr = pd.DataFrame(eb["dose_response"])
colors = ["#c0392b" if v < 0 else "#27ae60" for v in dr.roi_pct]
ax[2].bar(dr.bucket.astype(str), dr.roi_pct, color=colors)
ax[2].axhline(0, color="k", lw=.8)
ax[2].set_title("CS2 dose-response: ROI by disagreement size"); ax[2].set_xlabel("|model - market|"); ax[2].set_ylabel("ROI %")
for i, r in dr.iterrows():
    ax[2].annotate(f"n={int(r.n)}", (i, r.roi_pct), ha="center", fontsize=7, xytext=(0, 4 if r.roi_pct >= 0 else -10), textcoords="offset points")

plt.tight_layout()
fig.savefig(ART / "cs2_validation.png", dpi=110)
print("wrote cs2_validation.png")
