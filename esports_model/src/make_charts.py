import json, math
from pathlib import Path
import numpy as np, pandas as pd, pyarrow.parquet as pq
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts"

fig, ax = plt.subplots(1, 4, figsize=(21, 4.6))

# (1) calibration CS2 shipped vs baseline
pr = pq.read_table(ART / "cs2_oos_preds_v2.parquet").to_pandas()
for col, lab, c in [("base_prob", "Baseline Elo", "#888"),
                    ("v1_prob", "Current v1", "#e67e22"),
                    ("model_prob", "v2 shipped", "#2b6cb0")]:
    xs, ys = [], []
    for lo in np.arange(0, 1, 0.1):
        m = (pr[col] >= lo) & (pr[col] < lo + 0.1)
        if m.sum() > 30:
            xs.append(pr[col][m].mean()); ys.append(pr.actualA[m].mean())
    ax[0].plot(xs, ys, "o-", color=c, label=lab, ms=3)
ax[0].plot([0, 1], [0, 1], "--", color="k", lw=.8)
ax[0].set_title("CS2 OOS calibration"); ax[0].set_xlabel("predicted P(A)"); ax[0].set_ylabel("actual A win rate"); ax[0].legend(fontsize=8)

eb = json.loads((ART / "edge_backtest_cs2_v2.json").read_text())

# (2) unfiltered ROI vs threshold
md = pd.DataFrame(eb["v2_ship"]); vd = pd.DataFrame(eb["v1_current"]); bd = pd.DataFrame(eb["baseline"])
ax[1].plot(md.threshold, md.roi_pct, "o-", color="#2b6cb0", label="v2 shipped")
ax[1].plot(vd.threshold, vd.roi_pct, "^-", color="#e67e22", label="Current v1")
ax[1].plot(bd.threshold, bd.roi_pct, "s--", color="#888", label="Baseline Elo")
ax[1].axhline(0, color="k", lw=.8)
ax[1].set_title("Unfiltered: ROI by threshold"); ax[1].set_xlabel("min |model-market| to bet"); ax[1].set_ylabel("ROI %"); ax[1].legend(fontsize=8)

# (3) dose-response, shipped model
dr = pd.DataFrame(eb["v2_ship_dose"])
colors = ["#c0392b" if v < 0 else "#27ae60" for v in dr.roi_pct]
ax[2].bar(dr.bucket.astype(str), dr.roi_pct, color=colors)
ax[2].axhline(0, color="k", lw=.8)
ax[2].set_title("v2 dose-response (unfiltered)"); ax[2].set_xlabel("|model - market|"); ax[2].set_ylabel("ROI %")
for i, r in dr.iterrows():
    ax[2].annotate(f"n={int(r.n)}", (i, r.roi_pct), ha="center", fontsize=7,
                   xytext=(0, 4 if r.roi_pct >= 0 else -10), textcoords="offset points")

# (4) the v2 decision layer: mid-range before/after, per model
labels = ["baseline", "v1_current", "v2_ship"]
raw = [eb[f"{m}_R2"]["raw_mid"]["roi_pct"] for m in labels]
r2m = [eb[f"{m}_R2"]["R2_mid"]["roi_pct"] for m in labels]
x = np.arange(len(labels)); w = 0.38
ax[3].bar(x - w/2, raw, w, color="#c0392b", alpha=.75, label="mid 5-15c, unfiltered")
ax[3].bar(x + w/2, r2m, w, color="#27ae60", alpha=.9, label="mid 5-15c, tier+price filter")
ax[3].axhline(0, color="k", lw=.8)
ax[3].set_xticks(x); ax[3].set_xticklabels(["Elo", "v1 (current)", "v2 (shipped)"])
ax[3].set_title("Fillable mid-range: the v2 filter"); ax[3].set_ylabel("ROI %"); ax[3].legend(fontsize=8)
for i, (a_, b_) in enumerate(zip(raw, r2m)):
    ax[3].annotate(f"{a_:+.1f}", (i - w/2, a_), ha="center", fontsize=7, xytext=(0, -10 if a_<0 else 4), textcoords="offset points")
    ax[3].annotate(f"{b_:+.1f}", (i + w/2, b_), ha="center", fontsize=7, xytext=(0, -10 if b_<0 else 4), textcoords="offset points")

plt.tight_layout()
fig.savefig(ART / "cs2_validation_v2.png", dpi=110)
print("wrote cs2_validation_v2.png")
