"""Evaluate CS2 model PAPER bets: resolve via CLOB winner, compute PnL at the
recorded entry price, write results + daily summary.
"""
from __future__ import annotations
import csv, json, time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "cs2_model"
BETS = OUT / "paper_bets.csv"
RESULTS = OUT / "paper_results.csv"
SUMMARY = OUT / "paper_summary.json"
CACHE = OUT / "_winner_cache.json"
BET_USD = 10.0
S = requests.Session()

def load_cache():
    if CACHE.exists():
        try: return json.loads(CACHE.read_text())
        except Exception: pass
    return {}

def winner_of(cid, cache):
    if cid in cache and cache[cid].get("winner") is not None:
        return cache[cid]["winner"]
    try:
        r = S.get(f"https://clob.polymarket.com/markets/{cid}", timeout=8)
        if r.status_code != 200: return None
        m = r.json()
    except Exception:
        return None
    if not m.get("closed"):
        cache[cid] = {"winner": None}; return None
    win = None
    for t in m.get("tokens", []) or []:
        if t.get("winner"): win = t.get("outcome")
    cache[cid] = {"winner": win}
    return win

def main():
    if not BETS.exists():
        print("no paper bets yet"); return
    rows = list(csv.DictReader(BETS.open(encoding="utf-8")))
    cache = load_cache()
    results = []
    for r in rows:
        cid = r["condition_id"]
        win = winner_of(cid, cache)
        if win is None:
            results.append({**r, "status": "OPEN", "won": "", "pnl": ""})
            continue
        try:
            entry = float(r["entry_price"])
        except Exception:
            continue
        won = 1 if r["bet_outcome"] == win else 0
        shares = BET_USD / entry if entry > 0 else 0
        pnl = round(shares - BET_USD if won else -BET_USD, 4)
        results.append({**r, "status": "WIN" if won else "LOSS", "won": won, "pnl": pnl,
                        "winner": win})
        time.sleep(0.03)
    CACHE.write_text(json.dumps(cache))
    cols = list(results[0].keys()) if results else []
    if results:
        with RESULTS.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(results)
    resolved = [r for r in results if r["status"] in ("WIN", "LOSS")]
    n = len(resolved); wins = sum(1 for r in resolved if r["status"] == "WIN")
    pnl = sum(float(r["pnl"]) for r in resolved if r["pnl"] != "")
    cost = n * BET_USD

    # Breakdown by market type (series / map / handicap / total) — shows where
    # the model edge actually holds.
    by_type = {}
    for r in resolved:
        mt = r.get("market_type", "?") or "?"
        d = by_type.setdefault(mt, {"n": 0, "wins": 0, "pnl": 0.0})
        d["n"] += 1
        d["wins"] += 1 if r["status"] == "WIN" else 0
        d["pnl"] += float(r["pnl"]) if r["pnl"] != "" else 0.0
    type_summary = {mt: {"n": d["n"], "wr_pct": round(d["wins"]/max(d["n"],1)*100, 1),
                         "pnl_usd": round(d["pnl"], 2),
                         "roi_pct": round(d["pnl"]/max(d["n"]*BET_USD, 1)*100, 2)}
                    for mt, d in sorted(by_type.items())}
    # liquidity reality: median book depth at entry
    depths = [float(r["book_depth_usd"]) for r in rows if r.get("book_depth_usd") not in ("", None)]
    depths.sort()
    med_depth = depths[len(depths)//2] if depths else 0
    summary = {
        "n_bets": len(rows), "n_resolved": n, "n_open": len(rows)-n,
        "wins": wins, "losses": n-wins,
        "wr_pct": round(wins/max(n,1)*100, 1),
        "pnl_usd": round(pnl, 2), "roi_pct": round(pnl/max(cost,1)*100, 2),
        "median_book_depth_usd": med_depth,
        "by_market_type": type_summary,
        "generated_at": time.time(),
    }
    SUMMARY.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
