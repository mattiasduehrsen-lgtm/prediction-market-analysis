"""Cross-reference losing wallets across sports + esports.

Tells us:
  - Do the same wallets lose money on multiple categories?
  - Is there a "core whale" group bleeding everywhere, or are losers
    sport-specific?
  - What's the union of all losing wallets across all categories?
  - Bet size + frequency distribution for the unified loser pool
"""
import json
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent

# Load losing-wallets parquets from each recon
sport_dirs = sorted([d for d in (ROOT / "cowork_snapshot").iterdir()
                     if d.is_dir() and d.name.endswith("_recon")])
print(f"Found recon directories: {[d.name for d in sport_dirs]}\n")

per_sport_losers = {}
for d in sport_dirs:
    sport = d.name.replace("_recon", "")
    f = d / "losing_wallets.parquet"
    if not f.exists():
        print(f"  [skip] {sport}: no losing_wallets.parquet")
        continue
    df = pd.read_parquet(f)
    per_sport_losers[sport] = df
    print(f"  {sport}: {len(df)} qualifying losing wallets, "
          f"top loser ${df.iloc[0]['pnl']:.0f}")

# Also load esports current target list
es_targets_path = ROOT / "cowork_snapshot" / "esports" / "fade_targets.json"
es_wallets = set()
if es_targets_path.exists():
    try:
        es_data = json.loads(es_targets_path.read_text(encoding="utf-8"))
        es_wallets = set(w.lower() for w in es_data.get("target_wallets", []))
        print(f"  esports (live targets): {len(es_wallets)} wallets")
    except Exception as e:
        print(f"  [skip] esports targets: {e}")

print()
print("=" * 78)
print(" CROSS-SPORT OVERLAP")
print("=" * 78)

# Union of all losers across new-sport recons
all_loser_sets = {s: set(df.index.str.lower()) for s, df in per_sport_losers.items()}
if es_wallets:
    all_loser_sets["esports"] = es_wallets

# Pairwise overlap
sports = list(all_loser_sets.keys())
print(f"\n{'':>10} " + " ".join(f"{s:>7}" for s in sports))
for s1 in sports:
    row = [f"{s1:>10}"]
    for s2 in sports:
        if s1 == s2:
            row.append(f"{len(all_loser_sets[s1]):>7,}")
        else:
            overlap = len(all_loser_sets[s1] & all_loser_sets[s2])
            row.append(f"{overlap:>7,}")
    print(" ".join(row))

# Multi-category losers (in 2+ buckets)
all_losers = set()
for s in all_loser_sets.values(): all_losers.update(s)
multi_cat = {}  # wallet -> set of categories
for s, wset in all_loser_sets.items():
    for w in wset:
        multi_cat.setdefault(w, set()).add(s)
in_2_plus = [w for w, cats in multi_cat.items() if len(cats) >= 2]
in_3_plus = [w for w, cats in multi_cat.items() if len(cats) >= 3]

print()
print(f"Total UNIQUE wallets across all categories: {len(all_losers):,}")
print(f"Wallets losing in 2+ categories:           {len(in_2_plus):,}")
print(f"Wallets losing in 3+ categories:           {len(in_3_plus):,}")

if in_3_plus:
    print(f"\nTop 'omni-loser' wallets (losing in 3+ categories):")
    for w in in_3_plus[:10]:
        cats = sorted(multi_cat[w])
        print(f"  {w}  in: {cats}")

# Estimate of new wallets vs already-tracked
new_wallets = all_losers - es_wallets
print(f"\nLosers NOT in current esports target list: {len(new_wallets):,}")
print(f"  (these are candidates for the wider target pool)")
