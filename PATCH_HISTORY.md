# Patch History

---

## v1.18 — 2026-04-18
**Migrate to Polymarket CLOB V2 SDK (deadline: April 28 cutover)**

Polymarket is upgrading its CLOB infrastructure on April 28, 2026 (~11:00 UTC). V1 SDK stops functioning after cutover. ~1 hour downtime; all open orders cancelled.

### Changes
- `pyproject.toml`: `py-clob-client>=0.18.0` → `py-clob-client-v2==1.0.0`
- All import paths updated: `py_clob_client.*` → `py_clob_client_v2.*`
  - `src/bot/clob_auth.py`: `from py_clob_client.client import ClobClient` etc → `from py_clob_client_v2 import ...`
  - `src/bot/live_engine_5m.py`: top-level and 4 inline `BalanceAllowanceParams/AssetType` imports
  - `src/dashboard/app.py`: inline balance import
  - `test_order.py`: OrderArgs / BUY imports

### Verified unchanged (no code changes needed beyond imports)
- `ClobClient.__init__` signature: identical (`host`, `chain_id`, `key`, `funder`, etc — no dict-based change)
- `OrderArgs`: `token_id`, `price`, `size`, `side`, `expiration` — same; `fee_rate_bps`/`nonce`/`taker` removed but bot never set these
- `OrderType.GTC` / `OrderType.FOK`: same string constants
- `BUY` / `SELL` from `order_builder.constants`: still `"BUY"` / `"SELL"` strings
- `AssetType.COLLATERAL` / `AssetType.CONDITIONAL`: unchanged
- `POLYGON = 137`: unchanged

### pUSD collateral
Polymarket is migrating from USDC.e to pUSD. Users who use the Polymarket web UI get auto-wrapped. API-only traders must call `wrap()` on the Collateral Onramp contract. Confirm on https://polymarket.com that wallet shows pUSD balance before April 28.

### Deploy steps
1. `git pull` on laptop
2. `uv sync` (installs py-clob-client-v2, removes old py-clob-client + py-builder-signing-sdk)
3. Restart LIVE + PAPER bots

---

## v1.17 — 2026-04-18
**Fix circuit breaker not recording stop-loss exits**

### Root cause
`place_exit()` in `live_engine_5m.py` returned `None` in all cases. For FOK exits
(hard_stop_floor, soft_exit_stalled, force_exit_time, window_expired), the position
was settled synchronously *inside* `place_exit()` via `_settle_exit()` — trade written
to CSV, position removed — but the returned `ClosedLiveTrade5m` was discarded.

`main.py` only called `cb.record_trade()` in the `for closed_trade in engine.check_pending_exits()`
and `for closed_trade in engine.check_open_tp_fills()` loops. Take-profit exits use GTC
orders polled by `check_open_tp_fills()` so they were correctly recorded. All FOK exits
bypassed CB entirely.

Net effect: CB tracked every winning trade but zero stop-loss losses. After today's
run, CB showed +$43.28 (10 take-profit wins recorded) while actual today's PnL was
-$36.02 (13 unrecorded FOK losses totalling -$79.30).

### Fix
- `place_exit()` signature changed to `-> ClosedLiveTrade5m | None`
- All four inline `_settle_exit()` call sites inside `place_exit()` now `return` the result:
  - wallet empty path (line ~895)
  - below MIN_SHARES path (line ~905)
  - orderbook-gone / market_resolved path (line ~943)
  - FOK fill inline settle (line ~1021)
- Added `return None` at end of `place_exit()` for the GTC/take-profit path (position
  transitions to PENDING_EXIT, settled async via `check_pending_exits()`)
- `main.py`: both `engine.place_exit()` call sites now capture the return value and
  call `cb.record_trade(_settled.pnl_usd)` if not None

### Files changed
- `src/bot/live_engine_5m.py` — `place_exit()` return type + 4 `return self._settle_exit(...)` + `return None`
- `main.py` — 2 call sites: `_settled = engine.place_exit(...)` + CB record

---

## v1.16 — 2026-04-18
**Cowork 2026-04-18 filter set — 6 targeted changes from analysis of 395 paper trades**

### 🟢 1. Wire `hard_stop_max_remaining` for 15m windows (bug fix)
The 15m hard-stop gate was documented but never implemented. `hard_stop_max_remaining`
defaulted to `float("inf")`, so hard-stops were firing at median 45% through the
window instead of only in the final 4 minutes as intended. Changed to 240s for
15m windows. This delays ~67 hard-stop exits, giving positions more recovery time;
they become `soft_exit_stalled` instead if the price hasn't recovered.

