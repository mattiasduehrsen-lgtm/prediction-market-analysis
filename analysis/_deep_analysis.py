"""Full diagnostic of the esports fade strategy. Slices live_results.csv
every way that could reveal what's degrading.

Sections:
  1. Daily PnL + WR trend (whole history)
  2. Rolling-50-trade WR (edge decay detection)
  3. By entry-price bucket
  4. By strategy (fade vs follow)
  5. By market type (moneyline / handicap / total / game-N)
  6. By hour of day (UTC)
  7. Entry slippage (requested vs filled price)
  8. Target-wallet decay: are wallets we fade still losing in the live window?
  9. TP-exit vs hold-to-resolution outcomes
 10. Concentration: are losses spread or clustered on few markets/wallets?
"""
from __future__ import annotations
import csv, json
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
import statistics as stats

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "esports_fade"
RESULTS = OUT / "live_results.csv"
ORDERS = OUT / "live_orders.jsonl"

def load():
    rows = list(csv.DictReader(RESULTS.open(encoding="utf-8")))
    out = []
    for r in rows:
        if r["status"] not in ("WIN", "LOSS", "TP_SOLD", "TP_LOSS"):
            continue
        try:
            r["_ts"] = float(r.get("ts") or 0)
            r["_pnl"] = float(r.get("realized_pnl") or 0)
            r["_cost"] = float(r.get("cost_usd") or 0)
            r["_price"] = float(r.get("price") or 0)
            r["_rprice"] = float(r.get("requested_price") or 0)
            r["_won"] = r["status"] in ("WIN", "TP_SOLD")
        except Exception:
            continue
        out.append(r)
    out.sort(key=lambda r: r["_ts"])
    return out

def fmt(rs, label):
    if not rs:
        return f"  {label:<28} n=0"
    n = len(rs); w = sum(1 for r in rs if r["_won"])
    pnl = sum(r["_pnl"] for r in rs); cost = sum(r["_cost"] for r in rs)
    roi = pnl/cost*100 if cost else 0
    return (f"  {label:<28} n={n:>4}  WR={w/n*100:>5.1f}%  "
            f"PnL ${pnl:>+8.2f}  ROI {roi:>+6.1f}%")

def market_type(slug):
    s = (slug or "").lower()
    if "handicap" in s or "-spread" in s or "map-handicap" in s: return "handicap"
    if "total" in s or "-over-" in s or "-under-" in s or "-o" in s.split("-")[-1:][0:1]: return "total"
    if "-game" in s or "-map-" in s or "-game1" in s or "-game2" in s or "-game3" in s: return "map/game"
    return "moneyline/series"

