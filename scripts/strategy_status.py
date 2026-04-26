"""
Strategy status diagnostic - per-strategy WR / PnL / EV breakdown.

Reads trades.csv from PAPER (and optionally LIVE) and prints a per-(asset,
strategy, side) table including breakeven WR and a status flag against the
v1.23 LIVE filter rules. Also computes the rolling-N-trade WR specifically
for ETH DOWN RS and SOL DOWN RS, since those are the v1.23 LIVE rollout gates.

Usage (laptop):
  python scripts/strategy_status.py
  python scripts/strategy_status.py --paper output/5m_trading/trades.csv
  python scripts/strategy_status.py --live  output/5m_live/trades_BTC-15m.csv

Usage (dev PC, via SSH):
  ssh matti@192.168.2.212 "cd C:\\Users\\matti\\Desktop\\prediction-market-analysis && \\
    .venv\\Scripts\\python.exe scripts/strategy_status.py"

No external deps - stdlib only. Safe to run any time.
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable

# v1.23 LIVE filter - keep in sync with src/bot/signal_5m.py:should_enter_resolution_scalp
LIVE_RS_ALLOWED = {("ETH", "DOWN"), ("SOL", "DOWN")}

# v1.21 MR disablements
MR_DISABLED = {("BTC", "DOWN"), ("SOL", "DOWN")}


def _read_trades(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _aggregate(rows: Iterable[dict], strategy: str) -> dict[tuple[str, str], dict]:
    """Return {(asset, side): stats} for the given strategy."""
    buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in rows:
        if r.get("strategy", "") != strategy:
            continue
        asset = r.get("asset", "")
        side = r.get("side", "")
        try:
            pnl = float(r.get("pnl_usd") or 0)
        except ValueError:
            continue
        buckets[(asset, side)].append(pnl)

    out: dict[tuple[str, str], dict] = {}
    for key, pnls in buckets.items():
        n = len(pnls)
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        wr = len(wins) / n if n else 0.0
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        # Breakeven WR: avg_loss / (avg_win + avg_loss) using magnitudes
        be_wr = (
            abs(avg_loss) / (avg_win + abs(avg_loss))
            if (avg_win + abs(avg_loss)) > 0
            else 0.0
        )
        ev = wr * avg_win + (1 - wr) * avg_loss
        out[key] = {
            "n": n,
            "wr": wr,
            "pnl": sum(pnls),
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "be_wr": be_wr,
            "ev": ev,
            "pnls": pnls,  # ordered as in CSV
        }
    return out


def _status_mr(asset: str, side: str, stats: dict) -> str:
    if (asset, side) in MR_DISABLED:
        return "[X] disabled v1.21"
    if stats["wr"] >= stats["be_wr"]:
        return "[OK] above BE"
    delta = (stats["be_wr"] - stats["wr"]) * 100
    return f"~ {delta:.1f}pp below BE"


def _status_rs(asset: str, side: str, stats: dict) -> str:
    if (asset, side) in LIVE_RS_ALLOWED:
        live = "LIVE-allowed"
    else:
        live = "LIVE-disabled v1.23"
    if stats["wr"] >= stats["be_wr"]:
        return f"[OK] above BE | {live}"
    return f"[X] below BE | {live}"


def _print_table(title: str, agg: dict[tuple[str, str], dict], status_fn) -> None:
    print(f"\n{title}")
    print("=" * len(title))
    print(
        f"  {'Asset':<6}{'Side':<6}{'n':>5}  {'WR':>6}  {'PnL':>10}  "
        f"{'avg_w':>7}  {'avg_l':>7}  {'BE_WR':>6}  {'EV/tr':>7}  Status"
    )
    # Sort: asset (BTC, ETH, SOL), then side (UP first)
    asset_order = {"BTC": 0, "ETH": 1, "SOL": 2}
    side_order = {"UP": 0, "DOWN": 1}
    for (asset, side), s in sorted(
        agg.items(),
        key=lambda kv: (asset_order.get(kv[0][0], 99), side_order.get(kv[0][1], 99)),
    ):
        status = status_fn(asset, side, s)
        print(
            f"  {asset:<6}{side:<6}{s['n']:>5}  {s['wr']*100:>5.1f}%  "
            f"${s['pnl']:>+8.2f}  ${s['avg_win']:>+5.2f}  ${s['avg_loss']:>+5.2f}  "
            f"{s['be_wr']*100:>5.1f}%  ${s['ev']:>+5.2f}  {status}"
        )


def _rolling_wr(pnls: list[float], n: int) -> tuple[int, float, float]:
    """Last `n` trades: returns (n_actual, win_rate, sum_pnl). If fewer than n trades, uses what's available."""
    tail = pnls[-n:]
    if not tail:
        return 0, 0.0, 0.0
    wins = sum(1 for p in tail if p > 0)
    return len(tail), wins / len(tail), sum(tail)


