"""How far back / forward our esports data goes.

Reports the time window covered by:
  - The historical scrape shards (used to identify wallets to follow/fade)
  - The bot's own LIVE orders log (real-money trades since deployment)
"""
import glob
import json
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ES   = ROOT / "cowork_snapshot" / "esports"
LIVE = ROOT / "output" / "esports_fade" / "live_orders.jsonl"
PAPER = ROOT / "output" / "esports_fade" / "paper_trades.csv"

print("=" * 60)
print("HISTORICAL SCRAPE  (wallet-behavior dataset)")
print("=" * 60)
shards = sorted(glob.glob(str(ES / "scrape" / "shards" / "*.parquet")))
print(f"Shard files            : {len(shards)}")

df = pd.concat([pd.read_parquet(s, columns=["timestamp", "proxyWallet", "slug"])
                for s in shards], ignore_index=True)
df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
df = df.dropna(subset=["timestamp"])
first_ts = df["timestamp"].min()
last_ts  = df["timestamp"].max()
span_days = (last_ts - first_ts) / 86400

print(f"Total trades           : {len(df):,}")
print(f"Unique wallets         : {df['proxyWallet'].nunique():,}")
print(f"Unique market slugs    : {df['slug'].nunique():,}")
print(f"Earliest trade         : {pd.Timestamp(first_ts, unit='s')}")
print(f"Latest trade           : {pd.Timestamp(last_ts, unit='s')}")
print(f"Span                   : {span_days:.1f} days")

df["game"] = df["slug"].fillna("").str.split("-").str[0]
print()
print("Per-game coverage:")
print(f"  {'game':>10}  {'trades':>10}  {'first':<12}  {'last':<12}  {'days':>6}")
for g, n in df["game"].value_counts().head(8).items():
    sub = df[df["game"] == g]
    a = pd.Timestamp(sub["timestamp"].min(), unit="s").date()
    b = pd.Timestamp(sub["timestamp"].max(), unit="s").date()
    print(f"  {g:>10}  {n:>10,}  {str(a):<12}  {str(b):<12}  {(b-a).days:>6}")

print()
print("=" * 60)
print("LIVE BOT TRADES  (real-money window)")
print("=" * 60)
if LIVE.exists():
    fst = lst = None
    n_buy = n_sell = 0
    for l in LIVE.open(encoding="utf-8"):
        l = l.strip()
        if not l:
            continue
        try:
            d = json.loads(l)
        except json.JSONDecodeError:
            continue
        ts = float(d.get("ts") or 0)
        if not ts:
            continue
        fst = min(fst, ts) if fst else ts
        lst = max(lst, ts) if lst else ts
        side = d.get("side", "BUY")
        if side == "BUY":
            n_buy += 1
        elif side == "SELL":
            n_sell += 1
    print(f"BUY orders             : {n_buy}")
    print(f"SELL records (inferred): {n_sell}")
    print(f"First order            : {pd.Timestamp(fst, unit='s')}")
    print(f"Last order             : {pd.Timestamp(lst, unit='s')}")
    print(f"Span                   : {(lst-fst)/86400:.1f} days")
else:
    print("  (no live_orders.jsonl yet)")

print()
print("=" * 60)
print("PAPER BOT TRADES")
print("=" * 60)
if PAPER.exists():
    pdf = pd.read_csv(PAPER)
    if "timestamp" in pdf.columns:
        pdf["timestamp"] = pd.to_numeric(pdf["timestamp"], errors="coerce")
        pdf = pdf.dropna(subset=["timestamp"])
        if len(pdf):
            a = pd.Timestamp(pdf["timestamp"].min(), unit="s")
            b = pd.Timestamp(pdf["timestamp"].max(), unit="s")
            print(f"Signals                : {len(pdf):,}")
            print(f"First signal           : {a}")
            print(f"Last signal            : {b}")
            print(f"Span                   : {(b-a).total_seconds()/86400:.1f} days")
else:
    print("  (no paper_trades.csv yet)")
