"""
Synthetic replay test for the v1.33 WindowBrain prompt.

Identifies clear DEGRADED and STRONG 10-trade windows from PAPER trade history,
feeds them to the brain, and verifies the brain correctly classifies regime.

Decision rule:
  - DEGRADED windows (0-2 wins out of 10):  expect brain `mr_edge` = "degraded"
  - STRONG  windows (7+ wins out of 10):     expect brain `mr_edge` = "strong"
  - NORMAL  windows (3-6 wins out of 10):    expect brain `mr_edge` = "normal"

Cost: ~5 each category x 3 = 15 calls @ ~$0.002 = $0.03.

Run on laptop where ANTHROPIC_API_KEY is in .env:
  .venv\Scripts\python.exe replay_brain_test.py
"""
from __future__ import annotations

import csv
import io
import os
import sys
import time
from pathlib import Path
from collections import deque

from dotenv import load_dotenv
load_dotenv()

# Force enable brain even if BRAIN_ENABLED unset
os.environ.setdefault("BRAIN_ENABLED", "true")

from src.bot.window_brain import WindowBrain, NEUTRAL, BRAIN_MODEL

# ── Locate trades.csv ─────────────────────────────────────────────────────────
TRADES_CSV = Path("output/5m_trading/trades.csv")
if not TRADES_CSV.exists():
    print(f"FAIL: {TRADES_CSV} not found")
    sys.exit(1)

# ── Load trades (skip SSH warning lines if any) ───────────────────────────────
with TRADES_CSV.open(encoding="utf-8") as fh:
    lines = fh.readlines()
header_idx = next(i for i, l in enumerate(lines) if l.startswith("position_id,"))
reader = csv.DictReader(io.StringIO("".join(lines[header_idx:])))
all_trades = [r for r in reader if r.get("strategy") == "mean_reversion"
              and r.get("window") in ("15m", "4h")
              and r.get("exit_reason") not in ("", "open")]

print(f"Loaded {len(all_trades)} resolved MR trades")

# Sort chronologically per asset
def _f(s):
    try: return float(s)
    except: return 0.0
def _i(s):
    try: return int(float(s))
    except: return 0

# ── Build rolling windows per asset ──────────────────────────────────────────
def find_windows(trades, target_wr_range, max_samples=5, asset_filter="BTC"):
    """Return up to max_samples non-overlapping 10-trade windows where WR ∈ target_wr_range."""
    asset_trades = [t for t in trades if t.get("asset","").upper() == asset_filter
                    and t.get("window") == "15m"]   # 15m only - more data
    asset_trades.sort(key=lambda t: _f(t.get("opened_at")))

    samples = []
    i = 0
    while i <= len(asset_trades) - 10 and len(samples) < max_samples:
        window = asset_trades[i:i+10]
        wins = sum(1 for t in window if _f(t.get("pnl_usd")) > 0)
        if target_wr_range[0] <= wins <= target_wr_range[1]:
            # Reconstruct what WindowBrain history would look like
            history = []
            for t in window:
                history.append({
                    "side":        t.get("side", "?"),
                    "entry_price": _f(t.get("entry_price")),
                    "exit_reason": t.get("exit_reason", "?"),
                    "pnl_usd":     _f(t.get("pnl_usd")),
                    "won":         _f(t.get("pnl_usd")) > 0,
                    "edge":        _f(t.get("edge")) if t.get("edge") else 0.0,
                })
            # Next trade (after window) is the "candidate" we ask brain about
            if i + 10 < len(asset_trades):
                next_trade = asset_trades[i + 10]
                samples.append({
                    "window": window, "history": history, "wins": wins,
                    "next_side": next_trade.get("side"),
                    "next_entry": _f(next_trade.get("entry_price")),
                    "next_pnl": _f(next_trade.get("pnl_usd")),
                    "next_won": _f(next_trade.get("pnl_usd")) > 0,
                    "asset": asset_filter,
                })
            i += 10   # non-overlapping
        else:
            i += 1
    return samples


