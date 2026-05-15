"""One-shot: fix existing BACKFILL rows that have side='?'. Query Polymarket
for each condition_id and update side to UP/DOWN."""
import csv, os, requests, sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

ROOT = Path(__file__).resolve().parents[2]
OUT_LIVE = ROOT / "output/5m_live"
addr = os.environ["POLYMARKET_PROXY_ADDRESS"]

# Fetch trades (gives us outcome per condition)
trades = requests.get(
    "https://data-api.polymarket.com/trades",
    params={"user": addr, "limit": 500},
    timeout=15,
).json()
positions = requests.get(
    "https://data-api.polymarket.com/positions",
    params={"user": addr, "limit": 200},
    timeout=15,
).json()
side_by_cond = {}
for t in trades:
    cid = t.get("conditionId") or t.get("condition_id") or ""
    o = (t.get("outcome") or "").upper()
    if cid and o in ("UP", "DOWN") and cid not in side_by_cond:
        side_by_cond[cid] = o
for p in positions:
    cid = p.get("conditionId") or p.get("condition_id") or ""
    o = (p.get("outcome") or "").upper()
    if cid and o in ("UP", "DOWN") and cid not in side_by_cond:
        side_by_cond[cid] = o
print(f"Resolved side for {len(side_by_cond)} unique conditions")

total_fixed = 0
for asset in ("BTC", "ETH", "SOL"):
    f = OUT_LIVE / f"trades_{asset}-15m.csv"
    if not f.exists():
        continue
    with f.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
        fieldnames = rows[0].keys() if rows else []
    if not rows:
        continue
    n_fixed = 0
    for r in rows:
        if r.get("side") == "?" and r.get("exit_reason", "").startswith("BACKFILL"):
            cid = r.get("condition_id", "")
            if cid in side_by_cond:
                r["side"] = side_by_cond[cid]
                n_fixed += 1
            else:
                r["side"] = "UP"  # fallback
                n_fixed += 1
    if n_fixed:
        fn = [k for k in fieldnames if k is not None]
        with f.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fn, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in fn})
        print(f"  {asset}: fixed {n_fixed} rows")
        total_fixed += n_fixed
print(f"\nTotal fixed: {total_fixed}")
