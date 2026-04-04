"""
Paper trading engine for 5-minute Up/Down markets.

Simulates limit (maker) orders — no fee, small positive rebate.
Limit orders: place a bid at target price and wait for fill.
  - 0% maker fee (vs 10% taker fee for market orders)
  - Small maker rebate (~1-2% of fill, not yet modelled)
Positions auto-close before each window expires.

Files:
  output/5m_trading/positions.csv   — open positions
  output/5m_trading/trades.csv      — closed trade history
  output/5m_trading/summary.json    — running P&L summary
"""
from __future__ import annotations

import csv
import json
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OUT_DIR        = Path("output/5m_trading")
POSITIONS_FILE = OUT_DIR / "positions.csv"
TRADES_FILE    = OUT_DIR / "trades.csv"
SUMMARY_FILE   = OUT_DIR / "summary.json"
SKIPS_FILE     = OUT_DIR / "skipped_windows.csv"

STARTING_EQUITY = 1000.0
POSITION_SIZE   = 20.0    # $ per trade (paper)
MAKER_FEE       = 0.00    # 0% fee for limit (maker) orders — Polymarket charges only takers

POSITION_FIELDS = [
    "position_id", "condition_id", "slug", "asset", "side",
    "entry_price", "take_profit",
    "size_usd", "shares", "entry_fee_usd",
    "window_end_ts", "opened_at",
    # Entry context for ML analysis
    "btc_price_at_window_start", "btc_price_at_entry", "btc_pct_change_at_entry",
    "up_price_at_window_start", "secs_remaining_at_entry", "liquidity",
    "price_60s_before_entry", "price_30s_before_entry", "price_velocity",
]

TRADE_FIELDS = POSITION_FIELDS + [
    "price_60s_after_entry",                          # UP token price 60s after entry (ML: hold vs exit)
    "exit_price", "exit_fee_usd", "exit_reason",
    "closed_at", "hold_seconds", "pnl_usd", "return_pct",
    "resolution_side", "our_side_won",               # filled after window ends — did our side pay $1.00?
]

# Skipped windows — logged when entry window closes without a trade.
# Enables backtesting any ENTRY_MIN/ENTRY_MAX value against historical data.
SKIP_FIELDS = [
    "condition_id", "slug", "asset", "window_end_ts",
    "skip_reason",          # price_too_high | price_too_low | btc_filter | no_opportunity
    "best_price_seen",      # lowest cheaper-side price seen during the 45s entry window
    "best_side",            # which side was cheapest at best_price_seen
    "entry_min",            # ENTRY_MIN at time of skip (for backtest context)
    "entry_max",            # ENTRY_MAX at time of skip (for backtest context)
    "btc_at_window_start",
    "liquidity",
    "logged_at",
]


@dataclass
class Position5m:
    position_id: str
    condition_id: str
    slug: str
    asset: str
    side: str           # "UP" or "DOWN"
    entry_price: float  # price paid per share
    take_profit: float  # target exit price (no stop loss — let positions breathe)
    size_usd: float     # gross position size
    shares: float       # effective shares after entry fee deducted
    entry_fee_usd: float
    window_end_ts: float
    opened_at: float
    # Entry context for ML analysis (default 0 so old CSV rows still load)
    btc_price_at_window_start: float = 0.0  # Binance BTC/USD when window opened
    btc_price_at_entry: float = 0.0         # Binance BTC/USD at entry moment
    btc_pct_change_at_entry: float = 0.0    # % BTC move since window start
    up_price_at_window_start: float = 0.5   # UP token CLOB midpoint at window open
    secs_remaining_at_entry: float = 0.0    # seconds left in window when entered
    liquidity: float = 0.0                  # market liquidity at entry
    price_60s_before_entry: float = 0.0    # UP midpoint ~60s before entry
    price_30s_before_entry: float = 0.0    # UP midpoint ~30s before entry
    price_velocity: float = 0.0            # (entry_price - price_60s_ago) / 60  ¢/sec