### 🟢 2. Tighten `CROSS_WINDOW_MAX` 0.15 → 0.10
The +0.10..+0.15 cross-window bucket had 40% WR / −$2.60 EV (10 modern trades) —
the only band inside the current filter that consistently loses money. Changed both
the `.env` default in `market_5m.py` and the `.env` on the laptop.

### 🟢 3. BTC DOWN regime filter
BTC DOWN entries in bullish April regime: 50% WR / −$0.93 EV (58 modern trades)
vs BTC UP: 59% WR / +$1.22 EV. New filter: skip BTC DOWN when `btc_pct_chg_entry ≤ 0`
(BTC is flat or falling from window start). Only take BTC DOWN when BTC has bounced
up — giving the bet a genuine mean-reversion thesis (fading a bounce).

### 🟡 4. `soft_exit_secs` 300s → 420s for 15m
Winners resolve at median 256s (4m15s hold). Losers that hit soft_exit drag to
median 571s. Moving the trigger from 300s remaining to 420s remaining (i.e., after
~480–500s of holding with no TP hit) cuts 2 minutes off extended loser holds without
touching winners who already exited via take_profit.

### 🟡 5. Realized-volatility filter (new)
Top-quintile realized vol (Binance spot, 15m pre-entry) → 33% hard-stop rate vs 24%
baseline, 50% WR vs 60%+, EV flips to −$0.48. New filter: skip entries when the
std of BTC log-returns over the last 900s exceeds RV_THRESHOLD (default 0.0029 per
2s bar, configurable via `.env`). Requires btc_history maxlen extended 150→450.

### 🟡 6. Loosen BTC/SOL CLOB trend threshold 0.10 → 0.15
The −0.30..−0.15 CLOB bucket (n=23) had 65% WR / +$2.15 EV but was being blocked
by the ±0.10 threshold. Loosening to ±0.15 admits this positive-EV bucket.
ETH remains exempt from the filter (unchanged — ETH's edge comes from high opposing
trend entries that the filter would block).

**Files:** `main.py`, `src/bot/market_5m.py`, `src/bot/version.py`, `.env` (laptop)

---

## v1.15 — 2026-04-17
**Remove signal mirroring — LIVE runs independent signals, same as PAPER**

**Problem:** Signal mirroring (v1.8) made the LIVE bot copy PAPER entries via
`signal_mirror_{ASSET}_{WINDOW}.json` files. LIVE would enter only after PAPER
wrote the file, picking it up 1–2 poll cycles later. This introduced a
systematic delay and risked stale entry prices (though the live book price
was re-fetched at entry time, the timing lag could mean entering into a
moved market).

**Fix:** Removed both sides of the mirror:
- LIVE side: no longer reads `signal_mirror_*.json` to override `should_enter()`
- PAPER side: no longer writes `signal_mirror_*.json` after opening a position

Both `multi-live` and `multi-loop` now evaluate `should_enter()` independently
with their own price histories. They run the same strategy logic (BTC/ETH/SOL
15m mean reversion) and will enter the same trades when their independent
signals agree. Occasional divergence (different `btc_rate_per_min` due to
separate process histories) is an accepted tradeoff for eliminating staleness.

**Files:** `main.py`, `src/bot/version.py`

---

## v1.12 — 2026-04-16
**Cowork pre-live review: per-strategy summary JSON bug fixed; going live with tightened sizing**

Cowork analyzed the 820-trade paper history and produced a NO-GO verdict on the
full system but a conditional GO on 15m mean-reversion if BTC-5m is suspended
and entry filters are applied. The BTC-5m kill and entry filters were already
in place from v1.10–v1.11 (see `src/bot/signal_5m.py` asset-specific blocks
and `main.py` strategy-config comments). This patch lands the remaining positive
changes and deploys live.

**Fix — per-strategy summary JSON aggregation bug:**
`src/bot/engine_5m.py::_compute_summary()` read the shared `TRADES_FILE`
without filtering by asset/window/strategy. Every `Engine5m(tag="BTC-15m-mean_reversion")`,
`Engine5m(tag="ETH-15m-mean_reversion")`, and `Engine5m(tag="SOL-15m-mean_reversion")`
instance therefore wrote the same aggregate numbers to its own `summary_{tag}.json`
file — making the per-strategy dashboards and the cowork snapshot all show
identical 820-trade / 43.5% WR / −$850 figures regardless of which strategy
was in the filename.

