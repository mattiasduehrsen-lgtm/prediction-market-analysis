"""How is the sports paper bot doing? Signal volume + breakdown by sport."""
import csv, json, time
import datetime as dt
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SF = ROOT / "output" / "sports_fade"

# Read paper_trades.csv
pt = SF / "paper_trades.csv"
print("=" * 72)
print(" SPORTS PAPER BOT STATUS")
print("=" * 72)
if not pt.exists():
    print("  No paper trades yet")
    raise SystemExit
rows = list(csv.DictReader(pt.open(encoding="utf-8")))
print(f"\nTotal paper signals: {len(rows):,}")

# Time range
ts_min = ts_max = None
for r in rows:
    try: t = float(r["timestamp"])
    except: continue
    if ts_min is None or t < ts_min: ts_min = t
    if ts_max is None or t > ts_max: ts_max = t
if ts_min:
    print(f"First signal: {dt.datetime.fromtimestamp(ts_min, tz=dt.timezone.utc).strftime('%m-%d %H:%M UTC')}")
    print(f"Last signal:  {dt.datetime.fromtimestamp(ts_max, tz=dt.timezone.utc).strftime('%m-%d %H:%M UTC')}")
    span_hours = (ts_max - ts_min) / 3600
    if span_hours > 0:
        print(f"Span: {span_hours:.1f}h, rate: {len(rows)/span_hours:.1f} signals/hour")

# Group by sport (slug prefix)
def sport_of(slug):
    s = (slug or "").lower()
    if s.startswith("nhl-"): return "nhl"
    if s.startswith("nba-"): return "nba"
    if s.startswith("mlb-"): return "mlb"
    if s.startswith("atp-") or s.startswith("wta-"): return "tennis"
    if s.startswith(("epl-","laliga-","champions-","uefa-","fifa-")): return "soccer"
    return "other"

by_sport = Counter()
by_sport_unique = defaultdict(set)
by_target_wallet = Counter()
entry_prices = []
for r in rows:
    sp = sport_of(r.get("fade_slug",""))
    by_sport[sp] += 1
    by_sport_unique[sp].add(r.get("fade_slug",""))
    by_target_wallet[r.get("target_wallet","")] += 1
    try: entry_prices.append(float(r.get("our_entry",0)))
    except: pass

print()
print(f"{'Sport':<10} {'signals':>9} {'markets':>9} {'avg/mkt':>9}")
print("-" * 50)
for sp, n in by_sport.most_common():
    n_mkts = len(by_sport_unique[sp])
    avg = n / max(n_mkts, 1)
    print(f"{sp:<10} {n:>9,} {n_mkts:>9,} {avg:>9.1f}")

# Top 5 most-active target wallets
print()
print("Top 5 most-active fadeable wallets (this paper run):")
for w, n in by_target_wallet.most_common(5):
    print(f"  {w}  {n} signals")

# Entry price distribution
print()
if entry_prices:
    buckets = Counter()
    for p in entry_prices:
        if p < 0.40: buckets["<$0.40 (filter violation!)"] += 1
        elif p < 0.50: buckets["$0.40-0.50"] += 1
        elif p < 0.60: buckets["$0.50-0.60"] += 1
        elif p < 0.70: buckets["$0.60-0.70"] += 1
        elif p < 0.80: buckets["$0.70-0.80"] += 1
        elif p < 0.90: buckets["$0.80-0.90"] += 1
        else: buckets["$0.90+"] += 1
    print("Entry-price distribution:")
    for b in ["<$0.40 (filter violation!)","$0.40-0.50","$0.50-0.60",
              "$0.60-0.70","$0.70-0.80","$0.80-0.90","$0.90+"]:
        if b in buckets:
            print(f"  {b:<32} {buckets[b]:>5}")

# Recent activity sample
print()
print("Most recent 5 signals:")
for r in rows[-5:]:
    ts = float(r.get("timestamp") or 0)
    when = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).strftime("%H:%M:%S")
    print(f"  {when}  FADE {(r.get('our_outcome') or '')[:20]:<20} @${r.get('our_entry')}  slug={(r.get('fade_slug') or '')[:42]}")

# Check fade_events for skip counts (filter activity)
print()
print("Filter activity (skip events):")
ev_path = SF / "fade_events.jsonl"
skip_counts = Counter()
if ev_path.exists():
    with ev_path.open(encoding="utf-8") as f:
        for line in f:
            try: e = json.loads(line)
            except: continue
            if "skip" in e.get("type",""):
                skip_counts[e.get("type")] += 1
for t, c in skip_counts.most_common():
    print(f"  {c:>5}  {t}")
