"""
Live trading engine for 5-minute Up/Down markets.

Mirrors engine_5m.py but places real limit (maker) orders on the Polymarket CLOB
instead of simulating them. Persists state to a separate output directory so
paper and live runs never mix.

Order lifecycle
───────────────
Entry:
  1. place_entry()  — post GTC limit BUY at ENTRY_PRICE; returns order_id
  2. check_entries() — called every poll; marks position OPEN on fill
  3. cancel_entry()  — called if window closes before fill

Exit:
  1. place_exit()   — post GTC limit SELL at take-profit, OR aggressive limit for stops
  2. check_exits()  — called every poll; marks position CLOSED on fill

State machine per position:
  PENDING_ENTRY → OPEN → PENDING_EXIT → CLOSED  (happy path)
  PENDING_ENTRY → CANCELLED                       (window closed, no fill)

Files (separate from paper trading):
  output/5m_live/positions.csv   — open + pending positions
  output/5m_live/trades.csv      — closed trade history
  output/5m_live/summary.json    — running P&L
"""
from __future__ import annotations

import csv
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL

from src.bot.clob_auth import get_client

OUT_DIR        = Path("output/5m_live")
POSITIONS_FILE = OUT_DIR / "positions.csv"
TRADES_FILE    = OUT_DIR / "trades.csv"
SUMMARY_FILE   = OUT_DIR / "summary.json"

STARTING_EQUITY = 1000.0
POSITION_SIZE   = 20.0    # USD per trade (real money)
MIN_SHARES      = 5       # Polymarket CLOB minimum order size in shares

# Aggressive exit price for hard stops / force exits.
# Posting a SELL at 0.01 on Polymarket will immediately match the best available
# bid — effectively a market order with price improvement.
AGGRESSIVE_EXIT_PRICE = 0.01

# Cancel unfilled entry orders after this many seconds (price likely moved away).
ENTRY_FILL_TIMEOUT = 45

# Re-submit exit as aggressive FOK if GTC exit has been pending this long.
EXIT_STUCK_TIMEOUT = 90


# ── Position states ────────────────────────────────────────────────────────────

class State:
    PENDING_ENTRY = "pending_entry"   # buy order placed, waiting for fill
    OPEN          = "open"            # filled, holding
    PENDING_EXIT  = "pending_exit"    # sell order placed, waiting for fill
    CLOSED        = "closed"          # fully done (written to trades.csv)
    CANCELLED     = "cancelled"       # entry never filled, order cancelled


POSITION_FIELDS = [
    "position_id", "condition_id", "slug", "asset", "side", "state",
    "entry_price", "take_profit",
    "size_usd", "shares", "entry_fee_usd",
    "window_end_ts", "opened_at",
    # Order tracking
    "entry_order_id", "exit_order_id",
    # Entry context (mirrors paper engine for ML parity)
    "btc_price_at_window_start", "btc_price_at_entry", "btc_pct_change_at_entry",
    "up_price_at_window_start", "secs_remaining_at_entry", "liquidity",
    "price_60s_before_entry", "price_30s_before_entry", "price_velocity",
]

TRADE_FIELDS = POSITION_FIELDS + [
    "price_60s_after_entry",
    "exit_price", "exit_fee_usd", "exit_reason",
    "closed_at", "hold_seconds", "pnl_usd", "return_pct",
]


@dataclass
class LivePosition5m:
    position_id: str
    condition_id: str
    slug: str
    asset: str
    side: str           # "UP" or "DOWN"
    state: str          # State.*
    entry_price: float  # limit price the buy was placed at
    take_profit: float
    size_usd: float
    shares: float       # filled shares (0 until OPEN)
    entry_fee_usd: float
    window_end_ts: float
    opened_at: float    # time buy order was placed (not fill time)
    # Order IDs
    entry_order_id: str = ""
    exit_order_id: str = ""
    # Entry context
    btc_price_at_window_start: float = 0.0
    btc_price_at_entry: float = 0.0
    btc_pct_change_at_entry: float = 0.0
    up_price_at_window_start: float = 0.5
    secs_remaining_at_entry: float = 0.0
    liquidity: float = 0.0
    price_60s_before_entry: float = 0.0
    price_30s_before_entry: float = 0.0
    price_velocity: float = 0.0


