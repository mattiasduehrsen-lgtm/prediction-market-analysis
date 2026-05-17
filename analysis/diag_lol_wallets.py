"""Why don't any LoL wallets qualify as fade/follow targets?

Walk through each filter step on LoL data and see how many wallets survive.
"""
import glob
import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ES = ROOT / "cowork_snapshot" / "esports"
BET = 5.0


def determine_won(df):
    sell_mask = df["side"] == "SELL"
    return np.where(
        sell_mask,
        df["outcome"] != df["winning_outcome"],
        df["outcome"] == df["winning_outcome"],
    ).astype(bool)


def pnl_for_price(price, won, bet=BET):
    p = np.clip(price.astype(float), 0.05, 0.95)
    s = bet / p
    return np.where(won, s - bet, -bet)


print("Loading shards + resolutions...")
shards = sorted(glob.glob(str(ES / "scrape" / "shards" / "*.parquet")))
df = pd.concat([pd.read_parquet(s) for s in shards], ignore_index=True)
res = pd.read_parquet(ES / "resolutions.parquet")[
    ["condition_id", "winning_outcome", "resolved", "slug"]
].rename(columns={"condition_id": "conditionId", "slug": "mkt_slug"})
df = df.merge(res, on="conditionId", how="left")
df = df[df["resolved"] & df["winning_outcome"].notna()].copy()
df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
df = df.dropna(subset=["timestamp"])
df["won"] = determine_won(df)
df["pnl"] = pnl_for_price(df["price"], df["won"].values)
df["game"] = df["mkt_slug"].fillna("").str.split("-").str[0]

print(f"\nTotal resolved trades: {len(df):,}")
print("\nGame breakdown of resolved trades:")
print(df["game"].value_counts().head(10).to_string())

# League filtering walkthrough
print("\n\n========== LEAGUE OF LEGENDS DRILLDOWN ==========")
lol = df[df["game"] == "league"].copy()
print(f"All-time LoL resolved trades: {len(lol):,}")

if not len(lol):
    print("ZERO trades. Scraper isn't capturing LoL data OR markets aren't resolving.")
    raise SystemExit

latest_ts = lol["timestamp"].max()
print(f"Latest LoL trade timestamp: {pd.Timestamp(latest_ts, unit='s')}")
print(f"Days since latest LoL trade: {(df['timestamp'].max() - latest_ts)/86400:.1f}")

# 60-day window
recent_60d = lol[lol["timestamp"] >= latest_ts - 60*86400]
print(f"\nIn last 60d of LoL data: {len(recent_60d):,} trades")
print(f"Unique LoL wallets (60d): {recent_60d['proxyWallet'].nunique():,}")

# Per-wallet aggregation
g = recent_60d.groupby("proxyWallet").agg(
    trades=("pnl","size"),
    pnl=("pnl","sum"),
    last_ts=("timestamp","max"),
).reset_index()
g["roi"] = g["pnl"]/(g["trades"]*BET)*100

print("\nFilter funnel:")
for min_tr in (5, 10, 15, 20, 30):
    qual = g[g["trades"] >= min_tr]
    print(f"  n >= {min_tr:>2}: {len(qual):>4} wallets")

losers = g[(g["trades"] >= 15) & (g["roi"] < -5)]
print(f"\n  fade-eligible (n>=15, ROI<-5%): {len(losers):>4} wallets")
winners = g[(g["trades"] >= 25) & (g["roi"] > 5)]
print(f"  follow-eligible (n>=25, ROI>5%): {len(winners):>4} wallets")

very_recent = latest_ts - 14*86400
losers_recent  = losers[losers["last_ts"] >= very_recent]
winners_recent = winners[winners["last_ts"] >= very_recent]
print(f"\n  fade-eligible + active in last 14d:   {len(losers_recent):>4}")
print(f"  follow-eligible + active in last 14d: {len(winners_recent):>4}")

# Why "last 14d" might be too strict — most recent LoL trade
df_all_max = df["timestamp"].max()
days_offset = (df_all_max - latest_ts) / 86400
if days_offset > 14:
    print(f"\n  >> LoL data is {days_offset:.0f}d behind CS2's latest trade.")
    print(f"     'last 14d' cutoff uses the BIG dataset's latest_ts, not LoL's.")
    print(f"     With LoL's own latest_ts: 'last 14d' = {pd.Timestamp(latest_ts-14*86400, unit='s')}")

# Show the top 10 best fade-candidates (most negative PnL with n>=10)
print("\nTOP 10 LoL fade candidates (most negative PnL, n>=10):")
print(g[g["trades"] >= 10].sort_values("pnl").head(10).to_string(index=False))
print()
print("TOP 10 LoL follow candidates (most positive PnL, n>=15):")
print(g[g["trades"] >= 15].sort_values("pnl", ascending=False).head(10).to_string(index=False))
