"""Evaluate sports paper trades against actual market resolutions.

Reads output/sports_fade/paper_trades.csv (signals the bot logged), looks up
each market's winner via the CLOB API, computes hypothetical PnL using the
$5 bet size and our entry price.

Writes:
  output/sports_fade/paper_results.csv  (per-trade outcomes)
  output/sports_fade/paper_daily_pnl.json  (today's totals)

This is the sports analog to analysis/evaluate_live.py for esports.
Designed to run as a cron every ~10 min so we always have fresh paper PnL.
"""
from __future__ import annotations
import csv
import datetime as dt
import json
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "output" / "sports_fade"
PT_CSV = OUT_DIR / "paper_trades.csv"
RESULTS_CSV = OUT_DIR / "paper_results.csv"
DAILY_JSON = OUT_DIR / "paper_daily_pnl.json"
WINNER_CACHE = OUT_DIR / "_winner_cache.json"

BET_USD = 5.0
CLOB_URL = "https://clob.polymarket.com/markets/{cid}"


def load_winner_cache():
    if WINNER_CACHE.exists():
        try: return json.loads(WINNER_CACHE.read_text(encoding="utf-8"))
        except Exception: pass
    return {}


def save_winner_cache(d):
    try: WINNER_CACHE.write_text(json.dumps(d), encoding="utf-8")
    except Exception: pass


def fetch_market(cid, session):
    """Fetch market info, return {closed, winning_outcome} or None."""
    try:
        r = session.get(CLOB_URL.format(cid=cid), timeout=10)
        if r.status_code != 200: return None
        m = r.json()
    except Exception:
        return None
    if not m: return None
    closed = bool(m.get("closed", False))
    tokens = m.get("tokens") or []
    win_outcome = None
    if isinstance(tokens, list):
        winners = [t for t in tokens if isinstance(t, dict) and t.get("winner")]
        if len(winners) == 1:
            win_outcome = winners[0].get("outcome")
    return {"closed": closed, "winning_outcome": win_outcome}


