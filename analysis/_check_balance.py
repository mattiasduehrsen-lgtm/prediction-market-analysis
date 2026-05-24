"""One-shot helper to reconcile our computed PnL against actual on-chain wallet.

Prints:
  - pUSD wallet balance (current)
  - Sum of share-value across all open positions (best-bid MTM)
  - Sum of realized PnL from live_results.csv
  - Net "equity" = pUSD + open MTM
  - Comparison to expected if our evaluator is right
"""
from __future__ import annotations
import csv, os, time
from pathlib import Path
import requests
from dotenv import load_dotenv
from py_clob_client_v2 import ClobClient
from py_clob_client_v2.constants import POLYGON
from py_clob_client_v2.clob_types import BalanceAllowanceParams, AssetType

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "output" / "esports_fade" / "live_results.csv"

load_dotenv()
c = ClobClient(
    "https://clob.polymarket.com",
    key=os.environ["POLYMARKET_PRIVATE_KEY"],
    chain_id=POLYGON,
    signature_type=2,
    funder=os.environ["POLYMARKET_PROXY_ADDRESS"],
)
c.set_api_creds(c.create_or_derive_api_creds())
b = c.get_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
pusd = int(b["balance"]) / 1e6
print(f"pUSD wallet balance      : ${pusd:,.2f}")

# Sum realized + count of unresolved
rows = list(csv.DictReader(RESULTS.open(encoding="utf-8")))
realized = sum(float(r["realized_pnl"] or 0) for r in rows if r["realized_pnl"] not in ("", None))
total_cost = sum(float(r["cost_usd"] or 0) for r in rows if r["status"] in ("WIN","LOSS","TP_SOLD","TP_LOSS"))
print(f"Realized PnL (csv)       : ${realized:+,.2f} on ${total_cost:,.2f} cost ({realized/max(total_cost,1)*100:+.2f}% ROI)")

# Mark open positions to market
open_rows = [r for r in rows if r["status"] == "UNRESOLVED"]
sess = requests.Session()
mv = 0.0; cb = 0.0
for r in open_rows:
    tid = r.get("token_id","")
    shares = float(r.get("shares") or 0) - float(r.get("sold_shares") or 0)
    cost = float(r.get("cost_usd") or 0) - float(r.get("sold_proceeds") or 0)
    if shares <= 0: continue
    try:
        rsp = sess.get("https://clob.polymarket.com/price",
                       params={"token_id": tid, "side": "sell"}, timeout=5)
        p = float(rsp.json().get("price") or 0.5)
    except Exception:
        p = 0.5
    mv += shares * p
    cb += cost
    time.sleep(0.03)
print(f"Open positions MTM       : ${mv:,.2f} value vs ${cb:,.2f} cost  = unrealized ${mv-cb:+,.2f}")

# Try /positions endpoint via data-api as cross-check
try:
    rsp = sess.get(
        "https://data-api.polymarket.com/positions",
        params={"user": os.environ["POLYMARKET_PROXY_ADDRESS"], "sizeThreshold": 0.01},
        timeout=10,
    )
    if rsp.status_code == 200:
        positions = rsp.json() or []
        on_chain_value = sum(float(p.get("currentValue") or 0) for p in positions)
        on_chain_cost  = sum(float(p.get("initialValue") or 0) for p in positions)
        on_chain_pnl   = sum(float(p.get("cashPnl") or 0) for p in positions)
        print(f"data-api /positions      : {len(positions)} pos, value ${on_chain_value:,.2f}, "
              f"cost ${on_chain_cost:,.2f}, cashPnl ${on_chain_pnl:+,.2f}")
except Exception as e:
    print(f"data-api /positions failed: {e}")

equity = pusd + mv
print()
print(f"Total equity (pUSD + open MTM) : ${equity:,.2f}")
print()
print("To compute lifetime PnL from this you need the starting deposit amount.")
print("If you remember roughly what you funded, the gap = lifetime PnL.")
