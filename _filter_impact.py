"""How much did the stale-trade filter actually block today, and during what hours?"""
import json, time, datetime as dt
from pathlib import Path
from collections import defaultdict, Counter

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output" / "esports_fade"
now = time.time()
window_start = now - 30 * 3600

by_hour = defaultdict(lambda: {"signals": 0, "stale_skips_logged": 0, "scanned_marker": 0})
with (OUT / "fade_events.jsonl").open(encoding="utf-8") as f:
    for line in f:
        try: e = json.loads(line)
        except: continue
        ts = float(e.get("ts") or 0)
        if ts < window_start: continue
        hour = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).strftime("%m-%d %H:00")
        t = e.get("type", "?")
        if t == "fade_signal":
            by_hour[hour]["signals"] += 1
        elif t == "skip_stale_trade":
            by_hour[hour]["stale_skips_logged"] += 1

# The bot logs every 100th stale skip — so raw_stale_skips ≈ logged * 100
print(f"{'hour (UTC)':>14}  {'signals':>8}  {'stale_skips (raw est)':>22}  {'signal/skip ratio':>20}")
print("-" * 75)
total_signals = 0
total_stale_raw = 0
healthy_signals = 0
healthy_stale = 0
for hour in sorted(by_hour.keys()):
    s = by_hour[hour]
    raw_stale = s["stale_skips_logged"] * 100  # bot only logs every 100th
    total_signals += s["signals"]
    total_stale_raw += raw_stale
    ratio = f"{s['signals'] / max(raw_stale, 1) * 1000:.1f} signals/1k stale"
    print(f"  {hour:>12}  {s['signals']:>8}  {raw_stale:>22,}  {ratio:>20}")
    if s["signals"] > 0:
        healthy_signals += s["signals"]
        healthy_stale += raw_stale

print()
print(f"Across 30h:")
print(f"  Total fade_signals:    {total_signals:,}")
print(f"  Total stale skips:     ~{total_stale_raw:,} (raw, from 100x sampling)")
print()
print(f"During HEALTHY hours (>=1 signal):")
print(f"  Signals:               {healthy_signals:,}")
print(f"  Stale skips:           ~{healthy_stale:,}")
print(f"  Ratio:                 {healthy_signals / max(healthy_stale,1) * 100:.2f}% signals per stale-skip")
print()

# Estimate target-wallet stale skips. Currently the filter doesn't differentiate,
# so we estimate: if X% of all trades on Polymarket are from our targets,
# X% of stale skips would have been target-wallet trades we lost.
# Active target wallets = 500, total Polymarket wallets = ~100k.
# Crude estimate: ratio of fades to total unique trades = signal rate per trade.
# During the day, ~25 signals / hour vs ~50k trades scanned / hour = 0.05% are target.
print("--- Rough estimate of TARGET-wallet stale skips ---")
# bot scans ~50k trades/hour, target-rate is ~25 signals per 50k = ~0.05%
target_rate_pct = 0.05
target_stale_estimated = total_stale_raw * target_rate_pct / 100
print(f"  Of {total_stale_raw:,} stale skips, est. {target_stale_estimated:.0f} were from target wallets")
print(f"  (assumes ~0.05% of trades come from our 500 target wallets, based on signal rate)")