def main():
    if not PT_CSV.exists():
        print("No paper_trades.csv yet")
        return

    rows = list(csv.DictReader(PT_CSV.open(encoding="utf-8")))
    print(f"Loaded {len(rows):,} paper signals")

    winner_cache = load_winner_cache()
    session = requests.Session()
    today_utc = dt.datetime.now(dt.timezone.utc).date().isoformat()

    n_new_resolved = 0
    results = []
    for r in rows:
        cid = r.get("fade_condition", "")
        if not cid: continue
        cached = winner_cache.get(cid)
        if cached is None or cached.get("winning_outcome") is None:
            info = fetch_market(cid, session)
            if info is None: continue
            winner_cache[cid] = info
            if info.get("winning_outcome"):
                n_new_resolved += 1
            time.sleep(0.05)
            cached = info
        win_outcome = cached.get("winning_outcome")
        if win_outcome is None:
            results.append({**r, "status": "UNRESOLVED", "realized_pnl": "", "cost_usd": ""})
            continue
        our_outcome = r.get("our_outcome", "")
        try: our_entry = float(r.get("our_entry") or 0)
        except (TypeError, ValueError): our_entry = 0
        if our_entry <= 0: continue
        won = (our_outcome == win_outcome)
        cost = BET_USD
        shares = BET_USD / our_entry
        pnl = round(shares - cost if won else -cost, 4)
        results.append({**r, "status": "WIN" if won else "LOSS",
                         "realized_pnl": pnl, "cost_usd": cost,
                         "winning_outcome": win_outcome})

    save_winner_cache(winner_cache)
    if n_new_resolved:
        print(f"  Resolved {n_new_resolved} new markets via CLOB API")

    # Write results.csv
    if results:
        cols = list(results[0].keys())
        with RESULTS_CSV.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(results)

    # Compute stats
    resolved = [r for r in results if r["status"] in ("WIN", "LOSS")]
    today_resolved = [r for r in resolved if r.get("timestamp") and
                       dt.datetime.fromtimestamp(float(r["timestamp"]),
                                                  tz=dt.timezone.utc).date().isoformat() == today_utc]
    n_w = sum(1 for r in resolved if r["status"] == "WIN")
    n_l = sum(1 for r in resolved if r["status"] == "LOSS")
    pnl = sum(float(r["realized_pnl"]) for r in resolved if r["realized_pnl"] != "")
    cost = sum(float(r["cost_usd"]) for r in resolved if r["cost_usd"] != "")

    # Per-sport breakdown
    def sport_of(slug):
        s = (slug or "").lower()
        if s.startswith("nhl-"): return "nhl"
        if s.startswith("nba-"): return "nba"
        if s.startswith("mlb-"): return "mlb"
        if s.startswith("atp-") or s.startswith("wta-"): return "tennis"
        return "other"
    by_sport = {}
    for r in resolved:
        sp = sport_of(r.get("fade_slug", ""))
        s = by_sport.setdefault(sp, {"n":0,"w":0,"l":0,"pnl":0.0,"cost":0.0})
        s["n"] += 1
        if r["status"] == "WIN": s["w"] += 1
        else: s["l"] += 1
        s["pnl"] += float(r["realized_pnl"] or 0)
        s["cost"] += float(r["cost_usd"] or 0)

    today_w = sum(1 for r in today_resolved if r["status"] == "WIN")
    today_l = sum(1 for r in today_resolved if r["status"] == "LOSS")
    today_pnl = sum(float(r["realized_pnl"]) for r in today_resolved if r["realized_pnl"] != "")

    daily_data = {
        "date": today_utc,
        "today_resolved": len(today_resolved),
        "today_wins": today_w, "today_losses": today_l,
        "today_pnl_usd": round(today_pnl, 2),
        "lifetime_resolved": len(resolved),
        "lifetime_wins": n_w, "lifetime_losses": n_l,
        "lifetime_pnl_usd": round(pnl, 2),
        "lifetime_cost_usd": round(cost, 2),
        "lifetime_wr_pct": round(n_w / max(len(resolved), 1) * 100, 2),
        "lifetime_roi_pct": round(pnl / max(cost, 1) * 100, 2),
        "by_sport": {k: {**v, "wr_pct": round(v["w"]/max(v["n"],1)*100, 2),
                          "roi_pct": round(v["pnl"]/max(v["cost"],1)*100, 2),
                          "pnl": round(v["pnl"], 2)}
                      for k, v in by_sport.items()},
    }
    DAILY_JSON.write_text(json.dumps(daily_data, indent=2), encoding="utf-8")

    # Console report
    print(f"\n=== SPORTS PAPER RESULTS ===")
    print(f"Lifetime: {len(resolved):,} resolved, {n_w} W / {n_l} L "
          f"({n_w/max(len(resolved),1)*100:.1f}% WR)")
    print(f"  PnL: ${pnl:+,.2f} on ${cost:,.2f} cost  ({pnl/max(cost,1)*100:+.2f}% ROI)")
    print(f"Today ({today_utc}): {len(today_resolved):,} resolved, "
          f"{today_w} W / {today_l} L, PnL ${today_pnl:+,.2f}")
    print(f"\nPer-sport:")
    for sp, s in sorted(by_sport.items(), key=lambda x: -x[1]["pnl"]):
        sign = "+" if s["pnl"]>=0 else "-"
        print(f"  {sp:<8} n={s['n']:>5,} W/L={s['w']}/{s['l']:<4} "
              f"WR={s['w']/max(s['n'],1)*100:>4.1f}%  PnL={sign}${abs(s['pnl']):,.2f}  "
              f"ROI={s['pnl']/max(s['cost'],1)*100:+.2f}%")


if __name__ == "__main__":
    main()
