"""How many filter violations in last 6h vs last 1h?"""
import csv, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent
pt = ROOT / "output" / "sports_fade" / "paper_trades.csv"
now = time.time()
windows = [("last 1h", 3600), ("last 3h", 10800), ("last 6h", 21600),
           ("last 12h", 43200), ("all", 86400 * 7)]
rows = list(csv.DictReader(pt.open(encoding="utf-8")))
for label, span in windows:
    cutoff = now - span
    recent = [r for r in rows if float(r.get("timestamp", 0)) > cutoff]
    viol = [r for r in recent if float(r.get("our_entry", 0)) < 0.40]
    print(f"  {label:>10}: {len(recent):>4} signals, {len(viol):>3} violations")
