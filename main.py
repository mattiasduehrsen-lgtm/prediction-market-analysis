"""
Polymarket Paper Trading Bot
=============================
Commands:
  python main.py btc-5m-loop               — 5-minute BTC mean-reversion bot (primary)
  python main.py multi-loop [CONFIGS...]   — run multiple markets in parallel threads
  python main.py paper-loop                — daily BTC strike market bot (legacy)
  python main.py dashboard                 — web dashboard
  python main.py status                    — print current state and exit

CONFIGS format: ASSET:WINDOW:STRATEGY  (e.g. BTC:5m:mean_reversion SOL:15m:mean_reversion)
  ASSET:    BTC ETH SOL XRP
  WINDOW:   5m 15m
  STRATEGY: mean_reversion momentum
"""
from __future__ import annotations

import io
import json
import math
import os
import pathlib
import sys
import threading
import time

from dotenv import load_dotenv

load_dotenv()

LOOP_SLEEP    = float(os.environ.get("LOOP_SLEEP_SECONDS", "30"))
MAX_POSITIONS = int(os.environ.get("MAX_POSITIONS", "5"))
# Absolute path so the log lands next to main.py regardless of CWD
LOG_FILE      = str(pathlib.Path(__file__).resolve().parent / "bot.log")


# ── Logging ───────────────────────────────────────────────────────────────────

class _Tee(io.RawIOBase):
    """Write to both the log file and the original console simultaneously."""
    def __init__(self, log_raw, console):
        self._log = log_raw
        self._con = console

    def write(self, b):
        self._log.write(b)
        try:
            self._con.buffer.write(b)
            self._con.buffer.flush()
        except Exception:
            pass
        return len(b)

    def readable(self):  return False
    def writable(self):  return True
    def seekable(self):  return False


def _setup_logging() -> None:
    """Tee stdout/stderr to bot.log AND keep output visible in the console window."""
    log = io.FileIO(LOG_FILE, mode="ab")
    tee = _Tee(log, sys.stdout)
    wrapped = io.TextIOWrapper(tee, encoding="utf-8", write_through=True)
    sys.stdout = wrapped
    sys.stderr = wrapped


# ── Core loop ─────────────────────────────────────────────────────────────────

def run_loop() -> None:
    from src.bot import btc_feed, btc_markets, signal
    from src.bot.paper_engine import PaperEngine

    print(f"\n{'='*60}")
    print(f"BTC Paper Trading Bot — {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Loop interval: {LOOP_SLEEP}s | Max positions: {MAX_POSITIONS}")
    print(f"{'='*60}\n")

    # Start BTC price feed
    btc_feed.start()
    print("[MAIN] Waiting for BTC price feed...")
    state = btc_feed.wait_for_price(timeout=15)
    if not state:
        print("[MAIN] ERROR: Could not connect to Binance. Exiting.")
        sys.exit(1)
    print(f"[MAIN] BTC price: ${state.price:,.2f}\n")

    engine = PaperEngine()
    iteration = 0

    while True:
        iteration += 1
        now = time.strftime("%H:%M:%S")
        print(f"\n--- Iteration {iteration} [{now}] ---")

        try:
            _run_once(engine, btc_feed, btc_markets, signal)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            print(f"[MAIN] Iteration error: {exc}")

        try:
            time.sleep(LOOP_SLEEP)
        except BaseException:
            pass


def _run_once(engine, btc_feed_mod, btc_markets_mod, signal_mod) -> None:
    # 1. Get current BTC state
    btc = btc_feed_mod.get_state()
    if btc.price <= 0 or btc.is_stale():
        print(f"[MAIN] BTC feed stale — skipping")
        return

    print(
        f"[BTC] price=${btc.price:,.2f} | "
        f"1m={btc.momentum_1m:+.3f}% | "
        f"5m={btc.momentum_5m:+.3f}% | "
        f"dir={btc.direction}"
    )

    # 2. Get market snapshot
    snapshot = btc_markets_mod.fetch()
    if not snapshot:
        print("[MAIN] No market snapshot — skipping")
        return

    if snapshot.markets:
        atm = snapshot.atm_markets(btc.price, n=3)
        atm_str = " | ".join(
            f"${m.strike//1000}k YES={m.yes_price:.2f}" for m in atm
        )
        print(f"[MARKETS] ATM: {atm_str} | expires {snapshot.event_end[:10]}")

    # 3. Check exits for open positions
    _check_exits(engine, snapshot, btc)

    # 4. Check entries if we have room
    open_count = len(engine.positions)
    if open_count >= MAX_POSITIONS:
        print(f"[MAIN] At max positions ({open_count}/{MAX_POSITIONS}) — no new entries")
    else:
        _check_entries(engine, snapshot, btc, signal_mod)

    # 5. Save summary
    engine.save_summary()
    s = engine.summary()
    print(
        f"[SUMMARY] equity=${s['equity']:.2f} | "
        f"open={s['open_positions']} | "
        f"closed={s['closed_trades']} ({s['wins']}W/{s['losses']}L) | "
        f"pnl=${s['total_pnl']:+.2f} | "
        f"win_rate={s['win_rate']:.0f}%"
    )


