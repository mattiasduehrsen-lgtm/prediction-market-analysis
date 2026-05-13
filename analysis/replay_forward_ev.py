"""
Forward-EV check: when brain says "degraded" (correctly), does the NEXT trade
actually have worse EV than when brain says "strong"?

This is the real test - does the brain's correctly-classified regime call have
PREDICTIVE value, or is it just descriptive of past?

Method: same windows as replay_brain_test.py (no API calls), but compute the
NEXT trade's actual pnl after each 10-trade window.
"""
import csv
import io
from pathlib import Path

TRADES_CSV = Path(r"cowork_snapshot/5m_trading/trades.csv")
if not TRADES_CSV.exists():
    TRADES_CSV = Path("output/5m_trading/trades.csv")

with TRADES_CSV.open(encoding="utf-8") as fh:
    lines = fh.readlines()
header_idx = next(i for i, l in enumerate(lines) if l.startswith("position_id,"))
reader = csv.DictReader(io.StringIO("".join(lines[header_idx:])))
all_trades = [r for r in reader if r.get("strategy") == "mean_reversion"
              and r.get("window") in ("15m", "4h")
              and r.get("exit_reason") not in ("", "open")]

def _f(s):
    try: return float(s)
    except: return 0.0

print(f"Loaded {len(all_trades)} resolved MR trades")

# Also apply v1.28 share/TP corrections to next_pnl for honest accounting
def corrected_pnl(row):
    DISCOUNT = 0.955
    size_usd = _f(row.get("size_usd"))
    entry_price = _f(row.get("entry_price"))
    if entry_price <= 0:
        return _f(row.get("pnl_usd"))
    correct_shares = round((size_usd / entry_price) * DISCOUNT, 2)
    if row.get("exit_reason") == "take_profit":
        exit_p = _f(row.get("take_profit"))
    else:
        exit_p = _f(row.get("exit_price"))
    return correct_shares * exit_p - size_usd


def get_windows(asset, target_wr_range, max_samples=20):
    """Find all non-overlapping 10-trade windows for asset where WR in range."""
    asset_trades = sorted(
        [t for t in all_trades if t.get("asset","").upper() == asset
         and t.get("window") == "15m"],
        key=lambda t: _f(t.get("opened_at")),
    )
    out = []
    i = 0
    while i <= len(asset_trades) - 11:
        window = asset_trades[i:i+10]
        wins = sum(1 for t in window if _f(t.get("pnl_usd")) > 0)
        if target_wr_range[0] <= wins <= target_wr_range[1]:
            next_trade = asset_trades[i+10]
            out.append({
                "wins": wins,
                "next_pnl_old": _f(next_trade.get("pnl_usd")),
                "next_pnl_v1_28": corrected_pnl(next_trade),
            })
            i += 1   # OVERLAP allowed for more samples
        else:
            i += 1
        if len(out) >= max_samples:
            break
    return out


def summarize(label, samples):
    n = len(samples)
    if n == 0:
        print(f"  {label}: n=0")
        return
    old_evs = [s["next_pnl_old"] for s in samples]
    new_evs = [s["next_pnl_v1_28"] for s in samples]
    old_mean = sum(old_evs) / n
    new_mean = sum(new_evs) / n
    wins = sum(1 for v in new_evs if v > 0)
    print(f"  {label:<10} n={n:>3}  next_trade WR={wins/n*100:.0f}%  "
          f"EV_old=${old_mean:+.3f}  EV_v1.28=${new_mean:+.3f}")


print(f"\n=== Forward EV by prior 10-trade WR (per asset) ===\n")
for asset in ["BTC", "ETH", "SOL"]:
    deg  = get_windows(asset, (0, 2),  max_samples=200)
    nor  = get_windows(asset, (4, 6),  max_samples=200)
    stro = get_windows(asset, (7, 10), max_samples=200)
    print(f"{asset}:")
    summarize("degraded", deg)
    summarize("normal  ", nor)
    summarize("strong  ", stro)
    print()

print(f"=== Forward EV by prior 10-trade WR (ALL assets pooled) ===\n")
all_deg  = []; all_nor = []; all_stro = []
for asset in ["BTC", "ETH", "SOL"]:
    all_deg.extend(get_windows(asset, (0, 2),  max_samples=200))
    all_nor.extend(get_windows(asset, (4, 6),  max_samples=200))
    all_stro.extend(get_windows(asset, (7, 10), max_samples=200))
summarize("degraded", all_deg)
summarize("normal  ", all_nor)
summarize("strong  ", all_stro)

# Check: is the strong-vs-degraded gap statistically meaningful?
if all_deg and all_stro:
    import math
    def stat(samples):
        evs = [s["next_pnl_v1_28"] for s in samples]
        n = len(evs)
        mean = sum(evs) / n
        var = sum((v-mean)**2 for v in evs) / max(1, n-1)
        return n, mean, math.sqrt(var)

    n_d, m_d, s_d = stat(all_deg)
    n_s, m_s, s_s = stat(all_stro)
    se = math.sqrt(s_d**2/n_d + s_s**2/n_s)
    delta = m_s - m_d
    t = delta / se if se > 0 else 0
    print(f"\nStrong - Degraded next-trade EV gap: ${delta:+.3f}/trade  (SE=${se:.3f}, t={t:+.2f})")
    if t > 2:
        print("  -> Brain regime call has FORWARD predictive value (p<0.05)")
    elif t > 1:
        print("  -> Modest forward signal (suggestive)")
    else:
        print("  -> No forward signal - brain classification doesn't predict next-trade outcome")
