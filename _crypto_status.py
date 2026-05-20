"""One-off: aggregate stats for the 15m crypto bot PAPER trades."""
import csv, datetime as dt, io, sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

for asset in ("BTC", "ETH", "SOL"):
    p = Path(f"output/5m_live/trades_{asset}-15m.csv")
    if not p.exists():
        print(f"{asset}: file missing"); continue
    rows = list(csv.DictReader(p.open(encoding="utf-8")))

    def fpnl(r):
        try: return float(r.get("pnl_usd") or r.get("pnl") or 0)
        except (TypeError, ValueError): return 0.0
    def is_backfill(r):
        return (str(r.get("entry_order_id","")).startswith("BACKFILL")
                or str(r.get("position_id","")).startswith("bf_"))
    closed = [r for r in rows if r.get("state") in ("closed","TP_SOLD","LOSS","WIN")]
    bf = [r for r in closed if is_backfill(r)]
    real = [r for r in closed if not is_backfill(r)]
    open_now = [r for r in rows if r.get("state") in ("open","pending_exit")]

    print(f"== {asset} =====================")
    print(f"  total rows         : {len(rows)}")
    print(f"  closed             : {len(closed)}  (backfill: {len(bf)}, real: {len(real)})")
    print(f"  open / pending     : {len(open_now)}")

    real_pnl = sum(fpnl(r) for r in real)
    print(f"  REAL trades PnL    : ${real_pnl:+.2f}")
    if real:
        wins   = sum(1 for r in real if fpnl(r) > 0)
        losses = sum(1 for r in real if fpnl(r) < 0)
        if wins + losses > 0:
            print(f"  REAL W/L           : {wins}W / {losses}L  ({wins/(wins+losses)*100:.0f}% WR)")
        # Latest real trade timestamp
        def get_ts(r):
            try: return float(r.get("opened_at") or r.get("entry_ts") or 0)
            except: return 0.0
        latest = max(real, key=get_ts)
        ts = get_ts(latest)
        if ts:
            age_days = (dt.datetime.now(dt.timezone.utc).timestamp() - ts) / 86400
            print(f"  latest REAL trade  : {dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc):%Y-%m-%d %H:%M UTC} ({age_days:.1f} days ago)")

        # Exit-reason breakdown for real trades
        from collections import Counter
        reasons = Counter(r.get("exit_reason","?") for r in real)
        print(f"  exit reasons       : {dict(reasons.most_common(5))}")

    # Most-recent open positions
    if open_now:
        print(f"  open trades        :")
        for r in open_now[-3:]:
            print(f"    {r.get('asset','?')} {r.get('side','?'):<4} entry={r.get('entry_price','?')} state={r.get('state','?')}")
    print()
