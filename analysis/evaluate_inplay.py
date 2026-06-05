"""Evaluate in-play PAPER bets: resolve via CLOB series winner, compute PnL at the
recorded entry, and summarize the two unknowns (bo3 detection latency, book depth).
"""
from __future__ import annotations
import csv, json, time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "cs2_inplay"
BETS = OUT / "paper_bets.csv"
RESULTS = OUT / "paper_results.csv"
SUMMARY = OUT / "paper_summary.json"
BET_USD = 10.0
S = requests.Session()

def winner_of(cid, cache):
    if cid in cache: return cache[cid]
    try:
        r = S.get(f"https://clob.polymarket.com/markets/{cid}", timeout=8)
        if r.status_code != 200: return None
        m = r.json()
    except Exception:
        return None
    if not m.get("closed"):
        cache[cid] = None; return None
    win = None
    for t in m.get("tokens", []) or []:
        if t.get("winner"): win = t.get("outcome")
    cache[cid] = win; return win

def main():
    if not BETS.exists():
        print("no in-play paper bets yet"); return
    rows = list(csv.DictReader(BETS.open(encoding="utf-8")))
    cache = {}; results = []
    for r in rows:
        win = winner_of(r["condition_id"], cache)
        if win is None:
            results.append({**r, "status": "OPEN", "pnl": ""}); continue
        try: entry = float(r["entry_price"])
        except Exception: continue
        won = 1 if r["bet_outcome"] == win else 0
        shares = BET_USD / entry if entry > 0 else 0
        pnl = round(shares - BET_USD if won else -BET_USD, 4)
        results.append({**r, "status": "WIN" if won else "LOSS", "pnl": pnl, "winner": win})
        time.sleep(0.03)
    if results:
        cols = list(results[0].keys())
        with RESULTS.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(results)
    res = [r for r in results if r["status"] in ("WIN", "LOSS")]
    n = len(res); wins = sum(1 for r in res if r["status"] == "WIN")
    pnl = sum(float(r["pnl"]) for r in res if r["pnl"] != "")
    def fnums(col):
        out = []
        for r in rows:
            v = r.get(col)
            if v not in ("", None):
                try: out.append(float(v))
                except Exception: pass
        return out
    lags = sorted(fnums("bo3_detect_lag_s")); depths = sorted(fnums("book_depth_usd"))
    summ = {
        "n_bets": len(rows), "n_resolved": n, "n_open": len(rows) - n,
        "wins": wins, "wr_pct": round(wins / max(n, 1) * 100, 1),
        "pnl_usd": round(pnl, 2), "roi_pct": round(pnl / max(n * BET_USD, 1) * 100, 2),
        "median_bo3_lag_s": lags[len(lags)//2] if lags else None,
        "median_book_depth_usd": depths[len(depths)//2] if depths else None,
        "generated_at": time.time(),
    }
    SUMMARY.write_text(json.dumps(summ, indent=2))
    print(json.dumps(summ, indent=2))

if __name__ == "__main__":
    main()