# ── Find samples ──────────────────────────────────────────────────────────────
print("\nSearching for clear regime windows (BTC 15m)...")
degraded_samples = find_windows(all_trades, (0, 2), max_samples=5, asset_filter="BTC")
print(f"  DEGRADED (0-2/10 wins): found {len(degraded_samples)} non-overlapping windows")

strong_samples = find_windows(all_trades, (7, 10), max_samples=5, asset_filter="BTC")
print(f"  STRONG   (7-10/10 wins): found {len(strong_samples)} non-overlapping windows")

normal_samples = find_windows(all_trades, (4, 6), max_samples=5, asset_filter="BTC")
print(f"  NORMAL   (4-6/10 wins): found {len(normal_samples)} non-overlapping windows")

# Try ETH if BTC didn't yield enough
if len(strong_samples) < 3:
    eth_strong = find_windows(all_trades, (7, 10), max_samples=3, asset_filter="ETH")
    print(f"  ETH STRONG fallback: found {len(eth_strong)}")
    strong_samples.extend(eth_strong)

# ── Run brain on each sample ─────────────────────────────────────────────────
def test_one(sample, expected_label):
    asset = sample["asset"]
    brain = WindowBrain(asset, "15m")
    # Pre-load the history (brain._history is a deque)
    brain._history = deque(sample["history"], maxlen=10)

    # Synthetic candidate based on the actual next trade
    advice = brain.advise(
        entry_price=sample["next_entry"],
        side=sample["next_side"],
        edge=0.0,
        rv_std=0.0,
        cross_window_pct=0.0,
        secs_remaining=600.0,   # mid-window
    )

    correct = advice.mr_edge == expected_label
    mark = "✓" if correct else "✗"
    print(f"  {mark} [{expected_label:>8} expected] wins={sample['wins']:>2}/10  "
          f"→ regime={advice.regime:<9} mr_edge={advice.mr_edge:<8} "
          f"mod={advice.edge_modifier:+.3f}  conf=? — {advice.reasoning[:80]}")
    return correct, advice


print(f"\n=== Replay test (model={BRAIN_MODEL}) ===\n")

print(f"--- DEGRADED windows (expect mr_edge=degraded) ---")
deg_correct = 0
for s in degraded_samples:
    ok, _ = test_one(s, "degraded")
    if ok: deg_correct += 1
    time.sleep(0.5)

print(f"\n--- STRONG windows (expect mr_edge=strong) ---")
str_correct = 0
for s in strong_samples:
    ok, _ = test_one(s, "strong")
    if ok: str_correct += 1
    time.sleep(0.5)

print(f"\n--- NORMAL windows (expect mr_edge=normal) ---")
nor_correct = 0
for s in normal_samples:
    ok, _ = test_one(s, "normal")
    if ok: nor_correct += 1
    time.sleep(0.5)

print(f"\n=== Results ===")
n_deg = len(degraded_samples); n_str = len(strong_samples); n_nor = len(normal_samples)
total = n_deg + n_str + n_nor
correct = deg_correct + str_correct + nor_correct
print(f"  DEGRADED: {deg_correct}/{n_deg} correct")
print(f"  STRONG:   {str_correct}/{n_str} correct")
print(f"  NORMAL:   {nor_correct}/{n_nor} correct")
print(f"  TOTAL:    {correct}/{total} ({100*correct/total if total else 0:.0f}%)")

# Diagnostic: did brain correctly USE the recency signal at all?
if deg_correct == 0 and str_correct == 0:
    print("\n  DIAGNOSIS: Brain does not differentiate by recent WR. Calibration broken.")
elif deg_correct >= n_deg * 0.6 and str_correct >= n_str * 0.6:
    print("\n  DIAGNOSIS: Brain correctly identifies clear regime windows. Calibration GOOD.")
else:
    print("\n  DIAGNOSIS: Mixed - brain partially recognizes regimes but not consistently.")
