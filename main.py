"""
Polymarket Paper Trading Bot
=============================
Commands:
  python main.py btc-5m-loop  — 5-minute BTC Up/Down bot (primary)
  python main.py paper-loop   — daily BTC strike market bot (legacy)
  python main.py dashboard    — web dashboard
  python main.py status       — print current state and exit
"""
from __future__ import annotations

import io
import json
import os
import pathlib
import sys
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

def _fetch_btc_price() -> float:
    """Quick Binance spot price — used for trade context capture."""
    import httpx as _httpx
    try:
        r = _httpx.get(
            "https://api.binance.com/api/v3/ticker/price",
            params={"symbol": "BTCUSDT"},
            timeout=5,
        )
        return float(r.json()["price"])
    except Exception:
        return 0.0


def run_5m_loop(asset: str = "BTC", live: bool = False) -> None:
    import collections
    from src.bot.market_5m import fetch_market, fetch_live_prices, FORCE_EXIT, ENTRY_MAX, BTC_SKIP_RATE
    from src.bot.signal_5m import should_enter, should_exit, take_profit_price
    from src.bot import chainlink_feed

    POLL_INTERVAL = 2   # seconds — match Chainlink poll rate

    mode_str = "LIVE" if live else "PAPER"
    print(f"\n{'='*60}")
    print(f"5-Minute Up/Down Bot [{mode_str}] — {asset} — {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Poll every {POLL_INTERVAL}s | Limit buy @{ENTRY_MAX:.0%} in first 90s only | TP=50¢ Force=90¢ | BTC skip >${BTC_SKIP_RATE:.0f}/min")
    print(f"{'='*60}\n")

    if live:
        from src.bot.live_engine_5m import LiveEngine5m
        from src.bot.circuit_breaker import CircuitBreaker
        engine = LiveEngine5m()
        cb = CircuitBreaker(max_daily_loss_usd=50.0)
        print(cb.status())
    else:
        from src.bot.engine_5m import Engine5m
        engine = Engine5m()
        cb = None

    # Start Chainlink feed — actual window start prices, not stale API data
    chainlink_feed.start()
    print("[MAIN] Waiting for Chainlink price feed...")
    cl = chainlink_feed.wait_for_price(timeout=15)
    if cl:
        print(f"[MAIN] Chainlink BTC: ${cl.price:,.2f}")
    else:
        print("[MAIN] Chainlink unavailable — continuing without window-start tracking")

    iteration = 0
    market = None   # cached — only refetched when window expires

    # ── Context tracking for ML data capture ──────────────────────────────────
    # Rolling price history for the current window: deque of (timestamp, up_price)
    price_history: collections.deque = collections.deque(maxlen=300)
    # Continuous BTC price history — NOT reset on window change (independent of windows)
    # maxlen=150 @ 2s poll = 5 minutes of continuous BTC price data
    btc_history: collections.deque = collections.deque(maxlen=150)
    btc_at_window_start: float = 0.0   # Binance BTC/USD when window opened
    up_price_at_window_start: float = 0.5  # first CLOB midpoint reading for window
    # Per-window stop guard: block re-entry after a stop loss in the same window.
    # ENTRY_MIN=0.25 prevents the cascade at sub-25¢ prices, but after a hard_stop
    # at ~20¢ the price could recover to 30¢ and trigger another bad entry.
    # Does NOT block re-entry after take_profit — the double-entry pattern
    # (first trade wins quickly → re-enter the other side) is a real source of profit.
    window_stopped: set = set()  # condition_ids that hit a stop this window

    while True:
        iteration += 1
        now_str = time.strftime("%H:%M:%S")

        try:
            # Refetch market structure from Gamma only on startup or window change.
            # outcomePrices from Gamma is stale — only token IDs and slug are needed here.
            if market is None or market.is_expired():
                new_market = fetch_market(asset)
                if new_market is None:
                    print(f"[{now_str}] No active market found — retrying...")
                    time.sleep(POLL_INTERVAL)
                    continue
                market = new_market

                # Reset per-window context
                price_history.clear()
                window_stopped.clear()
                btc_at_window_start = _fetch_btc_price()
                up_price_at_window_start = market.up_price  # Gamma initial price (≈0.5)

                cl = chainlink_feed.get_state()
                secs = market.seconds_remaining
                cl_str = (
                    f"CL=${cl.price:,.2f} start=${cl.window_start_price:,.2f} Δ{cl.pct_change:+.3f}%"
                    if cl.price > 0 else "CL=unavailable"
                )
                btc_str = f" | BTC=${btc_at_window_start:,.2f}" if btc_at_window_start else ""
                print(f"\n[NEW WINDOW] {market.slug} | {secs:.0f}s | liq=${market.liquidity:,.0f} | {cl_str}{btc_str}")

            # Live prices from CLOB midpoint — updates every 2s, reflects real order book.
            # Gamma's outcomePrices does NOT update mid-window and will show stale 0.50/0.50.
            market.up_price, market.down_price, clob_ok = fetch_live_prices(market)
            cl = chainlink_feed.get_state()
            secs = market.seconds_remaining

            # Record price history for this window
            price_history.append((time.time(), market.up_price))

            # Continuous BTC price — every poll, independent of windows
            btc_now = _fetch_btc_price()
            if btc_now > 0:
                btc_history.append((time.time(), btc_now))

            # Update window-start price with first good CLOB reading
            if clob_ok and up_price_at_window_start == 0.5 and market.up_price != 0.5:
                up_price_at_window_start = market.up_price

            src = "clob" if clob_ok else "CACHED"
            cl_info = f"CL={cl.pct_change:+.3f}%" if cl.price > 0 else ""
            print(
                f"[{now_str}] {asset} UP={market.up_price:.3f} DOWN={market.down_price:.3f} "
                f"[{src}] | {secs:.0f}s left {cl_info}"
            )

            # ── Advance live order state machine ───────────────────────────────
            if live:
                engine.check_pending_entries()
                for closed_trade in engine.check_pending_exits():
                    if cb:
                        cb.record_trade(closed_trade.pnl_usd)
                # Cancel any pending entries whose window has expired
                for pos_id, pos in list(engine.positions.items()):
                    from src.bot.live_engine_5m import State
                    if pos.state == State.PENDING_ENTRY and secs <= 0:
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
                        engine.place_exit(pos_id, market.token_id_up, "window_expired")
                    else:
                        engine.close(pos_id, 0.01, "window_expired", price_60s_after_entry=0.0)
                    continue

                do_exit, reason = should_exit(
                    side=pos.side,
                    entry_price=pos.entry_price,
                    current_up_price=cur_up,
                    take_profit=pos.take_profit,
                    seconds_remaining=secs,
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
                        engine.place_exit(pos_id, token_id, reason,
                                          price_60s_after_entry=p60_after)
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

            # ── Check entries ──────────────────────────────────────────────────
            cb_open = (cb is None or cb.is_open())
            if cb and not cb_open and iteration % 30 == 0:
                print(cb.status())
            if not engine.already_in(market.condition_id) and market.condition_id not in window_stopped and cb_open:
                # Rolling BTC rate $/min — use btc_history deque (updated every 2s poll)
                btc_rate_per_min = 0.0
                if len(btc_history) >= 2:
                    latest_btc_ts, latest_btc_px = btc_history[-1]
                    for old_ts, old_px in btc_history:
                        elapsed_secs = latest_btc_ts - old_ts
                        if elapsed_secs >= 5:
                            btc_rate_per_min = (latest_btc_px - old_px) / (elapsed_secs / 60.0)
                            break

                do_enter, side, entry_price = should_enter(market, btc_rate_per_min=btc_rate_per_min)
                if do_enter:
                    now_ts = time.time()

                    # Look up historical prices from deque for velocity/trajectory
                    p_60s = p_30s = 0.0
                    for ts, px in price_history:
                        age = now_ts - ts
                        if 55 <= age <= 65:
                            p_60s = px
                        elif 25 <= age <= 35:
                            p_30s = px

                    btc_at_entry = btc_history[-1][1] if btc_history else 0.0

                    if live:
                        token_id = market.token_id_up if side == "UP" else market.token_id_down
                        engine.place_entry(
                            condition_id=market.condition_id,
                            slug=market.slug,
                            asset=asset,
                            side=side,
                            token_id=token_id,
                            entry_price=entry_price,
                            take_profit=take_profit_price(entry_price),
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
                            take_profit=take_profit_price(entry_price),
                            window_end_ts=market.window_end_ts,
                            btc_price_at_window_start=btc_at_window_start,
                            btc_price_at_entry=btc_at_entry,
                            up_price_at_window_start=up_price_at_window_start,
                            liquidity=market.liquidity,
                            price_60s_before_entry=p_60s,
                            price_30s_before_entry=p_30s,
                        )

            # ── Summary every 30 polls (≈ 1 min at 2s interval) ───────────────
            if iteration % 30 == 0:
                engine.save_summary()
                s = engine.summary()
                print(
                    f"[SUMMARY] equity=${s['equity']:.2f} | open={s['open_positions']} | "
                    f"closed={s['closed_trades']} ({s['wins']}W/{s['losses']}L) | "
                    f"pnl=${s['total_pnl']:+.2f} | win_rate={s['win_rate']:.0f}%"
                )

        except KeyboardInterrupt:
            raise
        except Exception as exc:
            print(f"[{now_str}] ERROR: {exc}")

        try:
            time.sleep(POLL_INTERVAL)
        except BaseException:
            pass


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
