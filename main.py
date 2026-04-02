"""
BTC Strike Market Paper Trading Bot
====================================
Trades Polymarket "Bitcoin above $X on [date]?" markets based on live BTC
price momentum from Binance WebSocket.

Commands:
  python main.py paper-loop   — run the trading bot
  python main.py dashboard    — run the web dashboard
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

def _setup_logging() -> None:
    """Redirect stdout/stderr to bot.log (fully unbuffered write-through)."""
    # io.FileIO is a raw binary stream with NO intermediate buffer, so every
    # write() reaches the OS immediately without an explicit flush() call.
    # write_through=True then ensures TextIOWrapper also skips its own buffer.
    log = io.FileIO(LOG_FILE, mode="ab")  # noqa: WPS515
    wrapped = io.TextIOWrapper(log, encoding="utf-8", write_through=True)
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

    if cmd == "paper-loop":
        _setup_logging()
        run_loop()
    elif cmd == "dashboard":
        run_dashboard()
    elif cmd == "status":
        run_status()
    else:
        print(__doc__)
        sys.exit(0)