def main():
    rows = load()
    print("="*78)
    print(f" ESPORTS FADE — DEEP DIAGNOSTIC  ({len(rows)} resolved trades)")
    print("="*78)

    # 1. Daily
    print("\n[1] DAILY PnL + WR")
    by_day = defaultdict(list)
    for r in rows:
        d = datetime.fromtimestamp(r["_ts"], tz=timezone.utc).date().isoformat()
        by_day[d].append(r)
    cum = 0
    for d in sorted(by_day):
        rs = by_day[d]; pnl = sum(x["_pnl"] for x in rs); cum += pnl
        w = sum(1 for x in rs if x["_won"])
        print(f"  {d}  n={len(rs):>3}  WR={w/len(rs)*100:>5.1f}%  "
              f"day ${pnl:>+8.2f}  cum ${cum:>+8.2f}")

    # 2. Rolling-50 WR
    print("\n[2] ROLLING-50-TRADE WR (edge decay)")
    win = 50
    for i in range(0, len(rows), 25):
        chunk = rows[i:i+win]
        if len(chunk) < 20: continue
        w = sum(1 for r in chunk if r["_won"])
        pnl = sum(r["_pnl"] for r in chunk)
        d0 = datetime.fromtimestamp(chunk[0]["_ts"], tz=timezone.utc).strftime("%m-%d")
        d1 = datetime.fromtimestamp(chunk[-1]["_ts"], tz=timezone.utc).strftime("%m-%d")
        print(f"  trades {i:>3}-{i+len(chunk):>3} ({d0}->{d1})  "
              f"WR={w/len(chunk)*100:>5.1f}%  PnL ${pnl:>+7.2f}")

    # 3. Entry price buckets
    print("\n[3] BY ENTRY-PRICE BUCKET")
    buckets = [(0,0.45),(0.45,0.55),(0.55,0.65),(0.65,0.75),(0.75,0.85),(0.85,1.01)]
    for lo, hi in buckets:
        rs = [r for r in rows if lo <= r["_price"] < hi]
        print(fmt(rs, f"[{lo:.2f},{hi:.2f})"))

    # 4. Strategy
    print("\n[4] BY STRATEGY")
    for strat in sorted(set(r.get("strategy","") for r in rows)):
        rs = [r for r in rows if r.get("strategy")==strat]
        print(fmt(rs, strat or "(none)"))

    # 5. Market type
    print("\n[5] BY MARKET TYPE")
    for mt in ["moneyline/series","map/game","handicap","total"]:
        rs = [r for r in rows if market_type(r.get("fade_slug",""))==mt]
        print(fmt(rs, mt))

    # 6. Hour of day
    print("\n[6] BY HOUR OF DAY (UTC)")
    by_hr = defaultdict(list)
    for r in rows:
        h = datetime.fromtimestamp(r["_ts"], tz=timezone.utc).hour
        by_hr[h].append(r)
    for h in sorted(by_hr):
        print(fmt(by_hr[h], f"{h:02d}:00"))

    # 7. Slippage
    print("\n[7] ENTRY SLIPPAGE (filled - requested)")
    slips = [r["_price"]-r["_rprice"] for r in rows if r["_rprice"]>0]
    if slips:
        print(f"  mean slippage: {stats.mean(slips)*100:+.2f}c   "
              f"median: {stats.median(slips)*100:+.2f}c   "
              f"max: {max(slips)*100:+.2f}c")
        # Does high slippage correlate with losses?
        hi_slip = [r for r in rows if r["_rprice"]>0 and (r["_price"]-r["_rprice"])>0.015]
        print(fmt(hi_slip, "trades w/ >1.5c slippage"))

    # 8. Target wallet decay — are faded wallets still losing in live window?
    print("\n[8] TARGET-WALLET PERFORMANCE (the wallets we FADE)")
    print("    If our fade WR is dropping, the wallets we copy-against may have improved.")
    # Group our results by target_wallet; our win = their loss
    by_wallet = defaultdict(list)
    for r in rows:
        if r.get("strategy")=="fade":
            by_wallet[r.get("target_wallet","")].append(r)
    # Top wallets by trade count
    ranked = sorted(by_wallet.items(), key=lambda kv: -len(kv[1]))[:15]
    for wallet, rs in ranked:
        w = sum(1 for r in rs if r["_won"])
        pnl = sum(r["_pnl"] for r in rs)
        print(f"  {wallet[:14]}..  n={len(rs):>3}  our_WR={w/len(rs)*100:>5.1f}%  "
              f"our_PnL ${pnl:>+7.2f}")

    # 9. TP exits vs holds
    print("\n[9] EXIT TYPE")
    for st in ["WIN","LOSS","TP_SOLD","TP_LOSS"]:
        rs = [r for r in rows if r["status"]==st]
        print(fmt(rs, st))

    # 10. Loss concentration
    print("\n[10] LOSS CONCENTRATION")
    losers = [r for r in rows if r["_pnl"] < 0]
    by_mkt = defaultdict(float)
    for r in losers:
        by_mkt[r.get("fade_slug","")] += r["_pnl"]
    worst = sorted(by_mkt.items(), key=lambda kv: kv[1])[:12]
    print(f"  {len(losers)} losing trades; worst markets by total loss:")
    for slug, pnl in worst:
        print(f"    ${pnl:>+8.2f}  {slug[:55]}")

if __name__ == "__main__":
    main()