Fix: `_compute_summary()` now accepts optional `(asset, window, strategy)`
filters, `Engine5m.__init__` parses its `tag` into those three components, and
`Engine5m.summary()` passes them through. Legacy `tag=""` callers and any
future aggregate caller get unfiltered stats by passing `None` for each filter.

**Live deployment (Cowork-recommended settings):**
- `LIVE_POSITION_SIZE_USD=3` (down from $20 default; ~0.7× half-Kelly on $500 bankroll)
- `LIVE_MAX_DAILY_LOSS_USD=25` (down from $50 default)
- Enabled strategies: `BTC-15m-mean_reversion`, `ETH-15m-mean_reversion`, `SOL-15m-mean_reversion`
- Disabled: `BTC-5m-mean_reversion` (−$801 paper), `BTC-5m-momentum` (−$168 paper)
- All changes deployed to laptop via `.env` edit + `git pull` + `schtasks /run`.

**Kill-switches active:**
- Daily loss ≥ $25 → circuit breaker trips (paused.flag)
- Concurrent live positions ≤ MAX_POSITIONS (5)
- Stalled-exit rate monitored manually; >35% in last 20 trades → suspend

**Known caveats from Cowork report:**
- Filter-uplift numbers (+$373 on 294-trade history) are in-sample fit, not OOS
  expectancy. Treat as directional, not predictive.
- advisor_skip counterfactual (+$3.30 avg on 184 skipped windows) suggests
  disabling it could be meaningful upside — but the CF math hasn't been verified.
  Leaving advisor disabled (current behaviour) until next review.
- 15m MR per-strategy CIs all include zero. Going live at $3/trade is the
  smallest sustainable size to accumulate the next ~150 trades OOS.

---

## v1.11 — 2026-04-16
**Fix: size orders by actual wallet balance, not API `size_matched`; settle on resolved markets**

**Problem (A) — orphaned positions that can't place TP:**
After a BUY fills, `check_pending_entries()` reads `size_matched` from the order
API and sets `pos.shares = size_matched`. But Polymarket's `size_matched` consistently
over-reports the real on-chain balance by ~4–5% (a fee/rounding quirk that is not
documented, but verified in live logs on 2026-04-16):

```
[LIVE5M] FILLED 9e6fb366 | BTC DOWN 12.82 shares @ 0.390
[LIVE5M] TP order placement failed: balance: 12238490, order amount: 12820000
```

The order said 12.82 shares filled; the wallet only had 12.238. `_place_tp_order`
then tried to SELL 12.82 and Polymarket rejected with "not enough balance."
The 5% tolerance check (`confirmed_shares < pos.shares * 0.95`) passed because
the shortfall was only 4.5% — so the bot proceeded to place a TP it couldn't
afford, got rejected, and retried forever. The position sat with state=OPEN,
no `tp_order_id`, and no way to exit. The user had to sell the shares manually.

This is the bug the user described: "the dashboard says 14 @35, but it in
reality it filled 13.7 @36. The bot loses control of the position when this
happens and does not create a take profit order on Polymarket."

**Problem (B) — infinite retry on resolved markets:**
When a window ends and the market resolves, Polymarket removes the orderbook.
Any subsequent `place_exit` / `_place_tp_order` call fails with
`"the orderbook <id> does not exist"`. The exception handler reverted state to
OPEN, and the main loop fired `place_exit("window_expired")` again on the next
poll — forever, filling `live.log` with the same error every second.