@dataclass
class ClosedLiveTrade5m:
    position_id: str
    condition_id: str
    slug: str
    asset: str
    side: str
    state: str
    entry_price: float
    take_profit: float
    size_usd: float
    shares: float
    entry_fee_usd: float
    window_end_ts: float
    opened_at: float
    entry_order_id: str = ""
    exit_order_id: str = ""
    btc_price_at_window_start: float = 0.0
    btc_price_at_entry: float = 0.0
    btc_pct_change_at_entry: float = 0.0
    up_price_at_window_start: float = 0.5
    secs_remaining_at_entry: float = 0.0
    liquidity: float = 0.0
    price_60s_before_entry: float = 0.0
    price_30s_before_entry: float = 0.0
    price_velocity: float = 0.0
    price_60s_after_entry: float = 0.0
    exit_price: float = 0.0
    exit_fee_usd: float = 0.0
    exit_reason: str = ""
    closed_at: float = 0.0
    hold_seconds: float = 0.0
    pnl_usd: float = 0.0
    return_pct: float = 0.0


# ── Persistence ────────────────────────────────────────────────────────────────

def _save_positions(positions: dict[str, LivePosition5m]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(POSITIONS_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=POSITION_FIELDS)
        writer.writeheader()
        for p in positions.values():
            writer.writerow(asdict(p))


def _load_positions() -> dict[str, LivePosition5m]:
    if not POSITIONS_FILE.exists():
        return {}
    out: dict[str, LivePosition5m] = {}
    str_fields = {"position_id","condition_id","slug","asset","side","state",
                  "entry_order_id","exit_order_id"}
    with open(POSITIONS_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                out[row["position_id"]] = LivePosition5m(**{
                    k: (row[k] if k in str_fields else float(row[k]))
                    for k in POSITION_FIELDS if k in row
                })
            except Exception:
                pass
    return out


def _append_trade(trade: ClosedLiveTrade5m) -> None:
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
    trades: list[ClosedLiveTrade5m] = []
    str_fields = {"position_id","condition_id","slug","asset","side","state",
                  "entry_order_id","exit_order_id","exit_reason"}
    with open(TRADES_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                trades.append(ClosedLiveTrade5m(**{
                    k: (row[k] if k in str_fields else float(row[k]))
                    for k in TRADE_FIELDS if k in row
                }))
            except Exception:
                pass

    total_pnl = sum(t.pnl_usd for t in trades)
    wins   = [t for t in trades if t.pnl_usd > 0]
    losses = [t for t in trades if t.pnl_usd <= 0]
    return {
        "equity":        round(STARTING_EQUITY + total_pnl, 2),
        "closed_trades": len(trades),
        "wins":          len(wins),
        "losses":        len(losses),
        "win_rate":      round(len(wins) / len(trades) * 100, 1) if trades else 0.0,
        "total_pnl":     round(total_pnl, 2),
        "avg_win":       round(sum(t.pnl_usd for t in wins)   / len(wins),   2) if wins   else 0.0,
        "avg_loss":      round(sum(t.pnl_usd for t in losses) / len(losses), 2) if losses else 0.0,
    }


# ── Engine ─────────────────────────────────────────────────────────────────────

class LiveEngine5m:
    """
    Live trading engine. Places real orders on the Polymarket CLOB.
    Call check_pending() every poll to advance the order state machine.
    """

    def __init__(self) -> None:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        self._client = get_client()
        self.positions: dict[str, LivePosition5m] = _load_positions()
        open_count    = sum(1 for p in self.positions.values() if p.state == State.OPEN)
        pending_count = sum(1 for p in self.positions.values() if p.state == State.PENDING_ENTRY)
        print(f"[LIVE5M] Loaded {open_count} open, {pending_count} pending-entry positions")
        self._cancel_expired_entries()

    def _cancel_expired_entries(self) -> None:
        """On startup, cancel any PENDING_ENTRY orders whose window already closed."""
        now = time.time()
        for pos_id, pos in list(self.positions.items()):
            if pos.state == State.PENDING_ENTRY and pos.window_end_ts < now:
                print(f"[LIVE5M] STARTUP cancel orphaned entry {pos_id} (window expired)")
                self.cancel_entry(pos_id)

    def already_in(self, condition_id: str) -> bool:
        return any(
            p.condition_id == condition_id
            for p in self.positions.values()
            if p.state in (State.PENDING_ENTRY, State.OPEN, State.PENDING_EXIT)
        )

    # ── Entry ─────────────────────────────────────────────────────────────────

    def place_entry(
        self,
        condition_id: str,
        slug: str,
        asset: str,
        side: str,               # "UP" or "DOWN"
        token_id: str,           # ERC-1155 token ID for the UP or DOWN token
        entry_price: float,      # limit price (e.g. 0.40)
        take_profit: float,
        window_end_ts: float,
        btc_price_at_window_start: float = 0.0,
        btc_price_at_entry: float = 0.0,
        up_price_at_window_start: float = 0.5,
        liquidity: float = 0.0,
        price_60s_before_entry: float = 0.0,
        price_30s_before_entry: float = 0.0,
    ) -> LivePosition5m | None:
        """Place a GTC limit BUY order. Returns position in PENDING_ENTRY state."""
        if self.already_in(condition_id):
            return None

        shares = round(POSITION_SIZE / entry_price, 4)
        if shares < MIN_SHARES:
            print(f"[LIVE5M] Skip — {shares:.2f} shares below minimum {MIN_SHARES}")
            return None

        # Place the order
        try:
            order_args = OrderArgs(
                price=entry_price,
                size=shares,
                side=BUY,
                token_id=token_id,
            )
            signed = self._client.create_order(order_args)
            resp   = self._client.post_order(signed, OrderType.GTC)
        except Exception as exc:
            print(f"[LIVE5M] Entry order failed: {exc}")
            return None

        order_id = resp.get("orderID", "")
        if not order_id:
            print(f"[LIVE5M] Entry order rejected: {resp}")
            return None

        # Derived context fields
        btc_pct = 0.0
        if btc_price_at_window_start > 0 and btc_price_at_entry > 0:
            btc_pct = round(
                (btc_price_at_entry - btc_price_at_window_start) / btc_price_at_window_start * 100, 4
            )
        now = time.time()
        secs_remaining = round(max(0.0, window_end_ts - now), 1)
        price_velocity = 0.0
        if price_60s_before_entry > 0:
            price_velocity = round((entry_price - price_60s_before_entry) / 60.0, 6)

        pos = LivePosition5m(
            position_id=str(uuid.uuid4())[:8],
            condition_id=condition_id,
            slug=slug,
            asset=asset,
            side=side,
            state=State.PENDING_ENTRY,
            entry_price=entry_price,
            take_profit=take_profit,
            size_usd=POSITION_SIZE,
            shares=0.0,    # unknown until fill confirmed
            entry_fee_usd=0.0,
            window_end_ts=window_end_ts,
            opened_at=now,
            entry_order_id=order_id,
            btc_price_at_window_start=btc_price_at_window_start,
            btc_price_at_entry=btc_price_at_entry,
            btc_pct_change_at_entry=btc_pct,
            up_price_at_window_start=up_price_at_window_start,
            secs_remaining_at_entry=secs_remaining,
            liquidity=liquidity,
            price_60s_before_entry=price_60s_before_entry,
            price_30s_before_entry=price_30s_before_entry,
            price_velocity=price_velocity,
        )
        self.positions[pos.position_id] = pos
        _save_positions(self.positions)

        print(
            f"[LIVE5M] ORDER  {pos.position_id} | {asset} {side} "
            f"limit BUY {shares:.2f} shares @ {entry_price:.3f} | "
            f"order_id={order_id[:16]}..."
        )
        return pos

    def cancel_entry(self, position_id: str) -> None:
        """Cancel a PENDING_ENTRY order (window closed before fill)."""
        pos = self.positions.get(position_id)
        if pos is None or pos.state != State.PENDING_ENTRY:
            return
        try:
            self._client.cancel(pos.entry_order_id)
            print(f"[LIVE5M] CANCEL {position_id} | entry order cancelled (window expired)")
        except Exception as exc:
            print(f"[LIVE5M] Cancel failed for {position_id}: {exc}")
        pos.state = State.CANCELLED
        self.positions.pop(position_id, None)
        _save_positions(self.positions)

    # ── Fill detection ─────────────────────────────────────────────────────────

    def check_pending_entries(self) -> None:
        """
        Poll entry order status. Transition PENDING_ENTRY → OPEN on fill.
        Cancels orders that haven't filled within ENTRY_FILL_TIMEOUT seconds.
        Called every poll cycle.
        """
        now = time.time()
        for pos_id, pos in list(self.positions.items()):
            if pos.state != State.PENDING_ENTRY:
                continue

            # Timeout: cancel entries that price has moved away from
            age = now - pos.opened_at
            if age > ENTRY_FILL_TIMEOUT:
                print(f"[LIVE5M] TIMEOUT {pos_id} — unfilled after {age:.0f}s, cancelling")
                self.cancel_entry(pos_id)
                continue

            try:
                order = self._client.get_order(pos.entry_order_id)
            except Exception as exc:
                print(f"[LIVE5M] get_order failed for {pos_id}: {exc}")
                continue

            status = order.get("status", "")
            size_matched = float(order.get("size_matched", 0))

            if status in ("matched", "filled") and size_matched > 0:
                pos.shares = size_matched
                pos.state  = State.OPEN
                _save_positions(self.positions)
                print(
                    f"[LIVE5M] FILLED {pos_id} | {pos.asset} {pos.side} "
                    f"{size_matched:.2f} shares @ {pos.entry_price:.3f}"
                )

    # ── Exit ──────────────────────────────────────────────────────────────────

    def place_exit(
        self,
        position_id: str,
        token_id: str,
        exit_reason: str,
        price_60s_after_entry: float = 0.0,
    ) -> None:
        """
        Place an exit (SELL) order.
        - take_profit / force_exit_price: GTC limit at take_profit price (sits on book)
        - hard_stop / trailing_stop / force_exit_time: aggressive limit at 0.01
          (immediately matches best available bid — effective market order)
        """
        pos = self.positions.get(position_id)
        if pos is None or pos.state != State.OPEN:
            return

        # All stop/floor/stalled reasons must exit immediately via FOK.
        # hard_stop_floor and soft_exit_stalled are the paper engine names for
        # the same conditions — include both forms so nothing slips through.
        aggressive_reasons = {
            "hard_stop", "hard_stop_floor",
            "soft_exit_stalled",
            "trailing_stop_z2", "trailing_stop_z3",
            "force_exit_time", "window_expired",
        }
        if exit_reason in aggressive_reasons:
            exit_price = AGGRESSIVE_EXIT_PRICE
            order_type = OrderType.FOK   # Fill or Kill — must fill immediately
        else:
            # take_profit — post GTC limit at TP price and let it sit on the book
            exit_price = pos.take_profit
            order_type = OrderType.GTC

        try:
            order_args = OrderArgs(
                price=exit_price,
                size=pos.shares,
                side=SELL,
                token_id=token_id,
            )
            signed = self._client.create_order(order_args)
            resp   = self._client.post_order(signed, order_type)
        except Exception as exc:
            print(f"[LIVE5M] Exit order failed for {position_id}: {exc}")
            return

        order_id = resp.get("orderID", "")
        if not order_id and order_type != OrderType.FOK:
            # GTC exit with no order_id means the API rejected it — don't
            # transition state or the position will be stuck in PENDING_EXIT forever.
            print(f"[LIVE5M] Exit order rejected (no orderID): {resp}")
            return
        pos.exit_order_id = order_id
        pos.state = State.PENDING_EXIT
        _save_positions(self.positions)

        print(
            f"[LIVE5M] EXIT   {position_id} | {exit_reason} "
            f"SELL {pos.shares:.2f} @ {exit_price:.3f} | "
            f"order_id={order_id[:16] if order_id else 'FOK-immediate'}..."
        )

        # FOK resolves immediately — check right away
        if order_type == OrderType.FOK:
            self._settle_exit(position_id, exit_price, exit_reason, price_60s_after_entry)

    def check_pending_exits(self, price_60s_after_entry: float = 0.0) -> list[ClosedLiveTrade5m]:
        """
        Poll exit order status. Transition PENDING_EXIT → CLOSED on fill.
        Re-submits as aggressive FOK if GTC exit has been stuck > EXIT_STUCK_TIMEOUT.
        Called every poll cycle. Returns list of trades closed this call.
        """
        now    = time.time()
        closed = []
        for pos_id, pos in list(self.positions.items()):
            if pos.state != State.PENDING_EXIT:
                continue

            # Rescue: GTC exit stuck too long — re-submit as aggressive FOK
            if not pos.exit_order_id or (now - pos.opened_at > EXIT_STUCK_TIMEOUT):
                age = now - pos.opened_at
                print(f"[LIVE5M] STUCK EXIT {pos_id} — pending {age:.0f}s, re-submitting as FOK")
                # Cancel existing GTC order if we have one
                if pos.exit_order_id:
                    try:
                        self._client.cancel(pos.exit_order_id)
                    except Exception:
                        pass
                # Reset to OPEN so place_exit() can fire again as aggressive
                pos.state = State.OPEN
                pos.exit_order_id = ""
                _save_positions(self.positions)
                self._settle_exit(pos_id, AGGRESSIVE_EXIT_PRICE, "force_exit_stuck", price_60s_after_entry)
                continue

            try:
                order = self._client.get_order(pos.exit_order_id)
            except Exception as exc:
                print(f"[LIVE5M] get_order (exit) failed for {pos_id}: {exc}")
                continue

            status = order.get("status", "")
            if status in ("matched", "filled"):
                actual_exit = float(order.get("average_price", pos.take_profit))
                trade = self._settle_exit(pos_id, actual_exit, "take_profit", price_60s_after_entry)
                if trade:
                    closed.append(trade)
        return closed

    def _settle_exit(
        self,
        position_id: str,
        actual_exit_price: float,
        exit_reason: str,
        price_60s_after_entry: float,
    ) -> ClosedLiveTrade5m | None:
        """Record the closed trade and remove from active positions."""
        pos = self.positions.pop(position_id, None)
        if pos is None:
            return

        gross_proceeds = pos.shares * actual_exit_price
        pnl_usd    = gross_proceeds - pos.size_usd
        return_pct = pnl_usd / pos.size_usd * 100
        hold_sec   = time.time() - pos.opened_at

        trade = ClosedLiveTrade5m(
            **asdict(pos),
            price_60s_after_entry=round(price_60s_after_entry, 4),
            exit_price=actual_exit_price,
            exit_fee_usd=0.0,    # maker orders: 0% fee
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
            f"[LIVE5M] CLOSE {position_id} | {emoji} ${pnl_usd:+.2f} ({return_pct:+.1f}%) "
            f"| {exit_reason} | hold={hold_sec:.0f}s"
        )
        return trade

    # ── Summary ───────────────────────────────────────────────────────────────

    def summary(self) -> dict[str, Any]:
        s = _compute_summary()
        s["open_positions"]    = sum(1 for p in self.positions.values() if p.state == State.OPEN)
        s["pending_positions"] = sum(1 for p in self.positions.values() if p.state == State.PENDING_ENTRY)
        return s

    def save_summary(self) -> None:
        SUMMARY_FILE.write_text(json.dumps(self.summary(), indent=2), encoding="utf-8")