def _print_live_gates(rs_agg: dict[tuple[str, str], dict]) -> None:
    print("\nLIVE Rollout Gates (Cowork 2026-04-25)")
    print("=" * 38)

    eth_down = rs_agg.get(("ETH", "DOWN"))
    sol_down = rs_agg.get(("SOL", "DOWN"))

    print("\n  ETH DOWN RS - first to enable on LIVE:")
    if eth_down:
        for window in (20, 50):
            n, wr, pnl = _rolling_wr(eth_down["pnls"], window)
            gate = "WR >= 70%" if window == 20 else "WR >= 70% AND PnL > 0"
            wr_pass = wr >= 0.70
            pnl_pass = pnl > 0 if window == 50 else True
            ok = "[OK] PASS" if (wr_pass and pnl_pass) else "[X] fail"
            print(
                f"    Last {window:>2} trades (have {n:>2}): "
                f"WR={wr*100:>5.1f}%, PnL=${pnl:>+7.2f}  | gate: {gate}  --> {ok}"
            )
    else:
        print("    No ETH DOWN RS trades found.")

    print("\n  SOL DOWN RS - second (after ETH DOWN clears 50-trade gate):")
    if sol_down:
        for window in (20, 50):
            n, wr, pnl = _rolling_wr(sol_down["pnls"], window)
            gate = "WR >= 70%" if window == 20 else "WR >= 70% AND PnL > 0"
            wr_pass = wr >= 0.70
            pnl_pass = pnl > 0 if window == 50 else True
            ok = "[OK] PASS" if (wr_pass and pnl_pass) else "[X] fail"
            print(
                f"    Last {window:>2} trades (have {n:>2}): "
                f"WR={wr*100:>5.1f}%, PnL=${pnl:>+7.2f}  | gate: {gate}  --> {ok}"
            )
    else:
        print("    No SOL DOWN RS trades found.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().split("\n\n")[0])
    parser.add_argument(
        "--paper",
        type=Path,
        default=Path("output/5m_trading/trades.csv"),
        help="Path to PAPER trades.csv (default: output/5m_trading/trades.csv)",
    )
    parser.add_argument(
        "--live",
        type=Path,
        default=None,
        help="Optional path to a LIVE trades_*.csv (e.g. output/5m_live/trades_ETH-15m.csv)",
    )
    args = parser.parse_args()

    paper_rows = _read_trades(args.paper)
    if not paper_rows:
        print(f"[strategy_status] No trades found at {args.paper}", file=sys.stderr)
        return 1

    print(f"Strategy Status - {args.paper} ({len(paper_rows)} rows)")

    mr_agg = _aggregate(paper_rows, "mean_reversion")
    rs_agg = _aggregate(paper_rows, "resolution_scalp")

    if mr_agg:
        _print_table("PAPER MEAN REVERSION", mr_agg, _status_mr)
    if rs_agg:
        _print_table("PAPER RESOLUTION SCALP", rs_agg, _status_rs)
        _print_live_gates(rs_agg)

    if args.live:
        live_rows = _read_trades(args.live)
        if live_rows:
            # LIVE files don't have 'strategy' column; treat as MR for now
            # (multi-live default has only MR threads as of v1.23)
            print(f"\n--- LIVE: {args.live} ({len(live_rows)} rows, treated as mean_reversion) ---")
            for r in live_rows:
                r["strategy"] = "mean_reversion"
            live_agg = _aggregate(live_rows, "mean_reversion")
            if live_agg:
                _print_table("LIVE MEAN REVERSION", live_agg, _status_mr)

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
