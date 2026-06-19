"""LoL/LCS readiness check. Run on the laptop (fresh data)."""
import json, time, os, datetime
import pandas as pd
from pathlib import Path

ROOT = Path(r"C:\Users\matti\Desktop\prediction-market-analysis")
ES = ROOT / "cowork_snapshot" / "esports"

# 1) markets
p = ES / "clob_esports_markets.parquet"
print("markets parquet mtime:", datetime.datetime.fromtimestamp(os.path.getmtime(p)))
df = pd.read_parquet(p, columns=["slug", "game_start", "closed", "archived"])
lol = df[df["slug"].str.contains("league-|lol-|-lol|lck|lpl|lec|lcs|worlds|msi", case=False, na=False)]
op = lol[(~lol["closed"].astype(bool)) & (~lol["archived"].astype(bool))].copy()
op["gs"] = pd.to_datetime(op["game_start"], errors="coerce", utc=True)
now = pd.Timestamp.utcnow()
soon = op[(op["gs"].notna()) & (op["gs"] > now - pd.Timedelta(hours=5)) & (op["gs"] < now + pd.Timedelta(days=4))]
print(f"open LoL markets: {len(op)} | with game_start in [-5h,+4d]: {len(soon)} | slugs w/ 'lcs': {op['slug'].str.contains('lcs',case=False,na=False).sum()}")
for s in soon["slug"].head(15):
    print("   soon:", s)
if len(soon) == 0:
    print("   (no upcoming LoL markets indexed — LCS finals markets not in our index)")

# 2) LoL target wallets in the LIVE list + meta
ft = json.loads((ES / "fade_targets.json").read_text(encoding="utf-8"))
meta = ft.get("target_meta")
print(f"\nfade_targets games={ft.get('games')} scope={ft.get('scope')} total_wallets={len(ft.get('target_wallets',[]))}")
# meta may carry per-wallet game; count league if present
if isinstance(meta, list) and meta:
    games = {}
    for m in meta:
        g = m.get("game", "?")
        games[g] = games.get(g, 0) + 1
    print("LIVE wallet games breakdown:", games)
else:
    print("(no per-wallet game meta in LIVE file)")

# 3) LoL model present?
gd = ROOT / "cowork_snapshot" / "gamedata" / "pandascore"
lol_models = [f.name for f in gd.glob("*") if "lol" in f.name.lower() or "league" in f.name.lower()]
print("\nLoL model files:", lol_models or "NONE")
