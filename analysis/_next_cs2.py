import pandas as pd
from datetime import datetime, timezone, timedelta
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
df = pd.read_parquet(ROOT/"cowork_snapshot"/"esports"/"clob_esports_markets.parquet",
                     columns=["slug","question","game_start","closed"])
df = df[df["slug"].fillna("").str.startswith("cs2-")].copy()
df["gs"] = pd.to_datetime(df["game_start"], errors="coerce", utc=True)
now = datetime.now(timezone.utc)
# series (not single-map) upcoming
import re
SM = re.compile(r"-game\d+|-map-?\d*\b|-map-|handicap|total|rounds", re.I)
up = df[(df["gs"]>now) & (~df["closed"].fillna(False)) & (~df["slug"].fillna("").str.contains(SM))].sort_values("gs")
print("now (UTC):", now.strftime("%Y-%m-%d %H:%M"))
print("upcoming cs2 SERIES markets next 24h:", int((up["gs"]<now+timedelta(hours=24)).sum()))
print("soonest:")
for r in up.head(8).itertuples():
    print(f"  {r.gs.strftime('%m-%d %H:%M')} UTC (in {(r.gs-now).total_seconds()/3600:.1f}h)  {str(r.question)[:48]}")
