# Patch History

---

## v1.6 — 2026-04-15
**BTC_SKIP_RATE configurable via .env; default raised from $20 → $50/min**

**Problem:** Paper bot and live bot are separate processes with independent BTC price
histories. At the moment of decision they computed slightly different `btc_rate_per_min`
values — the paper process saw ~-$15/min (passed), the live process saw -$30.6/min
(blocked by the -$20 threshold). The trade went on to win +50%, confirming the filter
gave a false block.

Root causes:
1. Two separate Python processes each maintain their own `btc_history` list, so the
   rate calculation samples slightly different time windows — one can be above the
   threshold while the other is below it.
2. `BTC_SKIP_RATE = 20.0` was too tight. At $74k BTC that's only 0.027%/min — normal
   short-term jitter can cross the line.

**Fix:** `BTC_SKIP_RATE` now reads from `.env` (default 50.0 $/min). Set in `.env`:
```
BTC_SKIP_RATE=50.0
```

**Files:** `src/bot/market_5m.py`, `.env`

---

## v1.5 — 2026-04-15
**Cross-window filter configurable via .env**

**Problem:** `CROSS_WINDOW_MIN` was hardcoded to `-0.06%`. During a slow downtrend,
every window was showing a cross-window move of `-0.07%` to `-0.14%` — just past the
floor — causing the bot to skip every single entry opportunity.

**Fix:** `CROSS_WINDOW_MIN` and `CROSS_WINDOW_MAX` now read from `.env` at startup.
Default changed from `-0.06` → `-0.15` so the current market conditions pass through.
To tighten or loosen the filter without a code deploy, set in `.env`:
```
CROSS_WINDOW_MIN=-0.15
CROSS_WINDOW_MAX=0.02
```

**Files:** `src/bot/market_5m.py`, `.env`

Each entry covers what changed, why, and what file(s) were touched.
The dashboard header always shows the current patch (`src/bot/version.py`).

---

## v1.4 — 2026-04-15
**Immediate TP order placement on fill**

**Problem:** After an entry filled, the take-profit was only acted on when the poll
loop observed the price crossing the TP threshold. A position could reach—and
exceed—the target with no action taken (incident: BTC UP 41c → 85c, TP at 60c
never fired after a restart+window-roll cycle).

**Fix:**
- `_place_tp_order()`: immediately after a BUY fill is confirmed, post a standing
  GTC SELL at the take-profit price on the Polymarket order book. The exchange
  executes this autonomously the moment a buyer matches — no polling latency.
- Balance verification: Polymarket rejects a SELL order if the fill hasn't settled
  in the wallet yet. `_place_tp_order` calls `get_balance_allowance` first and
  defers if the balance is still zero.
- `check_open_tp_fills()`: polls `tp_order_id` every cycle. Also retries deferred
  TP orders (balance may now be confirmed). Called in the main poll loop.
- Aggressive stops: cancel `tp_order_id` before firing FOK to avoid double-selling.
- `place_exit("take_profit")`: early-returns if TP is already on the book.
- Startup repair: OPEN positions with no `tp_order_id` get one placed immediately.
- `tp_order_id` persisted to CSV — survives restarts.

**Files:** `src/bot/live_engine_5m.py`, `main.py`

---

## v1.3 — 2026-04-15
**Exchange balance reconciliation + circuit breaker tightened**

**Problem:** After a restart+window-roll cycle, real share balances on Polymarket
could exist with no record in the positions CSV — the bot would never manage them.
Circuit breaker daily loss limit was $50 (too high for a $5/position bot).

**Fix:**
- `check_exchange_balances()`: on startup, queries Polymarket CLOB for actual
  conditional token holdings for the current window and logs a CRITICAL warning
  for any untracked balance.
- `LIVE_MAX_DAILY_LOSS_USD` reduced from $50 → $15 in `.env`.
- `CircuitBreaker.__init__` warns if limit > $40.

**Files:** `src/bot/live_engine_5m.py`, `src/bot/circuit_breaker.py`, `.env`

---

## v1.2 — 2026-04-15
**Speed: non-blocking Binance feed + 1s poll interval**

**Problem:** Binance price fetch was a synchronous HTTP call blocking the hot poll
loop for ~100-300ms every cycle. Poll interval was hardcoded at 2s.

**Fix:**
- `BinanceFeed` background thread: fetches Binance price every 2s, caches result.
  Main loop reads the cached value (non-blocking).
- `POLL_INTERVAL` reduced to 1s for live mode (configurable via
  `LIVE_POLL_INTERVAL_SECONDS` in `.env`).
- Summary output switched from iteration-count-based to time-based (every 60s).

**Files:** `main.py`

---

## v1.1 — 2026-04-15
**Audit findings 1-9: critical safety fixes**

Nine findings from a full engine audit, prioritised CRITICAL → LOW.

| # | Priority | Fix |
|---|----------|-----|
| 1 | CRITICAL | `cancel_entry()` → post-cancel `get_order()` check; if filled→transition OPEN instead of discarding shares |
| 2 | CRITICAL | `__pending__` orphan cleanup: remove pre-saved positions where API call never returned (>30s) |
| 3 | HIGH     | Pre-save as `PENDING_EXIT` before `post_order()` in `place_exit()`; revert on failure |
| 4 | HIGH     | Window-expiry check uses `pos.window_end_ts` not stale `secs` variable |
| 5 | HIGH     | Circuit breaker added; daily loss limit from `.env` |
| 6 | MEDIUM   | Live entry uses taker price (book_ask) same as paper engine |
| 7 | MEDIUM   | Startup logs OPEN/PENDING_EXIT counts with cross-check prompt |
| 8 | MEDIUM   | Auth-failed message clarified |
| 9 | LOW      | Exit retry counter logged after 3+ failed rescue attempts |

**Files:** `src/bot/live_engine_5m.py`, `main.py`, `src/bot/circuit_breaker.py`

---

## v1.0 — baseline
Initial live engine deployment. GTC limit entries, FOK aggressive exits, per-market
CSV state, paper-parity signal logic.