def _check_exits(engine, snapshot, btc) -> None:
    from src.bot.signal import should_exit
    if not engine.positions:
        return

    for pos_id, pos in list(engine.positions.items()):
        # Find current price for this market
        market = snapshot.find_strike(pos.strike)
        if market is None:
            # Market not in snapshot — close on expiry or skip
            if pos.strike not in [m.strike for m in snapshot.markets]:
                # Might be a new-day rollover; close it
                engine.close(pos_id, 0.5, "market_not_found")
            continue

        current_yes = market.yes_price
        hours_left  = market.hours_to_expiry

        do_exit, reason = should_exit(
            side=pos.side,
            entry_price=pos.entry_price,
            current_yes_price=current_yes,
            take_profit=pos.take_profit,
            stop_loss=pos.stop_loss,
            hours_to_expiry=hours_left,
        )

        if do_exit:
            engine.close(pos_id, current_yes, reason)
        else:
            current_pos_price = current_yes if pos.side == "YES" else 1 - current_yes
            pnl_pct = (current_pos_price - pos.entry_price) / pos.entry_price * 100
            print(
                f"[HOLD] {pos.position_id} {pos.side} ${pos.strike:,} "
                f"entry={pos.entry_price:.3f} now={current_pos_price:.3f} "
                f"pnl={pnl_pct:+.1f}% | {hours_left:.1f}h left"
            )


def _check_entries(engine, snapshot, btc, signal_mod) -> None:
    signals = signal_mod.generate(snapshot, btc)
    if not signals:
        print("[MAIN] No signals this cycle")
        return

    for sig in signals:
        if len(engine.positions) >= MAX_POSITIONS:
            break
        if engine.already_in(sig.condition_id):
            continue
        engine.open(sig)


# ── 5-minute Up/Down loop ─────────────────────────────────────────────────────

BINANCE_SYMBOLS: dict[str, str] = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "SOL": "SOLUSDT",
    "XRP": "XRPUSDT",
}


def _fetch_price(symbol: str = "BTCUSDT") -> float:
    """Quick Binance spot price — used for trade context capture."""
    import httpx as _httpx
    try:
        r = _httpx.get(
            "https://api.binance.com/api/v3/ticker/price",
            params={"symbol": symbol},
            timeout=5,
        )
        return float(r.json()["price"])
    except Exception:
        return 0.0


class BinanceFeed:
    """
    Background thread that fetches Binance spot price on a fixed interval.

    Replaces the blocking _fetch_price() call in the poll loop. The main
    loop reads self.get() — an instant cached read — instead of waiting
    100-300ms for each Binance REST round-trip.
    """

    def __init__(self, symbol: str, interval: float = 2.0) -> None:
        import httpx as _httpx
        self._symbol   = symbol
        self._interval = interval
        self._price: float = 0.0
        self._lock  = threading.Lock()
        self._http  = _httpx.Client(timeout=5)
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"binance-{symbol}")
        self._thread.start()

    def _run(self) -> None:
        while True:
            try:
                r = self._http.get(
                    "https://api.binance.com/api/v3/ticker/price",
                    params={"symbol": self._symbol},
                )
                price = float(r.json()["price"])
                with self._lock:
                    self._price = price
            except Exception:
                pass
            time.sleep(self._interval)

    def get(self) -> float:
        with self._lock:
            return self._price