**Fix:**
- `_place_tp_order()`: The TP SELL size is now `floor(confirmed_shares, 2)`
  (true wallet balance), never `pos.shares`. If the balance is within 10% of
  the expected `pos.shares`, we accept it as ground truth and reconcile
  `pos.shares` to match so PnL stays accurate. If the balance is more than
  10% short, we defer (fill genuinely hasn't settled yet).
- `place_exit()`: Same treatment — the SELL size is the floored wallet
  balance. If the balance is below the Polymarket minimum (5 shares) or
  essentially zero, we settle via `_settle_exit` without trying to SELL
  instead of looping on rejection.
- Both functions now catch `"orderbook does not exist"` and call
  `_settle_exit(..., exit_reason="market_resolved", exit_price=0.0)`
  to break the infinite retry loop. The operator sees a clear
  `market_resolved` exit in trades.csv and can manually reconcile on
  Polymarket if the position actually won (shares redeemed for $1 in USDC).

**Files:** `src/bot/live_engine_5m.py`

---

## v1.10 — 2026-04-15
**Fix: Polymarket returns `"MATCHED"` (uppercase) — bot was checking `"matched"` (lowercase)**

**Problem:** Every entry order was timing out after 45s and being cancelled, even when
the buy actually filled and shares appeared in Polymarket. The user saw shares in their
portfolio but the bot had no position record and placed no TP sell — happened 3 times.

Root cause: Polymarket's CLOB API returns order status as uppercase strings
(`"MATCHED"`, `"FILLED"`, `"CANCELED"`). Every status check in the live engine used
lowercase strings (`"matched"`, `"filled"`). Python string comparison is case-sensitive,
so `"MATCHED" in ("matched", "filled")` evaluates to `False`. The fill was never detected.

Flow: GTC BUY fills → `check_pending_entries()` polls `get_order()` → status `"MATCHED"`
doesn't match `"matched"` → no transition to OPEN → 45s timeout → `cancel_entry()` →
CANCEL→OPEN check also misses due to same bug → position removed as CANCELLED while
shares remain on Polymarket untracked.

**Fix:** Added `.lower()` to `order.get("status", "")` in all four status check sites:
- `check_pending_entries()` (partially fixed in v1.9)
- `cancel_entry()` — CANCEL→OPEN path (this is the critical path for 45s timeouts)
- `check_open_tp_fills()`
- `check_pending_exits()`

**Files:** `src/bot/live_engine_5m.py`

---

## v1.9 — 2026-04-15
**Entry taker slippage: +1¢ buffer so GTC order crosses the spread**

**Problem:** The live bot placed a GTC limit BUY at exactly `book_ask` from the
WebSocket (e.g. 0.380). If the WS book was even slightly stale — the real market
ask was already at 0.390 — the order rested as a maker rather than crossing as a
taker. No counterparty was selling at ≤ 0.380, so it sat unfilled for 45s, hit
`ENTRY_FILL_TIMEOUT`, was cancelled, and the position was removed from the CSV.
The user saw the order appear in Polymarket as a pending buy (looked like a fill)
and then disappear when it was cancelled. No TP limit sell ever appeared because
the buy never actually filled.

**Fix:**
- `main.py`: Added `ENTRY_SLIPPAGE = 0.01` (1¢). Entry taker override is now
  `min(book_ask + 0.01, 0.42)` for UP and `min(1 - book_bid + 0.01, 0.42)` for
  DOWN. A GTC BUY at `best_ask + 1¢` immediately crosses the spread as a taker
  even if the WS price is 1–2 cents stale. The 0.42 cap preserves the
  positive-EV gate.
- `live_engine_5m.py`: `check_pending_entries()` now detects `status=cancelled`
  from the exchange API and cleans up the position immediately (previously it
  waited the full 45s `ENTRY_FILL_TIMEOUT` before `cancel_entry()` ran).

**Files:** `main.py`, `src/bot/live_engine_5m.py`

---

## v1.8 — 2026-04-15
**Signal mirroring: live bot follows paper entries when process histories diverge**

**Problem:** Paper and live bots are separate OS processes. Each maintains its own
`btc_history`, `price_history`, and `clob_feed` — so history-based filters
(`btc_rate_per_min`, `clob_trend`, GBM collapse probability) compute different
values. The paper process fires `should_enter()=True`; the live process computes
a different rate and gets `False`. Trade is missed. Happened twice in one day,
both times the paper trade won.

**Fix:** Signal mirror file (`output/5m_live/signal_mirror_{ASSET}_{WINDOW}.json`).
- **Paper side**: after `engine.open()`, writes a mirror containing `condition_id`,
  `side`, `entry_price`, `take_profit`, `window_end_ts`, `written_at`.
- **Live side**: every poll cycle, after `should_enter()` returns False, checks for
  a fresh mirror (`condition_id` matches, `written_at < 30s`, still in entry window).
  If found, sets `do_enter=True` and falls through the existing entry path — uses
  current taker price from the live book, GBM/CLOB checks still apply.
- Mirror file is deleted after being consumed to prevent re-use.
- 30s freshness check prevents stale mirrors from triggering entries in later windows.

**Files:** `main.py`

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