@dataclass
class ClosedTrade5m:
    position_id: str
    condition_id: str
    slug: str
    asset: str
    side: str
    entry_price: float
    take_profit: float
    size_usd: float
    shares: float
    entry_fee_usd: float
    window_end_ts: float
    opened_at: float
    # ML context fields (match Position5m — defaults for backward compat)
    btc_price_at_window_start: float = 0.0
    btc_price_at_entry: float = 0.0
    btc_pct_change_at_entry: float = 0.0
    up_price_at_window_start: float = 0.5
    secs_remaining_at_entry: float = 0.0
    liquidity: float = 0.0
    price_60s_before_entry: float = 0.0
    price_30s_before_entry: float = 0.0
    price_velocity: float = 0.0
    # Exit context for ML analysis
    price_60s_after_entry: float = 0.0   # UP token price 60s after entry — for hold-vs-exit analysis
    # Exit fields
    exit_price: float = 0.0
    exit_fee_usd: float = 0.0
    exit_reason: str = ""
    closed_at: float = 0.0
    hold_seconds: float = 0.0
    pnl_usd: float = 0.0
    return_pct: float = 0.0
    # Filled after window resolves — blank until then
    resolution_side: str = ""   # "UP" or "DOWN" — which side paid $1.00
    our_side_won: str = ""      # "True" / "False" — did we pick the winner?


