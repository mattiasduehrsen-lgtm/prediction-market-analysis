"""Diagnostic for the v1.46 on-chain CU gate: parquet freshness + CS2 windows
open right now. Run on the laptop with the project venv."""
import os, time, datetime
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ES = ROOT / "cowork_snapshot" / "esports" / "clob_esports_markets.parquet"
PRE, POST = 2 * 3600, 5 * 3600

mtime = os.path.getmtime(ES)
print("parquet mtime:", datetime.datetime.fromtimestamp(mtime),
      f"({(time.time()-mtime)/3600:.1f}h old)")

df = pd.read_parquet(ES, columns=["slug", "game_start", "closed", "archived"])
cs = df[df["slug"].str.contains("cs2-|-cs2|csgo-|-csgo", case=False, na=False)]
cs = cs[(~cs["closed"].astype(bool)) & (~cs["archived"].astype(bool))]
gs = pd.to_datetime(cs["game_start"], errors="coerce", utc=True).dropna()
now = time.time()
wins = [(t.timestamp() - PRE, t.timestamp() + POST) for t in gs]
open_now = sum(1 for s, e in wins if s <= now <= e)
print(f"total CS2 windows: {len(wins)} | OPEN NOW: {open_now}  -> gate would be "
      f"{'ACTIVE' if open_now else 'IDLE'}")
future = sorted(t.timestamp() for t in gs if t.timestamp() > now)
if future:
    print(f"next match start in {(future[0]-now)/3600:.1f}h "
          f"(gate opens {(future[0]-PRE-now)/3600:.1f}h from now)")
