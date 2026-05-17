"""Diagnose LoL representation across targets / signals / live markets."""
import json
from collections import Counter
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

print("=== fade_targets.json by game ===")
ft = json.loads((ROOT / "cowork_snapshot/esports/fade_targets.json").read_text(encoding="utf-8"))
meta = ft.get("target_meta", []) or []
c = Counter(m.get("game", "?") for m in meta)
for k, v in sorted(c.items(), key=lambda x: -x[1]):
    print(f"  {k:>10}  {v}")
print(f"  total wallets in JSON: {len(ft.get('target_wallets', []))}")
print(f"  scope: {ft.get('scope', '(unset)')}")

print("\n=== follow_targets.json by game ===")
fl = json.loads((ROOT / "cowork_snapshot/esports/follow_targets.json").read_text(encoding="utf-8"))
meta = fl.get("target_meta", []) or []
c = Counter(m.get("game", "?") for m in meta)
for k, v in sorted(c.items(), key=lambda x: -x[1]):
    print(f"  {k:>10}  {v}")
print(f"  total wallets in JSON: {len(fl.get('target_wallets', []))}")

print("\n=== paper signal history by game prefix ===")
try:
    import csv
    rows = list(csv.DictReader((ROOT / "output/esports_fade/paper_trades.csv").open(encoding="utf-8")))
    c = Counter((r.get("fade_slug", "") or "").split("-")[0] for r in rows)
    for k, v in sorted(c.items(), key=lambda x: -x[1])[:10]:
        print(f"  {k:>10}  {v}")
    print(f"  total signals logged: {len(rows)}")
except FileNotFoundError:
    print("  (no paper_trades.csv)")

print("\n=== fresh CLOB esports market index by game ===")
try:
    import pandas as pd
    df = pd.read_parquet(ROOT / "cowork_snapshot/esports/clob_esports_markets.parquet")
    df["game"] = df["slug"].fillna("").str.split("-").str[0]
    print(df["game"].value_counts().head(10).to_string())
    print(f"  total markets indexed: {len(df)}")
    # How many active (not closed)?
    open_mkt = df[~df["closed"].astype(bool)]
    c = Counter(open_mkt["slug"].fillna("").str.split("-").str[0])
    print()
    print("  OPEN markets by game:")
    for k, v in sorted(c.items(), key=lambda x: -x[1])[:8]:
        print(f"    {k:>10}  {v}")
except Exception as e:
    print(f"  err: {e}")