def _load_positions() -> dict[str, Position5m]:
    if not POSITIONS_FILE.exists():
        return {}
    positions: dict[str, Position5m] = {}
    with open(POSITIONS_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                p = Position5m(
                    position_id=row["position_id"],
                    condition_id=row["condition_id"],
                    slug=row["slug"],
                    asset=row["asset"],
                    side=row["side"],
                    entry_price=float(row["entry_price"]),
                    take_profit=float(row["take_profit"]),
                    size_usd=float(row["size_usd"]),
                    shares=float(row["shares"]),
                    entry_fee_usd=float(row["entry_fee_usd"]),
                    window_end_ts=float(row["window_end_ts"]),
                    opened_at=float(row["opened_at"]),
                    # New context fields — graceful default for old CSV rows
                    btc_price_at_window_start=float(row.get("btc_price_at_window_start", 0)),
                    btc_price_at_entry=float(row.get("btc_price_at_entry", 0)),
                    btc_pct_change_at_entry=float(row.get("btc_pct_change_at_entry", 0)),
                    up_price_at_window_start=float(row.get("up_price_at_window_start", 0.5)),
                    secs_remaining_at_entry=float(row.get("secs_remaining_at_entry", 0)),
                    liquidity=float(row.get("liquidity", 0)),
                    price_60s_before_entry=float(row.get("price_60s_before_entry", 0)),
                    price_30s_before_entry=float(row.get("price_30s_before_entry", 0)),
                    price_velocity=float(row.get("price_velocity", 0)),
                )
                positions[p.position_id] = p
            except (KeyError, ValueError):
                pass
    return positions


def _save_positions(positions: dict[str, Position5m]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(POSITIONS_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=POSITION_FIELDS)
        writer.writeheader()
        for p in positions.values():
            writer.writerow(asdict(p))


def _append_trade(trade: ClosedTrade5m) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_header = not TRADES_FILE.exists()
    with open(TRADES_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TRADE_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow(asdict(trade))


def _compute_summary() -> dict[str, Any]:
    if not TRADES_FILE.exists():
        return {
            "equity": STARTING_EQUITY, "closed_trades": 0,
            "wins": 0, "losses": 0, "win_rate": 0.0,
            "total_pnl": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
        }
    trades: list[ClosedTrade5m] = []
    str_fields = {"position_id","condition_id","slug","asset","side","exit_reason"}
    with open(TRADES_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                trades.append(ClosedTrade5m(**{
                    k: (row[k] if k in str_fields else float(row[k]))
                    for k in TRADE_FIELDS if k in row
                }))
            except Exception:
                pass

    total_pnl = sum(t.pnl_usd for t in trades)
    wins   = [t for t in trades if t.pnl_usd > 0]
    losses = [t for t in trades if t.pnl_usd <= 0]

    return {
        "equity":       round(STARTING_EQUITY + total_pnl, 2),
        "closed_trades": len(trades),
        "wins":          len(wins),
        "losses":        len(losses),
        "win_rate":      round(len(wins) / len(trades) * 100, 1) if trades else 0.0,
        "total_pnl":     round(total_pnl, 2),
        "avg_win":       round(sum(t.pnl_usd for t in wins)   / len(wins),   2) if wins   else 0.0,
        "avg_loss":      round(sum(t.pnl_usd for t in losses) / len(losses), 2) if losses else 0.0,
    }


class Engine5m:
    """Paper trading engine for 5-minute up/down markets."""

    def __init__(self) -> None:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        self.positions: dict[str, Position5m] = _load_positions()
        # Tracks every condition_id traded this session (open OR closed) so we
        # never re-enter the same window. Analysis: single-trade windows +$85.90
        # (52.4% WR) vs multi-trade windows -$192.27 (39.7% WR).
        self.traded_windows: set[str] = {
            p.condition_id for p in self.positions.values()
        }
        print(f"[ENGINE5M] Loaded {len(self.positions)} open positions")

    def already_in(self, condition_id: str) -> bool:
        return condition_id in self.traded_windows

    def open(
        self,
        condition_id: str,
        slug: str,
        asset: str,
        side: str,           # "UP" or "DOWN"
        entry_price: float,
        take_profit: float,
        window_end_ts: float,
        # Entry context for ML learning
        btc_price_at_window_start: float = 0.0,
        btc_price_at_entry: float = 0.0,
        up_price_at_window_start: float = 0.5,
        liquidity: float = 0.0,
        price_60s_before_entry: float = 0.0,
        price_30s_before_entry: float = 0.0,
    ) -> Position5m | None:
        if self.already_in(condition_id):
            return None

        now = time.time()

        # Derived context fields
        btc_pct_change = 0.0
        if btc_price_at_window_start > 0 and btc_price_at_entry > 0:
            btc_pct_change = round(
                (btc_price_at_entry - btc_price_at_window_start) / btc_price_at_window_start * 100, 4
            )
        secs_remaining = round(max(0.0, window_end_ts - now), 1)
        price_velocity = 0.0
        if price_60s_before_entry > 0:
            price_velocity = round((entry_price - price_60s_before_entry) / 60.0, 6)

        # Limit (maker) order — no entry fee, full size goes to work
        entry_fee = POSITION_SIZE * MAKER_FEE   # = 0
        net_investment = POSITION_SIZE - entry_fee
        shares = net_investment / entry_price

        pos = Position5m(
            position_id=str(uuid.uuid4())[:8],
            condition_id=condition_id,
            slug=slug,
            asset=asset,
            side=side,
            entry_price=entry_price,
            take_profit=take_profit,
            size_usd=POSITION_SIZE,
            shares=shares,
            entry_fee_usd=round(entry_fee, 4),
            window_end_ts=window_end_ts,
            opened_at=now,
            btc_price_at_window_start=btc_price_at_window_start,
            btc_price_at_entry=btc_price_at_entry,
            btc_pct_change_at_entry=btc_pct_change,
            up_price_at_window_start=up_price_at_window_start,
            secs_remaining_at_entry=secs_remaining,
            liquidity=liquidity,
            price_60s_before_entry=price_60s_before_entry,
            price_30s_before_entry=price_30s_before_entry,
            price_velocity=price_velocity,
        )
        self.positions[pos.position_id] = pos
        _save_positions(self.positions)

        self.traded_windows.add(condition_id)
        secs = max(0, window_end_ts - time.time())
        print(
            f"[ENGINE5M] OPEN  {pos.position_id} | {asset} {side} "
            f"@ {entry_price:.3f} | tp={take_profit:.3f} (no SL) "
            f"| {secs:.0f}s left"
        )
        return pos

    def close(
        self,
        position_id: str,
        exit_price: float,
        exit_reason: str,
        price_60s_after_entry: float = 0.0,   # UP token price 60s post-entry from price_history
    ) -> ClosedTrade5m | None:
        pos = self.positions.pop(position_id, None)
        if pos is None:
            return None

        # Limit (maker) order on exit — no exit fee either
        gross_proceeds = pos.shares * exit_price
        exit_fee = gross_proceeds * MAKER_FEE   # = 0
        net_proceeds = gross_proceeds - exit_fee

        pnl_usd    = net_proceeds - pos.size_usd  # net vs gross invested
        return_pct = pnl_usd / pos.size_usd * 100
        hold_sec   = time.time() - pos.opened_at

        trade = ClosedTrade5m(
            **asdict(pos),
            price_60s_after_entry=round(price_60s_after_entry, 4),
            exit_price=exit_price,
            exit_fee_usd=round(exit_fee, 4),
            exit_reason=exit_reason,
            closed_at=time.time(),
            hold_seconds=round(hold_sec, 1),
            pnl_usd=round(pnl_usd, 4),
            return_pct=round(return_pct, 2),
        )
        _append_trade(trade)
        _save_positions(self.positions)

        emoji = "WIN " if pnl_usd > 0 else "LOSS"
        print(
            f"[ENGINE5M] CLOSE {pos.position_id} | {emoji} ${pnl_usd:+.2f} ({return_pct:+.1f}%) "
            f"| {exit_reason} | hold={hold_sec:.0f}s"
        )
        return trade

    def update_resolution(self, condition_id: str, resolution_side: str) -> None:
        """
        Called when a window ends — fills resolution_side and our_side_won for
        all trades from that window. Rewrites the trades CSV in place.
        resolution_side: "UP" if BTC closed higher than window start, else "DOWN"
        """
        if not TRADES_FILE.exists():
            return
        rows = []
        updated = 0
        str_fields = {"position_id","condition_id","slug","asset","side","exit_reason",
                      "resolution_side","our_side_won"}
        with open(TRADES_FILE, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("condition_id") == condition_id and not row.get("resolution_side"):
                    row["resolution_side"] = resolution_side
                    row["our_side_won"]    = str(row["side"] == resolution_side)
                    updated += 1
                rows.append(row)
        if updated:
            with open(TRADES_FILE, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=TRADE_FIELDS)
                writer.writeheader()
                writer.writerows(rows)
            print(f"[ENGINE5M] Resolution: {resolution_side} won | {updated} trade(s) updated")

    def summary(self) -> dict[str, Any]:
        s = _compute_summary()
        s["open_positions"] = len(self.positions)
        return s

    def save_summary(self) -> None:
        s = self.summary()
        SUMMARY_FILE.write_text(json.dumps(s, indent=2), encoding="utf-8")

    def log_skip(
        self,
        condition_id: str,
        slug: str,
        asset: str,
        window_end_ts: float,
        skip_reason: str,
        best_price_seen: float,
        best_side: str,
        entry_min: float,
        entry_max: float,
        btc_at_window_start: float = 0.0,
        liquidity: float = 0.0,
    ) -> None:
        """Log a window where the entry window closed without a trade."""
        write_header = not SKIPS_FILE.exists()
        with open(SKIPS_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=SKIP_FIELDS)
            if write_header:
                writer.writeheader()
            writer.writerow({
                "condition_id":      condition_id,
                "slug":              slug,
                "asset":             asset,
                "window_end_ts":     window_end_ts,
                "skip_reason":       skip_reason,
                "best_price_seen":   round(best_price_seen, 4),
                "best_side":         best_side,
                "entry_min":         entry_min,
                "entry_max":         entry_max,
                "btc_at_window_start": btc_at_window_start,
                "liquidity":         liquidity,
                "logged_at":         time.time(),
            })
