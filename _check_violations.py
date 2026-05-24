"""Why are there paper trades with our_entry < 0.40 despite the filter?"""
import csv, datetime as dt
from pathlib import Path
ROOT = Path(__file__).resolve().parent
pt = ROOT / "output" / "sports_fade" / "paper_trades.csv"
rows = list(csv.DictReader(pt.open(encoding="utf-8")))
violations = [r for r in rows if float(r.get("our_entry", 0)) < 0.40]
print(f"Total rows: {len(rows)}")
print(f"Rows with our_entry < $0.40: {len(violations)}")
print()
print("First 5 violations (sorted by time):")
violations.sort(key=lambda r: float(r.get("timestamp", 0)))
for r in violations[:5]:
    ts = float(r.get("timestamp", 0))
    when = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).strftime("%m-%d %H:%M:%S UTC")
    print(f"  {when}  strategy={r.get('strategy')}  our_entry=${r.get('our_entry')}  "
          f"their_price={r.get('their_price','')[:8]}  our_outcome={r.get('our_outcome')[:25]}  "
          f"slug={r.get('fade_slug','')[:42]}")
print()
print("Last 5 violations:")
for r in violations[-5:]:
    ts = float(r.get("timestamp", 0))
    when = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).strftime("%m-%d %H:%M:%S UTC")
    print(f"  {when}  strategy={r.get('strategy')}  our_entry=${r.get('our_entry')}  "
          f"their_price={r.get('their_price','')[:8]}  our_outcome={r.get('our_outcome')[:25]}  "
          f"slug={r.get('fade_slug','')[:42]}")
