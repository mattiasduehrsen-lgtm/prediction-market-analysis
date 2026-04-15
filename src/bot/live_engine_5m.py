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
  output/5m_live/positions_{tag}.csv   — open + pending positions
  output/5m_live/trades_{tag}.csv      — closed trade history
  output/5m_live/summary_{tag}.json    — running P&L
"""
from __future__ import annotations

import csv
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL

import os

from src.bot.clob_auth import get_client

OUT_DIR    = Path("output/5m_live")
PAUSE_FLAG = OUT_DIR / "paused.flag"   # dashboard writes this to pause new entries

STARTING_EQUITY = 1000.0
POSITION_SIZE   = float(os.environ.get("LIVE_POSITION_SIZE_USD", "20.0"))
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
    "token_id",          # ERC-1155 token ID for our side — needed for any exit without market context
    "exit_placed_at",    # timestamp when exit order was posted — for stuck-exit timeout
    "exit_reason",       # reason that triggered the exit — preserved through PENDING_EXIT
    "tp_order_id",       # standing GTC limit SELL at take_profit, placed immediately on fill
    # Entry context (mirrors paper engine for ML parity)
    "btc_price_at_window_start", "btc_price_at_entry", "btc_pct_change_at_entry",
    "up_price_at_window_start", "secs_remaining_at_entry", "liquidity",
    "price_60s_before_entry", "price_30s_before_entry", "price_velocity",
]

TRADE_FIELDS = POSITION_FIELDS + [
    "price_60s_after_entry",
    "exit_price", "exit_fee_usd",
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
    # Order IDs and exit tracking
    entry_order_id: str = ""
    exit_order_id: str = ""
    token_id: str = ""           # ERC-1155 token ID for our side
    exit_placed_at: float = 0.0  # timestamp when exit order was posted
    exit_reason: str = ""        # reason that triggered the exit
    tp_order_id: str = ""        # standing GTC SELL at take_profit, placed immediately on fill
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
    token_id: str = ""
    exit_placed_at: float = 0.0
    exit_reason: str = ""
    tp_order_id: str = ""
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
    closed_at: float = 0.0
    hold_seconds: float = 0.0
    pnl_usd: float = 0.0
    return_pct: float = 0.0


# ── Persistence ────────────────────────────────────────────────────────────────

STR_FIELDS_POS   = {"position_id","condition_id","slug","asset","side","state",
                    "entry_order_id","exit_order_id","token_id","exit_reason","tp_order_id"}
STR_FIELDS_TRADE = STR_FIELDS_POS | {"exit_reason"}


def _save_positions(positions: dict[str, LivePosition5m], path: Path) -> None:
    """Atomic write — positions file is always complete or previous version."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=POSITION_FIELDS)
        writer.writeheader()
        for p in positions.values():
            writer.writerow(asdict(p))
    os.replace(tmp, path)


def _load_positions(path: Path) -> dict[str, LivePosition5m]:
    if not path.exists():
        return {}
    out: dict[str, LivePosition5m] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                out[row["position_id"]] = LivePosition5m(**{
                    k: (row[k] if k in STR_FIELDS_POS else float(row.get(k, 0) or 0))
                    for k in POSITION_FIELDS if k in row
                })
            except Exception:
                pass
    return out


