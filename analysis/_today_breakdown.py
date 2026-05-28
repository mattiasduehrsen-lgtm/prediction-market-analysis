"""Today's damage report — esports vs sports, by hour."""
from __future__ import annotations
import csv, json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
now = datetime.now(timezone.utc)
day_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
# Also "rolling 24h" since user is on local time
rolling24_start = now - timedelta(hours=24)

def analyze(label: str, results_csv: Path):
    if not results_csv.exists():
        print(f"\n[{label}] no results.csv")
        return
    rows = list(csv.DictReader(results_csv.open(encoding="utf-8")))
    # Today (UTC day) and rolling 24h
    today = []
    rolling = []
    for r in rows:
        if r["status"] not in ("WIN", "LOSS", "TP_SOLD", "TP_LOSS"):
            continue
        try:
            ts = float(r.get("ts") or 0)
        except Exception:
            continue
        when = datetime.fromtimestamp(ts, tz=timezone.utc)
        if when >= day_start:
            today.append(r)
        if when >= rolling24_start:
            rolling.append(r)

    def summarize(name, rs):
        if not rs:
            print(f"  {name}: no resolved trades")
            return
        pnl = sum(float(r.get("realized_pnl") or 0) for r in rs)
        cost = sum(float(r.get("cost_usd") or 0) for r in rs)
        n = len(rs)
        w = sum(1 for r in rs if r["status"] in ("WIN", "TP_SOLD"))
        roi = pnl/cost*100 if cost else 0
        print(f"  {name}: n={n}, {w}W/{n-w}L ({w/n*100:.1f}% WR), "
              f"PnL ${pnl:+.2f} on ${cost:.2f} ({roi:+.2f}% ROI)")

    print(f"\n===== {label} =====")
    summarize(f"UTC today ({day_start.date()})", today)
    summarize("rolling 24h", rolling)

    # By-hour breakdown for rolling 24h
    by_hour = defaultdict(lambda: {"n":0, "w":0, "pnl":0.0, "cost":0.0})
    for r in rolling:
        try:
            ts = float(r.get("ts") or 0)
        except Exception:
            continue
        h = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:00")
        b = by_hour[h]
        b["n"] += 1
        if r["status"] in ("WIN", "TP_SOLD"): b["w"] += 1
        b["pnl"] += float(r.get("realized_pnl") or 0)
        b["cost"] += float(r.get("cost_usd") or 0)
    if by_hour:
        print(f"\n  by hour (rolling 24h):")
        for h in sorted(by_hour):
            b = by_hour[h]
            roi = b["pnl"]/b["cost"]*100 if b["cost"] else 0
            marker = " <<" if b["pnl"] < -10 else ""
            print(f"    {h}  n={b['n']:>3}  {b['w']:>2}W/{b['n']-b['w']:<2}L  "
                  f"PnL ${b['pnl']:>+8.2f} on ${b['cost']:>6.2f}  ({roi:+.1f}%){marker}")

    # Top 10 worst trades (rolling 24h)
    losers = sorted(
        [r for r in rolling if float(r.get("realized_pnl") or 0) < -2],
        key=lambda r: float(r.get("realized_pnl") or 0)
    )[:10]
    if losers:
        print(f"\n  worst single trades (rolling 24h):")
        for r in losers:
            ts = float(r.get("ts") or 0)
            h = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%m-%d %H:%M")
            slug = (r.get("fade_slug") or "")[:42]
            print(f"    {h} {r.get('our_outcome',''):>20} @ {r.get('price'):>5} x"
                  f"{float(r.get('shares') or 0):>5.1f}  PnL ${float(r.get('realized_pnl') or 0):+7.2f}  {slug}")


analyze("ESPORTS", ROOT / "output" / "esports_fade" / "live_results.csv")
analyze("SPORTS (MLB)", ROOT / "output" / "sports_fade" / "live_results.csv")