def run_5m_loop(
    asset: str = "BTC",
    live: bool = False,
    window: str = "5m",
    strategy: str = "mean_reversion",
    cb=None,   # shared CircuitBreaker for multi-thread live mode (Finding 2.B)
) -> None:
    import collections
    from src.bot.market_5m import (
        fetch_market, fetch_live_prices, WINDOW_SECONDS,
        FORCE_EXIT, ENTRY_MIN, ENTRY_MAX, MIN_SECONDS, BTC_SKIP_RATE,
        MOMENTUM_ENTRY_WINDOW, MOMENTUM_MIN_PREV_MOVE,
    )
    from src.bot.signal_5m import should_enter, should_enter_momentum, should_exit, take_profit_price
    from src.bot.claude_advisor import advise_entry
    from src.bot.chainlink_feed import ChainlinkFeed

    # Live: default 1s for faster fill detection and exit reactions.
    # Paper: 2s (no real money, save Binance API quota).
    # Override via LIVE_POLL_INTERVAL_SECONDS / PAPER_POLL_INTERVAL_SECONDS in .env.
    if live:
        POLL_INTERVAL = int(os.environ.get("LIVE_POLL_INTERVAL_SECONDS", "1"))
    else:
        POLL_INTERVAL = int(os.environ.get("PAPER_POLL_INTERVAL_SECONDS", "2"))
    window_seconds = WINDOW_SECONDS.get(window, 300)
    # Mean-reversion: enter in first 60s of window regardless of window size
    mr_min_seconds = window_seconds - 60
    # Soft exit scales with window: 5m→115s, 15m→420s
    # Cowork 2026-04-18: winners resolve at median 256s; losers that haven't
    # reverted by minute 10 almost never do. 420s triggers soft-exit 2 min
    # earlier than the old 300s setting, cutting extended loser hold time.
    soft_exit_secs        = 115 if window == "5m" else 420
    # Hard-stop gate: for 15m windows only fire in last 4 minutes (240s remaining).
    # Cowork 2026-04-18: the gate was documented but never wired — hard-stops were
    # firing at median 45% through the window (minute 7), same as the 5m bot.
    # Gating it preserves recovery time for positions that are down early.
    hard_stop_max_remaining = 240.0 if window == "15m" else float("inf")

    binance_symbol = BINANCE_SYMBOLS.get(asset.upper(), "BTCUSDT")

    mode_str = "LIVE" if live else "PAPER"
    print(f"\n{'='*60}")
    print(f"{window} Up/Down Bot [{mode_str}|{strategy}] — {asset} — {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    if live:
        from src.bot.live_engine_5m import LiveEngine5m
        from src.bot.circuit_breaker import CircuitBreaker
        engine = LiveEngine5m(tag=f"{asset}-{window}")   # per-market file (Finding 2.A)
        if cb is None:
            cb = CircuitBreaker()   # reads LIVE_MAX_DAILY_LOSS_USD from .env (Finding 6.B)
        print(cb.status())
    else:
        from src.bot.engine_5m import Engine5m
        engine = Engine5m(tag=f"{asset}-{window}-{strategy}")
        cb = None

    from src.bot.tick_logger import TickLogger
    from src.bot.clob_feed import ClobFeed
    from src.bot.market_store import BINANCE_SPOT, flush_all
    tick_logger = TickLogger()
    print("[MAIN] Tick logger active — writing price_ticks.csv every 5s")
    clob_feed = ClobFeed()
    clob_feed.start()
    print("[MAIN] CLOB WebSocket feed active — event-driven prices → clob_events.csv")

    # Binance price in background thread — removes blocking REST call from poll loop
    binance_feed = BinanceFeed(binance_symbol, interval=2.0)
    print(f"[MAIN] Binance feed active ({binance_symbol}) — non-blocking background poll")

    # Start Chainlink feed — actual window start prices, not stale API data
    feed = ChainlinkFeed(asset)
    feed.start()
    print("[MAIN] Waiting for Chainlink price feed...")
    cl = feed.wait_for_price(timeout=15)
    if cl:
        print(f"[MAIN] Chainlink {asset}: ${cl.price:,.2f}")
    else:
        print("[MAIN] Chainlink unavailable — continuing without window-start tracking")

    iteration = 0
    last_summary_ts: float = 0.0   # time-based summary — stays at ~60s regardless of POLL_INTERVAL
    _balance_checked = False        # run exchange reconciliation once after first market fetch
    market = None   # cached — only refetched when window expires

    # ── Context tracking for ML data capture ──────────────────────────────────
    # Rolling price history for the current window: deque of (timestamp, up_price)
    price_history: collections.deque = collections.deque(maxlen=300)
    # Continuous BTC price history — NOT reset on window change (independent of windows)
    # maxlen=450 @ 2s poll = 15 minutes of continuous BTC price data
    # Extended from 150 (5m) to 450 (15m) for realized-vol filter (Cowork 2026-04-18)
    btc_history: collections.deque = collections.deque(maxlen=450)
    btc_at_window_start: float = 0.0   # Binance BTC/USD when window opened
    up_price_at_window_start: float = 0.5  # first CLOB midpoint reading for window
    window_stopped: set = set()  # condition_ids that hit a stop this window (currently unused)
    # Resolution tracking — record prev window's condition_id and Chainlink start price
    # so we can fill resolution_side/our_side_won when the window closes
    prev_condition_id: str = ""
    prev_cl_start_price: float = 0.0
    # Skip tracking — best opportunity seen during each window's entry window (first 45s)
    # Logged to skipped_windows.csv when entry window closes without a trade
    best_opp_price: float = 1.0   # lowest cheaper-side price seen in entry window
    best_opp_side: str = ""
    entry_window_logged: bool = False  # prevent duplicate log entries per window
    # Claude advisor — called once per window early in entry window, result cached
    window_advisor_enter: bool = True   # default ENTER until advisor responds
    window_advisor_consulted: bool = False  # True once advisor has been called this window
    window_advisor_reason: str = ""     # advisor's explanation text (for skip log)

    while True:
        iteration += 1
        now_str = time.strftime("%H:%M:%S")

        try:
            # Refetch market structure from Gamma only on startup or window change.
            # outcomePrices from Gamma is stale — only token IDs and slug are needed here.
            if market is None or market.is_expired():
                # ── Resolution: fill prev window's outcome before resetting ──────
                if market is not None and prev_condition_id and prev_cl_start_price > 0:
                    cl_now = feed.get_state()
                    if cl_now.price > 0:
                        resolution_side = "UP" if cl_now.price >= prev_cl_start_price else "DOWN"
                        engine.update_resolution(prev_condition_id, resolution_side)

                new_market = fetch_market(asset, window)
                if new_market is None:
                    print(f"[{now_str}] No active market found — retrying...")
                    time.sleep(POLL_INTERVAL)
                    continue
                market = new_market

                # One-time startup: check Polymarket for untracked holdings.
                # Detects positions held on exchange but missing from positions file
                # (e.g. file deleted, process killed before save, previous session crash).
                if live and not _balance_checked:
                    _balance_checked = True
                    engine.check_exchange_balances(
                        token_id_up=market.token_id_up,
                        token_id_down=market.token_id_down,
                        slug=market.slug,
                    )

                # Subscribe CLOB WebSocket to the new window's token IDs
                clob_feed.subscribe(
                    token_id_up=market.token_id_up,
                    token_id_down=market.token_id_down,
                    condition_id=market.condition_id,
                    slug=market.slug,
                    window_end_ts=market.window_end_ts,
                )

                # Reset per-window context
                price_history.clear()
                window_stopped.clear()
                if live:
                    engine.reset_window()   # clear re-entry guard (Finding 5.D)
                btc_at_window_start = binance_feed.get()
                up_price_at_window_start = market.up_price  # Gamma initial price (≈0.5)

                # Save this window's starting state for resolution at next transition
                if not live:
                    prev_condition_id = market.condition_id
                    cl_start = feed.get_state()
                    prev_cl_start_price = cl_start.price  # 0.0 if feed unavailable — handled above

                # Reset skip tracking and advisor for new window
                best_opp_price = 1.0
                best_opp_side = ""
                entry_window_logged = False
                window_advisor_enter = True
                window_advisor_consulted = True   # disabled: advisor blocks 96% of in-range windows (wrong mental model for mean-reversion)
                window_advisor_reason = ""

                cl = feed.get_state()
                secs = market.seconds_remaining
                cl_str = (
                    f"CL=${cl.price:,.2f} start=${cl.window_start_price:,.2f} Δ{cl.pct_change:+.3f}%"
                    if cl.price > 0 else "CL=unavailable"
                )
                btc_str = f" | BTC=${btc_at_window_start:,.2f}" if btc_at_window_start else ""
                print(f"\n[NEW WINDOW] {market.slug} | {secs:.0f}s | liq=${market.liquidity:,.0f} | {cl_str}{btc_str}")

            # Live prices — WebSocket feed first (event-driven, sub-second);
            # fall back to REST midpoint poll every 2s if feed is not yet ready.
            up_ws, down_ws, ws_ok = clob_feed.get_prices()
            if ws_ok:
                market.up_price, market.down_price = up_ws, down_ws
                clob_ok = True
            else:
                market.up_price, market.down_price, clob_ok = fetch_live_prices(market)
            cl = feed.get_state()
            secs = market.seconds_remaining

            # Record price history for this window
            price_history.append((time.time(), market.up_price))

            # Continuous BTC price — non-blocking read from background BinanceFeed
            btc_now = binance_feed.get()
            if btc_now > 0:
                btc_history.append((time.time(), btc_now))
                BINANCE_SPOT.append({
                    "ts":    round(time.time(), 3),
                    "asset": asset,
                    "price": btc_now,
                })

            # Update window-start price with first good CLOB reading
            if clob_ok and up_price_at_window_start == 0.5 and market.up_price != 0.5:
                up_price_at_window_start = market.up_price

            # Order book state — best bid/ask, spread, depth (zeros if WS not ready)
            book_bid, book_ask, book_spread, book_bid_depth, book_ask_depth = clob_feed.get_book_state()

            src = "ws" if ws_ok else ("rest" if clob_ok else "cached")
            tick_logger.tick(
                condition_id=market.condition_id,
                slug=market.slug,
                up_price=market.up_price,
                down_price=market.down_price,
                seconds_left=secs,
                source=src,
            )
            cl_info = f"CL={cl.pct_change:+.3f}%" if cl.price > 0 else ""
            print(
                f"[{now_str}] {asset} UP={market.up_price:.3f} DOWN={market.down_price:.3f} "
                f"[{src}] | {secs:.0f}s left {cl_info}"
            )

            # ── Claude advisor — once per window, first live poll in entry window ─
            if not live and not window_advisor_consulted and clob_ok and secs >= MIN_SECONDS:
                cheap_side   = "UP" if market.up_price <= market.down_price else "DOWN"
                cheap_price  = min(market.up_price, market.down_price)
                # Compute BTC rates from btc_history for advisor context
                _adv_rate_pm = 0.0; _adv_rate_10s = 0.0; _adv_rate_30s = 0.0
                if len(btc_history) >= 2:
                    _lt, _lp = btc_history[-1]
                    for _ot, _op in btc_history:
                        _el = _lt - _ot
                        if _el >= 5  and _adv_rate_pm  == 0.0: _adv_rate_pm  = (_lp - _op) / (_el / 60.0)
                        if _el >= 10 and _adv_rate_10s == 0.0: _adv_rate_10s = (_lp - _op) / (_el / 60.0)
                        if _el >= 30 and _adv_rate_30s == 0.0: _adv_rate_30s = (_lp - _op) / (_el / 60.0)
                        if _adv_rate_pm and _adv_rate_10s and _adv_rate_30s: break
                _adv_decel = round(_adv_rate_10s / _adv_rate_30s, 4) if abs(_adv_rate_30s) > 1.0 else 0.0
                _adv_cross = round(
                    (cl.window_start_price - cl.prev_window_start_price) / cl.prev_window_start_price * 100, 4
                ) if cl.prev_window_start_price > 0 and cl.window_start_price > 0 else 0.0
                window_advisor_consulted = True  # set before call — prevents double-call on any exception
                window_advisor_enter, window_advisor_reason = advise_entry(
                    side=cheap_side,
                    entry_price=cheap_price,
                    cl_pct_change=cl.pct_change if cl.price > 0 else 0.0,
                    btc_rate_per_min=_adv_rate_pm,
                    btc_momentum_decel=_adv_decel,
                    cross_window_pct=_adv_cross,
                    cheap_side_velocity=0.0,   # no history yet at window start
                    secs_remaining=secs,
                )

            # ── Advance live order state machine ───────────────────────────────
            if live:
                engine.check_pending_entries()
                for closed_trade in engine.check_pending_exits():
                    if cb:
                        cb.record_trade(closed_trade.pnl_usd)
                # Poll standing TP orders — fills settled at exchange level
                for closed_trade in engine.check_open_tp_fills():
                    if cb:
                        cb.record_trade(closed_trade.pnl_usd)
                # Cancel any pending entries whose window has expired.
                # Finding 4 (HIGH): use pos.window_end_ts instead of secs — secs may
                # already reflect the NEW window (~300s) after a market roll, causing
                # the secs<=0 guard to never fire for old PENDING_ENTRY positions.
                for pos_id, pos in list(engine.positions.items()):
                    from src.bot.live_engine_5m import State
                    if pos.state == State.PENDING_ENTRY and pos.window_end_ts < time.time():
                        engine.cancel_entry(pos_id)

            # ── Check exits ────────────────────────────────────────────────────
            active_states = ({"open"} if live else None)
            for pos_id, pos in list(engine.positions.items()):
                # Live: only act on OPEN positions (PENDING_ENTRY handled above)
                if live and pos.state != "open":
                    continue

                cur_up = market.up_price if market.condition_id == pos.condition_id else None
                if cur_up is None:
                    if live:
                        # Use pos.token_id — market.token_id_up is the NEW window's token (Finding 1.C)
                        _settled = engine.place_exit(pos_id, pos.token_id, "window_expired")
                        if cb and _settled:
                            cb.record_trade(_settled.pnl_usd)
                    else:
                        engine.close(pos_id, 0.01, "window_expired", price_60s_after_entry=0.0)
                    continue

                do_exit, reason = should_exit(
                    side=pos.side,
                    entry_price=pos.entry_price,
                    current_up_price=cur_up,
                    take_profit=pos.take_profit,
                    seconds_remaining=secs,
                    soft_exit_secs=soft_exit_secs,
                    hard_stop_max_remaining=hard_stop_max_remaining,
                )

                # Look up UP token price ~60s after entry from price_history
                p60_after = 0.0
                target_ts = pos.opened_at + 60.0
                for ph_ts, ph_px in price_history:
                    if ph_ts >= target_ts:
                        p60_after = ph_px
                        break

                STOP_REASONS = {"hard_stop", "trailing_stop_z2", "trailing_stop_z3",
                               "force_exit_time", "window_expired"}
                if do_exit:
                    if reason in STOP_REASONS:
                        window_stopped.add(pos.condition_id)
                    if live:
                        token_id = market.token_id_up if pos.side == "UP" else market.token_id_down
                        cur_side_price = cur_up if pos.side == "UP" else (1.0 - cur_up)
                        _settled = engine.place_exit(pos_id, token_id, reason,
                                                     price_60s_after_entry=p60_after,
                                                     market_price_at_exit=cur_side_price)
                        # FOK exits (hard_stop, force_exit, etc.) settle synchronously
                        # inside place_exit(). Capture the returned trade and record in CB
                        # so stop-loss exits don't bypass the daily loss limit.
                        if cb and _settled:
                            cb.record_trade(_settled.pnl_usd)
                    else:
                        exit_price = cur_up if pos.side == "UP" else (1.0 - cur_up)
                        trade = engine.close(pos_id, exit_price, reason, price_60s_after_entry=p60_after)
                        if cb and trade:
                            cb.record_trade(trade.pnl_usd)
                else:
                    cur_price = cur_up if pos.side == "UP" else (1.0 - cur_up)
                    pnl_pct = (cur_price - pos.entry_price) / pos.entry_price * 100
                    print(
                        f"  [HOLD] {pos_id} {pos.side} entry={pos.entry_price:.3f} "
                        f"now={cur_price:.3f} pnl={pnl_pct:+.1f}% | {secs:.0f}s left"
                    )

            # ── Skip tracking — record best opportunity during entry window ───
            if not live and strategy == "mean_reversion":
                cheaper_price = min(market.up_price, market.down_price)
                cheaper_side  = "UP" if market.up_price <= market.down_price else "DOWN"
                if secs >= mr_min_seconds and cheaper_price < best_opp_price:
                    best_opp_price = cheaper_price
                    best_opp_side  = cheaper_side

                # Entry window just closed — log skip if we never entered
                if secs < mr_min_seconds and not entry_window_logged:
                    entry_window_logged = True
                    if not engine.already_in(market.condition_id):
                        if best_opp_price > ENTRY_MAX:
                            skip_reason = "price_too_high"
                        elif best_opp_price < ENTRY_MIN:
                            skip_reason = "price_too_low"
                        elif not window_advisor_enter:
                            skip_reason = "advisor_skip"
                        elif best_opp_price <= ENTRY_MAX:
                            skip_reason = "btc_filter"
                        else:
                            skip_reason = "no_opportunity"
                        engine.log_skip(
                            condition_id=market.condition_id,
                            slug=market.slug,
                            asset=asset,
                            window_end_ts=market.window_end_ts,
                            skip_reason=skip_reason,
                            best_price_seen=best_opp_price,
                            best_side=best_opp_side,
                            entry_min=ENTRY_MIN,
                            entry_max=ENTRY_MAX,
                            btc_at_window_start=btc_at_window_start,
                            liquidity=market.liquidity,
                            advisor_reason=window_advisor_reason,
                        )

            # ── Check entries ──────────────────────────────────────────────────
            cb_open = (cb is None or cb.is_open())
            if cb and not cb_open and iteration % 30 == 0:
                print(cb.status())

            if not engine.already_in(market.condition_id) and cb_open:
                # Rolling asset rates from btc_history deque (works for any asset)
                btc_rate_per_min = btc_rate_10s = btc_rate_30s = 0.0
                if len(btc_history) >= 2:
                    latest_btc_ts, latest_btc_px = btc_history[-1]
                    for old_ts, old_px in btc_history:
                        elapsed_secs = latest_btc_ts - old_ts
                        if elapsed_secs >= 5  and btc_rate_per_min == 0.0:
                            btc_rate_per_min = (latest_btc_px - old_px) / (elapsed_secs / 60.0)
                        if elapsed_secs >= 10 and btc_rate_10s == 0.0:
                            btc_rate_10s = (latest_btc_px - old_px) / (elapsed_secs / 60.0)
                        if elapsed_secs >= 30 and btc_rate_30s == 0.0:
                            btc_rate_30s = (latest_btc_px - old_px) / (elapsed_secs / 60.0)
                        if btc_rate_per_min and btc_rate_10s and btc_rate_30s:
                            break

                btc_momentum_decel = 0.0
                if abs(btc_rate_30s) > 1.0:
                    btc_momentum_decel = round(btc_rate_10s / btc_rate_30s, 4)
                    print(f"  [DECEL] rate_10s={btc_rate_10s:.2f} rate_30s={btc_rate_30s:.2f} decel={btc_momentum_decel:.3f}")

                # Binance 60s return — monitor only, not yet a hard filter (p=0.081, n=22)
                btc_pct_60s = 0.0
                if len(btc_history) >= 2:
                    latest_btc_ts, latest_btc_px = btc_history[-1]
                    for old_ts, old_px in btc_history:
                        if (latest_btc_ts - old_ts) >= 60 and old_px > 0:
                            btc_pct_60s = round((latest_btc_px - old_px) / old_px * 100, 4)
                            break
                if asset == "BTC" and window == "5m" and btc_pct_60s != 0.0:
                    print(f"  [MONITOR] bnb_pct_60s={btc_pct_60s:+.4f}% ({'rising' if btc_pct_60s >= 0 else 'falling'})")

                # Cross-window direction from Chainlink
                cross_window_pct = 0.0
                if cl.prev_window_start_price > 0 and cl.window_start_price > 0:
                    cross_window_pct = round(
                        (cl.window_start_price - cl.prev_window_start_price)
                        / cl.prev_window_start_price * 100, 4
                    )

                if strategy == "momentum":
                    # ── Momentum: enter at window open, bet continuation of prev window ──
                    do_enter, side, entry_price = should_enter_momentum(
                        market,
                        cross_window_pct=cross_window_pct,
                    )
                    if do_enter:
                        btc_at_entry = btc_history[-1][1] if btc_history else 0.0
                        xw_str = f"{cross_window_pct:+.3f}%"
                        print(f"  [MOMENTUM] {side} @ {entry_price:.3f} | prev_move={xw_str}")
                        engine.open(
                            condition_id=market.condition_id,
                            slug=market.slug,
                            asset=asset,
                            side=side,
                            entry_price=entry_price,
                            take_profit=take_profit_price(entry_price),
                            window_end_ts=market.window_end_ts,
                            window=window,
                            strategy=strategy,
                            btc_price_at_window_start=btc_at_window_start,
                            btc_price_at_entry=btc_at_entry,
                            up_price_at_window_start=up_price_at_window_start,
                            liquidity=market.liquidity,
                            cross_window_pct=cross_window_pct,
                        )

                else:
                    # ── Mean reversion: buy cheap side in entry window ─────────────────
                    window_duration  = 900 if window == "15m" else 300
                    secs_into_window = round(max(0.0, time.time() - (market.window_end_ts - window_duration)), 1)
                    clob_trades_60s  = clob_feed.get_recent_trade_count(lookback_secs=60)

                    do_enter, side, entry_price = should_enter(
                        market,
                        btc_rate_per_min=btc_rate_per_min,
                        cl_pct_change=cl.pct_change if cl.price > 0 else 0.0,
                        min_seconds=mr_min_seconds,
                        spread=book_spread,
                        cross_window_pct=cross_window_pct,
                        secs_into_window=secs_into_window,
                        clob_trades_60s=clob_trades_60s,
                    )

                    if do_enter:
                        now_ts = time.time()
                        p_60s = p_30s = cheap_20s_ago = 0.0
                        for ts, px in price_history:
                            age = now_ts - ts
                            if 55 <= age <= 65:
                                p_60s = px
                            elif 25 <= age <= 35:
                                p_30s = px
                            elif 18 <= age <= 24 and cheap_20s_ago == 0.0:
                                cheap_20s_ago = px if side == "UP" else (1.0 - px)

                        cheap_side_velocity = 0.0
                        if cheap_20s_ago > 0:
                            cheap_side_velocity = round((entry_price - cheap_20s_ago) / 20.0, 6)

                        if asset == "ETH" and cheap_side_velocity < -0.006:
                            print(f"  [MONITOR] ETH entry with cheap_side_velocity={cheap_side_velocity:+.4f} (below -0.006 threshold)")

                        # Finding 6 (MEDIUM): use taker price for both live and paper.
                        # The previous live midpoint (maker limit) frequently timed out
                        # without filling in fast markets — causing live to miss entries
                        # that paper caught at book_ask. Taker pricing ensures consistent
                        # fill rates at the cost of a small fee difference.
                        #
                        # v1.9: Add 1¢ slippage buffer above the WS best-ask so the GTC
                        # order aggressively crosses the spread even when the WS price is
                        # slightly stale (e.g. 0.380 WS ask but real ask is 0.390). Without
                        # slippage the GTC order sits as a resting maker, times out after
                        # 45s, and is cancelled — the "entry placed but disappeared" bug.
                        # Cap at 0.42 to stay inside the positive-EV gate.
                        ENTRY_SLIPPAGE = 0.01
                        if ws_ok and book_ask > 0 and book_bid > 0:
                            if side == "UP":
                                entry_price = min(round(book_ask + ENTRY_SLIPPAGE, 3), 0.42)
                            else:
                                entry_price = min(round(1.0 - book_bid + ENTRY_SLIPPAGE, 3), 0.42)

                        # ── Dynamic TP + negative-EV gate ────────────────────
                        tp = take_profit_price(entry_price)
                        if tp is None:
                            print(f"  [TP] Skip — entry {entry_price:.3f} > 0.42 (negative EV)")
                            continue

                        # ── GBM collapse gate ─────────────────────────────────
                        from src.bot.collapse_model import collapse_prob, should_skip, COLLAPSE_THRESHOLD
                        btc_at_entry   = btc_history[-1][1] if btc_history else 0.0
                        btc_pct_chg_entry = 0.0
                        if btc_at_window_start > 0 and btc_at_entry > 0:
                            btc_pct_chg_entry = (btc_at_entry - btc_at_window_start) / btc_at_window_start * 100

                        c_prob = collapse_prob(
                            entry_price=entry_price,
                            take_profit=tp,
                            btc_pct_change_at_entry=btc_pct_chg_entry,
                            secs_remaining=market.seconds_remaining,
                            liquidity=market.liquidity,
                            price_60s=p_60s,
                            price_30s=p_30s,
                            price_velocity=cheap_side_velocity,
                            side=side,
                            up_price_at_window_start=up_price_at_window_start,
                        )
                        if should_skip(c_prob):
                            print(f"  [GBM] Skip — collapse_prob={c_prob:.3f} >= {COLLAPSE_THRESHOLD}")
                            continue

                        # ── BTC DOWN regime filter (Cowork 2026-04-18) ───────
                        # BTC DOWN bets in a bullish April regime: 50% WR / −$0.93 EV
                        # vs BTC UP: 59% WR / +$1.22 EV (58 modern trades each).
                        # Only take BTC DOWN when BTC has bounced up from window start —
                        # gives the DOWN bet an actual mean-reversion thesis (fading
                        # a bounce). Flat or falling BTC DOWN is a regime bet, not a fade.
                        if asset == "BTC" and side == "DOWN" and btc_pct_chg_entry <= 0:
                            print(f"  [REGIME] Skip BTC DOWN — BTC not bouncing (chg={btc_pct_chg_entry:+.4f}%)")
                            continue

                        # ── Realized volatility filter (Cowork 2026-04-18) ───
                        # High-vol regimes (top quintile Binance spot) → 33% HS rate,
                        # 50% WR, −$0.48 EV vs 24% HS rate / 61% WR / +$1.87 EV baseline.
                        # Threshold: log-return std per 2s bar > 0.0029 (σ ≈ 0.29%).
                        # Configurable via RV_THRESHOLD in .env.
                        RV_THRESHOLD = float(os.environ.get("RV_THRESHOLD", "0.0029"))
                        if window == "15m" and len(btc_history) >= 10:
                            _now = time.time()
                            _rv_prices = [px for ts, px in btc_history if _now - ts <= 900]
                            if len(_rv_prices) >= 5:
                                _log_rets = [
                                    math.log(_rv_prices[i+1] / _rv_prices[i])
                                    for i in range(len(_rv_prices) - 1)
                                    if _rv_prices[i] > 0 and _rv_prices[i+1] > 0
                                ]
                                if _log_rets:
                                    _mean = sum(_log_rets) / len(_log_rets)
                                    _std  = (sum((r - _mean)**2 for r in _log_rets) / len(_log_rets)) ** 0.5
                                    if _std > RV_THRESHOLD:
                                        print(f"  [VOL] Skip — realized vol {_std:.4f} > {RV_THRESHOLD} (high-vol regime)")
                                        continue

                        # ── CLOB midpoint trend filter ────────────────────────
                        # Cowork: strong upward trend → 29.4% WR (BTC), downward → 13.8% WR
                        # NOT predictive for ETH (confusing signal); skip for ETH.
                        # 0.0 = no history yet → pass through.
                        clob_trend = clob_feed.get_midpoint_trend(lookback_secs=60)
                        # Cowork 2026-04-18: loosened from 0.10 → 0.15 for BTC/SOL.
                        # The −0.30..−0.15 CLOB bucket (n=23) has 65% WR / +$2.15 EV —
                        # it was being blocked when it's a positive-EV region.
                        CLOB_TREND_THRESHOLD = 0.15
                        if clob_trend != 0.0 and asset != "ETH":
                            if side == "UP" and clob_trend < -CLOB_TREND_THRESHOLD:
                                print(f"  [CLOB] Skip UP — midpoint trending down {clob_trend:+.3f}")
                                continue
                            if side == "DOWN" and clob_trend > CLOB_TREND_THRESHOLD:
                                print(f"  [CLOB] Skip DOWN — midpoint trending up {clob_trend:+.3f}")
                                continue

                        decel_str = f"{btc_momentum_decel:+.2f}" if btc_momentum_decel else "n/a"
                        vel_str   = f"{cheap_side_velocity:+.4f}" if cheap_side_velocity else "n/a"
                        xw_str    = f"{cross_window_pct:+.3f}%" if cross_window_pct else "n/a"
                        spd_str   = f"{book_spread:.4f}" if book_spread > 0 else "n/a"
                        trend_str = f"{clob_trend:+.3f}" if clob_trend != 0.0 else "n/a"
                        print(f"  [SIGNAL] decel={decel_str} vel={vel_str} cross={xw_str} spread={spd_str} collapse={c_prob:.3f} tp={tp:.2f} trend={trend_str}")

                        if live:
                            token_id = market.token_id_up if side == "UP" else market.token_id_down
                            engine.place_entry(
                                condition_id=market.condition_id,
                                slug=market.slug,
                                asset=asset,
                                side=side,
                                token_id=token_id,
                                entry_price=entry_price,
                                take_profit=tp,
                                window_end_ts=market.window_end_ts,
                                btc_price_at_window_start=btc_at_window_start,
                                btc_price_at_entry=btc_at_entry,
                                up_price_at_window_start=up_price_at_window_start,
                                liquidity=market.liquidity,
                                price_60s_before_entry=p_60s,
                                price_30s_before_entry=p_30s,
                            )
                        else:
                            engine.open(
                                condition_id=market.condition_id,
                                slug=market.slug,
                                asset=asset,
                                side=side,
                                entry_price=entry_price,
                                take_profit=tp,
                                window_end_ts=market.window_end_ts,
                                window=window,
                                strategy=strategy,
                                btc_price_at_window_start=btc_at_window_start,
                                btc_price_at_entry=btc_at_entry,
                                up_price_at_window_start=up_price_at_window_start,
                                liquidity=market.liquidity,
                                price_60s_before_entry=p_60s,
                                price_30s_before_entry=p_30s,
                                btc_momentum_decel=btc_momentum_decel,
                                cheap_side_velocity=cheap_side_velocity,
                                cross_window_pct=cross_window_pct,
                                spread_at_entry=book_spread,
                                bid_depth_at_entry=book_bid_depth,
                                ask_depth_at_entry=book_ask_depth,
                                clob_midpoint_trend_60s=clob_trend,
                            )

            # ── Summary every ~60s (time-based, stable across poll intervals) ──
            if time.time() - last_summary_ts >= 60:
                last_summary_ts = time.time()
                engine.save_summary()
                s = engine.summary()
                if live:
                    wallet = s.get("wallet_usdc", 0.0)
                    print(
                        f"[SUMMARY] wallet=${wallet:.2f} | open={s['open_positions']} | "
                        f"closed={s['closed_trades']} ({s['wins']}W/{s['losses']}L) | "
                        f"pnl=${s['total_pnl']:+.2f} | win_rate={s['win_rate']:.0f}%"
                    )
                else:
                    print(
                        f"[SUMMARY] equity=${s['equity']:.2f} | open={s['open_positions']} | "
                        f"closed={s['closed_trades']} ({s['wins']}W/{s['losses']}L) | "
                        f"pnl=${s['total_pnl']:+.2f} | win_rate={s['win_rate']:.0f}%"
                    )

        except KeyboardInterrupt:
            flush_all()
            raise
        except Exception as exc:
            print(f"[{now_str}] ERROR: {exc}")

        try:
            time.sleep(POLL_INTERVAL)
        except BaseException:
            pass


# ── Multi-market parallel loop ────────────────────────────────────────────────

def run_multi_loop(configs: list[tuple[str, str, str]], live: bool = False) -> None:
    """
    Run multiple market loops in parallel daemon threads.
    configs: list of (asset, window, strategy) e.g.
      [("BTC","5m","mean_reversion"), ("SOL","15m","mean_reversion"), ("BTC","5m","momentum")]
    """
    # Shared circuit breaker — one instance for all live threads so the daily loss
    # limit is global across markets, not per-market. Thread-safe (Finding 2.B).
    shared_cb = None
    if live:
        from src.bot.circuit_breaker import CircuitBreaker
        shared_cb = CircuitBreaker()
        print(f"[MULTI] {shared_cb.status()}")

    threads = []
    for asset, window, strategy in configs:
        name = f"{asset}-{window}-{strategy}"
        t = threading.Thread(
            target=run_5m_loop,
            kwargs={"asset": asset, "live": live, "window": window, "strategy": strategy, "cb": shared_cb},
            name=name,
            daemon=True,
        )
        t.start()
        threads.append(t)
        print(f"[MULTI] Started thread: {name}")
        time.sleep(0.5)  # stagger starts to avoid simultaneous API bursts

    print(f"[MULTI] {len(threads)} threads running")
    try:
        while any(t.is_alive() for t in threads):
            time.sleep(5)
    except KeyboardInterrupt:
        print("[MULTI] Shutting down...")


# ── Dashboard ─────────────────────────────────────────────────────────────────

def run_dashboard() -> None:
    from src.dashboard.app import create_app
    app = create_app()
    print("[DASHBOARD] Starting on http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)


# ── Status ────────────────────────────────────────────────────────────────────

def run_status() -> None:
    import httpx
    from src.bot.paper_engine import _compute_summary, _load_positions

    # BTC price
    try:
        r = httpx.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=5)
        btc = float(r.json()["price"])
        print(f"BTC price: ${btc:,.2f}")
    except Exception as exc:
        print(f"BTC price: error ({exc})")

    # Summary
    summary = _compute_summary()
    positions = _load_positions()
    print(f"Equity:   ${summary['equity']:.2f}")
    print(f"P&L:      ${summary['total_pnl']:+.2f}")
    print(f"Trades:   {summary['closed_trades']} closed ({summary['wins']}W / {summary['losses']}L)")
    print(f"Win rate: {summary['win_rate']:.0f}%")
    print(f"Open:     {len(positions)} positions")
    for p in positions.values():
        print(f"  {p.position_id} | {p.side} ${p.strike:,} @ {p.entry_price:.3f} | {p.reason[:50]}")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"

    if cmd == "btc-5m-loop":
        _setup_logging()
        run_5m_loop("BTC")
    elif cmd == "btc-5m-live":
        _setup_logging()
        run_5m_loop("BTC", live=True)
    elif cmd == "multi-live":
        # Live multi-market loop: BTC/ETH/SOL 15m + optional overrides
        # Usage: python main.py multi-live [ASSET:WINDOW:STRATEGY ...]
        _raw = sys.argv[2:]
        if _raw:
            _configs = []
            for _arg in _raw:
                _parts = _arg.split(":")
                if len(_parts) == 3:
                    _configs.append((_parts[0].upper(), _parts[1], _parts[2]))
                else:
                    print(f"Bad config '{_arg}' — expected ASSET:WINDOW:STRATEGY")
                    sys.exit(1)
        else:
            _configs = [
                ("BTC", "15m", "mean_reversion"),
                ("ETH", "15m", "mean_reversion"),
                ("SOL", "15m", "mean_reversion"),
            ]
        _setup_logging()
        run_multi_loop(_configs, live=True)
    elif cmd == "multi-loop":
        # Parse ASSET:WINDOW:STRATEGY args, default if none given
        _raw = sys.argv[2:]
        if _raw:
            _configs = []
            for _arg in _raw:
                _parts = _arg.split(":")
                if len(_parts) == 3:
                    _configs.append((_parts[0].upper(), _parts[1], _parts[2]))
                else:
                    print(f"Bad config '{_arg}' — expected ASSET:WINDOW:STRATEGY")
                    sys.exit(1)
        else:
            # Default: BTC 5m mean-reversion + BTC 5m momentum + 15m markets
            _configs = [
                # BTC 5m mean_reversion removed: 55 trades, 16% WR, -$217 — negative EV
                # BTC 5m momentum removed: 102 trades, 31% WR, -$168 (MOMENTUM_ENABLED=False anyway)
                ("BTC", "15m", "mean_reversion"),
                ("ETH", "15m", "mean_reversion"),
                ("SOL", "15m", "mean_reversion"),
            ]
        _setup_logging()
        run_multi_loop(_configs)
    elif cmd == "paper-loop":
        _setup_logging()
        run_loop()
    elif cmd == "dashboard":
        run_dashboard()
    elif cmd == "status":
        run_status()
    elif cmd == "setup-clob-auth":
        from dotenv import load_dotenv
        load_dotenv()
        from src.bot.clob_auth import setup_credentials
        setup_credentials()
    else:
        print(__doc__)
        sys.exit(0)