def _append_trade(trade: ClosedLiveTrade5m, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TRADE_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow(asdict(trade))


def _compute_summary(trades_path: Path) -> dict[str, Any]:
    if not trades_path.exists():
        return {
            "equity": STARTING_EQUITY, "closed_trades": 0,
            "wins": 0, "losses": 0, "win_rate": 0.0,
            "total_pnl": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
        }
    trades: list[ClosedLiveTrade5m] = []
    with open(trades_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                trades.append(ClosedLiveTrade5m(**{
                    k: (row[k] if k in STR_FIELDS_TRADE else float(row.get(k, 0) or 0))
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

    def __init__(self, tag: str = "default") -> None:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        # Per-market files prevent multi-thread overwrites (Finding 2.A)
        self._positions_file = OUT_DIR / f"positions_{tag}.csv"
        self._trades_file    = OUT_DIR / f"trades_{tag}.csv"
        self._summary_file   = OUT_DIR / f"summary_{tag}.json"
        self._tag            = tag
        self._auth_failed    = False   # set on 401 — halts new entries (Finding 3.A)
        self._cancelled_this_window: set[str] = set()  # re-entry guard (Finding 5.D)
        self._client  = get_client()
        self.positions: dict[str, LivePosition5m] = _load_positions(self._positions_file)
        open_count    = sum(1 for p in self.positions.values() if p.state == State.OPEN)
        pending_count = sum(1 for p in self.positions.values() if p.state == State.PENDING_ENTRY)
        print(f"[LIVE5M:{tag}] Loaded {open_count} open, {pending_count} pending-entry positions")
        self._repair_startup_state()
        self._cancel_expired_entries()

    def _repair_startup_state(self) -> None:
        """
        Startup repair: fix any PENDING_EXIT positions missing exit_placed_at.
        Without this, stuck-exit detection uses age=0 and the timeout never fires.
        Finding 1.E.
        """
        now = time.time()
        repaired = 0
        for pos in self.positions.values():
            if pos.state == State.PENDING_EXIT and pos.exit_placed_at == 0.0:
                pos.exit_placed_at = now
                repaired += 1
        if repaired:
            print(f"[LIVE5M:{self._tag}] Repaired exit_placed_at for {repaired} PENDING_EXIT position(s)")
            _save_positions(self.positions, self._positions_file)

        # Finding 7 (MEDIUM): Log open/pending counts on startup so operator can
        # cross-check the Polymarket UI for any untracked holdings.
        open_count         = sum(1 for p in self.positions.values() if p.state == State.OPEN)
        pending_exit_count = sum(1 for p in self.positions.values() if p.state == State.PENDING_EXIT)
        if open_count + pending_exit_count > 0:
            print(
                f"[LIVE5M:{self._tag}] STARTUP: {open_count} OPEN, {pending_exit_count} PENDING_EXIT. "
                f"Cross-check your Polymarket portfolio to verify these match."
            )

        # Place (or re-place) TP orders for OPEN positions that have none.
        # This handles restarts where the TP order was never placed or was lost.
        # Balance check inside _place_tp_order ensures we don't submit before fill settles.
        for pos_id, pos in list(self.positions.items()):
            if pos.state == State.OPEN and not pos.tp_order_id and pos.shares > 0:
                print(f"[LIVE5M:{self._tag}] Placing startup TP order for {pos_id} ({pos.asset} {pos.side})")
                self._place_tp_order(pos_id)

    def check_exchange_balances(
        self,
        token_id_up: str,
        token_id_down: str,
        slug: str = "",
    ) -> None:
        """
        Query Polymarket for actual conditional token balances and compare against
        our tracked positions. If we hold shares we have no position record for,
        log a CRITICAL warning so the operator can act before the position is lost.

        Call once after the first market fetch on startup (token IDs are required).
        This catches the case where positions_*.csv was deleted or never written,
        leaving real holdings on Polymarket with no exit management.
        """
        from py_clob_client.clob_types import BalanceAllowanceParams, AssetType

        for token_id, label in [(token_id_up, "UP"), (token_id_down, "DOWN")]:
            if not token_id:
                continue
            try:
                resp = self._client.get_balance_allowance(
                    BalanceAllowanceParams(
                        asset_type=AssetType.CONDITIONAL,
                        token_id=token_id,
                    )
                )
                raw = float(resp.get("balance", 0) or 0)
                shares = round(raw / 1_000_000, 4)
                if shares < 0.01:
                    continue  # dust / zero balance — nothing to worry about

                # Check whether we have a tracked open position for this token
                tracked = any(
                    p.token_id == token_id
                    and p.state in (State.OPEN, State.PENDING_EXIT, State.PENDING_ENTRY)
                    for p in self.positions.values()
                )
                if tracked:
                    print(
                        f"[LIVE5M:{self._tag}] BALANCE OK — {shares:.4f} shares of "
                        f"{label} ({slug}) — tracked in positions file ✓"
                    )
                else:
                    print(
                        f"\n[LIVE5M:{self._tag}] *** UNTRACKED HOLDING *** "
                        f"{shares:.4f} {label} shares of {slug} "
                        f"(token {token_id[:20]}...) are on Polymarket "
                        f"but NOT in our positions file. "
                        f"The bot will NOT manage or exit this position automatically. "
                        f"Sell manually on polymarket.com or restart the bot after "
                        f"manually adding a row to {self._positions_file.name}.\n"
                    )
            except Exception as exc:
                print(
                    f"[LIVE5M:{self._tag}] Balance check failed for {label} token "
                    f"{token_id[:20]}...: {exc}"
                )

    def _cancel_expired_entries(self) -> None:
        """On startup, cancel any PENDING_ENTRY orders whose window already closed."""
        now = time.time()
        for pos_id, pos in list(self.positions.items()):
            if pos.state == State.PENDING_ENTRY and pos.window_end_ts < now:
                print(f"[LIVE5M] STARTUP cancel orphaned entry {pos_id} (window expired)")
                self.cancel_entry(pos_id)

    def reset_window(self) -> None:
        """
        Clear the per-window re-entry guard. Call at the start of every new
        window so a fresh signal on the same market can trigger an entry again.
        Finding 5.D.
        """
        self._cancelled_this_window.clear()

    def already_in(self, condition_id: str) -> bool:
        return any(
            p.condition_id == condition_id
            for p in self.positions.values()
            if p.state in (State.PENDING_ENTRY, State.OPEN, State.PENDING_EXIT)
        )

    # ── TP order management ───────────────────────────────────────────────────

    def _place_tp_order(self, position_id: str) -> None:
        """
        Place a standing GTC SELL at take_profit immediately after fill confirmation.

        Polymarket will reject a SELL if the wallet balance hasn't settled yet
        (the fill needs a moment to propagate on-chain). We verify the balance via
        get_balance_allowance first. If the balance is still zero / too low, we
        return without placing — check_open_tp_fills() will retry on the next poll.
        """
        from py_clob_client.clob_types import BalanceAllowanceParams, AssetType

        pos = self.positions.get(position_id)
        if pos is None or pos.state != State.OPEN or not pos.token_id:
            return
        if pos.tp_order_id:
            return   # already on the book
        if pos.shares <= 0 or pos.take_profit <= 0:
            return

        # ── Verify balance has settled before posting the SELL ──────────────
        try:
            resp = self._client.get_balance_allowance(
                BalanceAllowanceParams(
                    asset_type=AssetType.CONDITIONAL,
                    token_id=pos.token_id,
                )
            )
            raw              = float(resp.get("balance", 0) or 0)
            confirmed_shares = round(raw / 1_000_000, 4)
            # Allow a 5% tolerance for rounding differences
            if confirmed_shares < pos.shares * 0.95:
                print(
                    f"[LIVE5M] TP deferred {position_id} — "
                    f"balance {confirmed_shares:.4f} < expected {pos.shares:.2f} shares "
                    f"(fill not settled yet, will retry)"
                )
                return
        except Exception as exc:
            print(
                f"[LIVE5M] Balance check before TP order failed for {position_id}: {exc} — "
                f"deferring TP order (will retry)"
            )
            return

        # ── Post GTC SELL at take_profit ────────────────────────────────────
        try:
            order_args = OrderArgs(
                price=pos.take_profit,
                size=pos.shares,
                side=SELL,
                token_id=pos.token_id,
            )
            signed   = self._client.create_order(order_args)
            resp_ord = self._client.post_order(signed, OrderType.GTC)
        except Exception as exc:
            print(f"[LIVE5M] TP order placement failed for {position_id}: {exc}")
            return

        order_id = resp_ord.get("orderID", "")
        if not order_id:
            print(f"[LIVE5M] TP order rejected for {position_id}: {resp_ord}")
            return

        pos.tp_order_id = order_id
        _save_positions(self.positions, self._positions_file)
        print(
            f"[LIVE5M] TP_ORDER {position_id} | {pos.asset} {pos.side} "
            f"GTC SELL {pos.shares:.2f} @ {pos.take_profit:.3f} | "
            f"tp_order_id={order_id[:16]}..."
        )

    def check_open_tp_fills(self) -> list[ClosedLiveTrade5m]:
        """
        Poll TP order status for all OPEN positions.
        - If tp_order_id is set and the order is filled → settle as take_profit exit.
        - If tp_order_id is missing (balance deferred) → retry _place_tp_order.

        Call every poll cycle alongside check_pending_exits().
        Returns list of trades closed this call.
        """
        closed: list[ClosedLiveTrade5m] = []
        for pos_id, pos in list(self.positions.items()):
            if pos.state != State.OPEN:
                continue

            # Retry placing if balance wasn't settled on the last attempt
            if not pos.tp_order_id:
                if pos.shares > 0:
                    self._place_tp_order(pos_id)
                continue

            try:
                order = self._client.get_order(pos.tp_order_id)
            except Exception as exc:
                print(f"[LIVE5M] get_order (TP) failed for {pos_id}: {exc}")
                continue

            status = order.get("status", "")
            if status in ("matched", "filled"):
                actual_exit = float(order.get("average_price") or pos.take_profit)
                trade = self._settle_exit(pos_id, actual_exit, "take_profit", 0.0)
                if trade:
                    closed.append(trade)

        return closed

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
        # Dashboard pause flag — halts new entries, existing positions keep running
        if PAUSE_FLAG.exists():
            print(f"[LIVE5M] PAUSED — not placing new entries (delete paused.flag to resume)")
            return None

        # Auth failure guard — halt new entries after a 401 (Finding 3.A)
        if self._auth_failed:
            # Finding 8 (MEDIUM): clearer message so operator knows what action to take
            print(f"[LIVE5M] BLOCKED — auth failed (401). Restart bot after fixing credentials. "
                  f"Existing positions are still being managed.")
            return None

        # Re-entry guard — don't re-enter a market we already cancelled this window (Finding 5.D)
        if condition_id in self._cancelled_this_window:
            print(f"[LIVE5M] Skip — already cancelled entry for {condition_id} this window")
            return None

        if self.already_in(condition_id):
            return None

        # Price sanity check — CLOB feed garbage in → bad order (Finding 5.A)
        if not (0.01 <= entry_price <= 0.99):
            print(f"[LIVE5M] Skip — entry_price {entry_price} out of sane range [0.01, 0.99]")
            return None
        if not (0.01 <= take_profit <= 0.99):
            print(f"[LIVE5M] Skip — take_profit {take_profit} out of sane range [0.01, 0.99]")
            return None

        # Round shares to 2dp — Polymarket CLOB standard (Finding 5.C)
        shares = round(POSITION_SIZE / entry_price, 2)
        if shares < MIN_SHARES:
            print(f"[LIVE5M] Skip — {shares:.2f} shares below minimum {MIN_SHARES}")
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

        # Build and persist position BEFORE placing the order — if we crash between
        # place and record, we'll see the PENDING_ENTRY on restart and can check/cancel.
        # (Finding 1.F pre-save)
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
            entry_order_id="__pending__",   # placeholder until API returns order_id
            token_id=token_id,
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
        _save_positions(self.positions, self._positions_file)

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
            exc_str = str(exc)
            if "401" in exc_str or "Unauthorized" in exc_str:
                self._auth_failed = True
                print(f"[LIVE5M] AUTH FAILURE — halting new entries: {exc}")
            else:
                print(f"[LIVE5M] Entry order failed: {exc}")
            # Remove the pre-saved position since no order was placed
            self.positions.pop(pos.position_id, None)
            _save_positions(self.positions, self._positions_file)
            return None

        order_id = resp.get("orderID", "")
        if not order_id:
            print(f"[LIVE5M] Entry order rejected: {resp}")
            self.positions.pop(pos.position_id, None)
            _save_positions(self.positions, self._positions_file)
            return None

        # Update with real order_id now that we have it
        pos.entry_order_id = order_id
        _save_positions(self.positions, self._positions_file)

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
            if pos.entry_order_id and pos.entry_order_id != "__pending__":
                self._client.cancel(pos.entry_order_id)
            print(f"[LIVE5M] CANCEL {position_id} | entry order cancelled (window expired)")
        except Exception as exc:
            print(f"[LIVE5M] Cancel failed for {position_id}: {exc}")

        # Finding 1 (CRITICAL): Verify the cancel actually worked — if the order filled
        # between the last poll and the cancel call, transition to OPEN instead of
        # discarding the shares. Without this, real shares are silently lost.
        if pos.entry_order_id and pos.entry_order_id != "__pending__":
            try:
                order        = self._client.get_order(pos.entry_order_id)
                status       = order.get("status", "")
                raw_matched  = order.get("size_matched", 0) or 0
                size_matched = float(raw_matched)
                if status in ("matched", "filled") and size_matched > 0:
                    avg_price = order.get("average_price")
                    if avg_price:
                        try:
                            pos.entry_price = round(float(avg_price), 6)
                        except (TypeError, ValueError):
                            pass
                    pos.shares = round(size_matched, 2)
                    pos.state  = State.OPEN
                    _save_positions(self.positions, self._positions_file)
                    print(
                        f"[LIVE5M] CANCEL→OPEN {position_id} — order filled before cancel; "
                        f"now tracking {pos.shares:.2f} shares @ {pos.entry_price:.4f}"
                    )
                    # Place standing GTC SELL at TP for this surprise fill
                    self._place_tp_order(position_id)
                    return   # do NOT remove or mark cancelled
            except Exception as exc2:
                print(
                    f"[LIVE5M] Post-cancel status check failed for {position_id}: {exc2} — "
                    f"treating as cancelled; verify manually on Polymarket"
                )

        # Record so we don't re-enter this market in the same window (Finding 5.D)
        self._cancelled_this_window.add(pos.condition_id)
        pos.state = State.CANCELLED
        self.positions.pop(position_id, None)
        _save_positions(self.positions, self._positions_file)

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

            # Finding 2 (CRITICAL): Placeholder entries — API call was never made (crash
            # between pre-save and post_order). If stuck >30s the API call is gone — clean up.
            if pos.entry_order_id == "__pending__":
                orphan_age = now - pos.opened_at
                if orphan_age > 30:
                    print(
                        f"[LIVE5M] ORPHAN {pos_id} — stuck as __pending__ for {orphan_age:.0f}s "
                        f"(API call never completed), removing"
                    )
                    self._cancelled_this_window.add(pos.condition_id)
                    pos.state = State.CANCELLED
                    self.positions.pop(pos_id, None)
                    _save_positions(self.positions, self._positions_file)
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

            status       = order.get("status", "")
            raw_matched  = order.get("size_matched", 0) or 0
            size_matched = float(raw_matched)

            if status in ("matched", "filled") and size_matched > 0:
                # Use actual fill price if available (Finding 3.C)
                avg_price = order.get("average_price")
                if avg_price:
                    try:
                        pos.entry_price = round(float(avg_price), 6)
                    except (TypeError, ValueError):
                        pass
                pos.shares = round(size_matched, 2)
                pos.state  = State.OPEN
                _save_positions(self.positions, self._positions_file)
                print(
                    f"[LIVE5M] FILLED {pos_id} | {pos.asset} {pos.side} "
                    f"{pos.shares:.2f} shares @ {pos.entry_price:.3f}"
                )
                # Place standing GTC SELL at TP immediately — verify balance first
                self._place_tp_order(pos_id)

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
        - take_profit: GTC limit at take_profit price (sits on book)
        - hard_stop / force_exit_time / window_expired / etc: aggressive FOK at 0.01
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
            "force_exit_time", "force_exit_stuck",
            "window_expired",
        }
        if exit_reason in aggressive_reasons:
            exit_price = AGGRESSIVE_EXIT_PRICE
            order_type = OrderType.FOK   # Fill or Kill — must fill immediately
            # Cancel the standing TP order before firing the aggressive exit,
            # otherwise both orders would try to sell the same shares.
            if pos.tp_order_id:
                try:
                    self._client.cancel(pos.tp_order_id)
                    print(
                        f"[LIVE5M] Cancelled TP order {pos.tp_order_id[:16]}... "
                        f"before aggressive exit ({exit_reason})"
                    )
                except Exception as exc:
                    print(f"[LIVE5M] TP cancel failed before {exit_reason} for {position_id}: {exc} — continuing")
                pos.tp_order_id = ""
        else:
            # take_profit — if a GTC SELL is already on the book, it will fill at
            # exchange level without any intervention. Skip the redundant place_exit call.
            if pos.tp_order_id:
                print(
                    f"[LIVE5M] TP order already on book for {position_id} "
                    f"(order {pos.tp_order_id[:16]}...) — no action needed"
                )
                return
            exit_price = pos.take_profit
            order_type = OrderType.GTC

        # Finding 3 (HIGH): Pre-save as PENDING_EXIT before the API call. If the process
        # crashes between post_order() and the save, restart sees PENDING_EXIT and checks
        # fills rather than placing a duplicate exit order.
        pos.exit_placed_at = time.time()
        pos.exit_reason    = exit_reason
        pos.exit_order_id  = "__pending_exit__"
        pos.state          = State.PENDING_EXIT
        _save_positions(self.positions, self._positions_file)

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
            exc_str = str(exc)
            if "401" in exc_str or "Unauthorized" in exc_str:
                self._auth_failed = True
                print(f"[LIVE5M] AUTH FAILURE during exit for {position_id}: {exc}")
            else:
                print(f"[LIVE5M] Exit order failed for {position_id}: {exc}")
            # Revert pre-save — no order was placed
            pos.state          = State.OPEN
            pos.exit_order_id  = ""
            pos.exit_placed_at = 0.0
            pos.exit_reason    = ""
            _save_positions(self.positions, self._positions_file)
            return

        order_id = resp.get("orderID", "")
        if not order_id and order_type != OrderType.FOK:
            # GTC exit with no order_id means the API rejected it — revert pre-save.
            print(f"[LIVE5M] Exit order rejected (no orderID): {resp}")
            pos.state          = State.OPEN
            pos.exit_order_id  = ""
            pos.exit_placed_at = 0.0
            pos.exit_reason    = ""
            _save_positions(self.positions, self._positions_file)
            return

        pos.exit_order_id  = order_id   # replace __pending_exit__ with real ID
        _save_positions(self.positions, self._positions_file)

        print(
            f"[LIVE5M] EXIT   {position_id} | {exit_reason} "
            f"SELL {pos.shares:.2f} @ {exit_price:.3f} | "
            f"order_id={order_id[:16] if order_id else 'FOK-immediate'}..."
        )

        # FOK: verify it actually filled before settling — a FOK with no bids is killed silently
        if order_type == OrderType.FOK:
            try:
                if order_id:
                    fok_status  = self._client.get_order(order_id)
                    raw_matched = fok_status.get("size_matched", 0) or 0
                    matched     = float(raw_matched)
                    if matched <= 0:
                        print(f"[LIVE5M] FOK KILLED for {position_id} — no bids, resetting to OPEN")
                        pos.state          = State.OPEN
                        pos.exit_order_id  = ""
                        pos.exit_placed_at = 0.0
                        pos.exit_reason    = ""
                        _save_positions(self.positions, self._positions_file)
                        return
                    actual_exit = float(fok_status.get("average_price") or exit_price)
                else:
                    print(f"[LIVE5M] FOK REJECTED (no orderID) for {position_id} — resetting to OPEN")
                    pos.state          = State.OPEN
                    pos.exit_order_id  = ""
                    pos.exit_placed_at = 0.0
                    pos.exit_reason    = ""
                    _save_positions(self.positions, self._positions_file)
                    return
            except Exception as exc:
                print(f"[LIVE5M] FOK status check failed for {position_id}: {exc} — resetting to OPEN")
                pos.state          = State.OPEN
                pos.exit_order_id  = ""
                pos.exit_placed_at = 0.0
                pos.exit_reason    = ""
                _save_positions(self.positions, self._positions_file)
                return
            self._settle_exit(position_id, actual_exit, exit_reason, price_60s_after_entry)

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

            # Finding 3: __pending_exit__ means place_exit() pre-saved but the API call
            # hasn't returned yet (or crashed mid-call). Let the stuck-exit timeout handle
            # it after EXIT_STUCK_TIMEOUT seconds rather than acting immediately.
            if pos.exit_order_id == "__pending_exit__":
                exit_age = (now - pos.exit_placed_at) if pos.exit_placed_at > 0 else 0
                if exit_age <= EXIT_STUCK_TIMEOUT:
                    continue   # still within grace period — wait for place_exit() to update
                # Timeout on __pending_exit__ — treat as a failed pre-save: rescue via FOK
                print(f"[LIVE5M] STUCK __pending_exit__ {pos_id} — rescuing via FOK")
                pos.state          = State.OPEN
                pos.exit_order_id  = ""
                pos.exit_placed_at = 0.0
                _save_positions(self.positions, self._positions_file)
                if pos.token_id:
                    self.place_exit(pos_id, pos.token_id, "force_exit_stuck", price_60s_after_entry)
                else:
                    print(f"[LIVE5M] CRITICAL: no token_id for {pos_id}, cannot rescue __pending_exit__")
                continue

            # Rescue: GTC exit stuck too long — cancel and re-submit as aggressive FOK
            exit_age = (now - pos.exit_placed_at) if pos.exit_placed_at > 0 else 0
            if not pos.exit_order_id or exit_age > EXIT_STUCK_TIMEOUT:
                age_str = f"{exit_age:.0f}s" if pos.exit_placed_at > 0 else "unknown age"
                print(f"[LIVE5M] STUCK EXIT {pos_id} — pending {age_str}, re-submitting as FOK")
                # Finding 9 (LOW): log escalation after multiple failed rescue attempts
                pos.exit_retry_count = getattr(pos, "exit_retry_count", 0) + 1
                if pos.exit_retry_count > 3:
                    print(
                        f"[LIVE5M] CRITICAL: {pos_id} has failed exit {pos.exit_retry_count} times. "
                        f"Manual intervention may be required on Polymarket."
                    )
                if pos.exit_order_id and pos.exit_order_id != "__pending__":
                    try:
                        self._client.cancel(pos.exit_order_id)
                    except Exception:
                        pass
                pos.state          = State.OPEN
                pos.exit_order_id  = ""
                pos.exit_placed_at = 0.0
                _save_positions(self.positions, self._positions_file)
                # place_exit() requires token_id — use stored value
                if pos.token_id:
                    self.place_exit(pos_id, pos.token_id, "force_exit_stuck", price_60s_after_entry)
                else:
                    print(f"[LIVE5M] CRITICAL: no token_id for {pos_id}, cannot place rescue exit")
                continue

            try:
                order = self._client.get_order(pos.exit_order_id)
            except Exception as exc:
                print(f"[LIVE5M] get_order (exit) failed for {pos_id}: {exc}")
                continue

            status = order.get("status", "")
            if status in ("matched", "filled"):
                actual_exit = float(order.get("average_price") or pos.take_profit)
                trade = self._settle_exit(pos_id, actual_exit, pos.exit_reason or "take_profit", price_60s_after_entry)
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
            return None

        gross_proceeds = pos.shares * actual_exit_price
        pnl_usd    = gross_proceeds - pos.size_usd
        return_pct = pnl_usd / pos.size_usd * 100
        hold_sec   = time.time() - pos.opened_at

        # Build the closed trade — note exit_reason comes from the parameter,
        # not pos.exit_reason, since the reason may be overridden (e.g. force_exit_stuck).
        # We must exclude exit_reason from asdict(pos) to avoid duplicate-kwarg TypeError.
        pos_dict = asdict(pos)
        pos_dict.pop("exit_reason", None)

        trade = ClosedLiveTrade5m(
            **pos_dict,
            exit_reason=exit_reason,
            price_60s_after_entry=round(price_60s_after_entry, 4),
            exit_price=actual_exit_price,
            exit_fee_usd=0.0,    # maker orders: 0% fee
            closed_at=time.time(),
            hold_seconds=round(hold_sec, 1),
            pnl_usd=round(pnl_usd, 4),
            return_pct=round(return_pct, 2),
        )
        _append_trade(trade, self._trades_file)
        _save_positions(self.positions, self._positions_file)

        emoji = "WIN " if pnl_usd > 0 else "LOSS"
        print(
            f"[LIVE5M] CLOSE {position_id} | {emoji} ${pnl_usd:+.2f} ({return_pct:+.1f}%) "
            f"| {exit_reason} | hold={hold_sec:.0f}s"
        )
        return trade

    # ── Summary ───────────────────────────────────────────────────────────────

    def summary(self) -> dict[str, Any]:
        s = _compute_summary(self._trades_file)
        s["open_positions"]    = sum(1 for p in self.positions.values() if p.state == State.OPEN)
        s["pending_positions"] = sum(1 for p in self.positions.values() if p.state == State.PENDING_ENTRY)
        return s

    def save_summary(self) -> None:
        self._summary_file.write_text(json.dumps(self.summary(), indent=2), encoding="utf-8")
