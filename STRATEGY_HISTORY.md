# Strategy History — Prediction Market Bot

**Last updated:** 2026-04-18
**Purpose:** Single source of truth for what the bot IS doing, what it WAS doing, and how to revert changes.

> **CRITICAL — READ FIRST:**
> The bot does **NOT** use Kalshi. It does **NOT** do cross-market arbitrage.
> Old memory files reference a Kalshi-arbitrage strategy that was retired around April 5, 2026.
> The current strategy is **15-minute Up/Down mean reversion on Polymarket only**.

---

## Current active strategy (as of v1.14 — 2026-04-16)

### What it trades
- **Platform:** Polymarket only (no Kalshi)
- **Markets:** 15-minute "Up/Down" prediction markets
- **Assets:** BTC, ETH, SOL (5m markets disabled — negative EV)
- **Strategy:** `mean_reversion` (momentum strategy disabled — negative EV)

### How it works
Every 15 minutes Polymarket creates a new "Will [ASSET] be UP or DOWN after 15 minutes?" market. The bot:
1. Watches the UP/DOWN prices during each window
2. Enters when price hits a mean-reversion threshold (contrarian bet)
3. Places a GTC limit SELL at take-profit
4. Exits via TP, stop-loss, or window expiration

### The two processes
| Command | Purpose | Money at risk |
|---------|---------|---------------|
| `main.py multi-live` | LIVE trading — real money on Polymarket | Yes |
| `main.py multi-loop` | PAPER trading — simulated, for data collection | No |

**Independent signals (v1.15):** LIVE and PAPER both evaluate `should_enter()` independently. No mirroring — LIVE enters on its own signal, not a copy of PAPER's.

### Pause control
- **LIVE only:** `output/5m_live/paused.live.flag` — halts new LIVE entries, existing positions still managed. Set via dashboard button or manually.
- **PAPER:** Never paused by flag — always runs (when the process is running).

---

## Version history — what was added when

Each version is tagged in `src/bot/version.py`. To revert, check out the commit hash listed.

### v1.17 — 2026-04-18 (pending push)
Fix circuit breaker not recording FOK (stop-loss) exits. `place_exit()` was returning `None` even when it settled the position synchronously inline (FOK fills, wallet-empty, min-shares, market-resolved paths). main.py discarded the return value, so `cb.record_trade()` was never called for hard_stop_floor / force_exit / soft_exit_stalled / window_expired exits. Take-profit exits use GTC orders settled via `check_open_tp_fills()` which DID propagate to CB — so CB was tracking wins only. Fix: `place_exit()` now returns `ClosedLiveTrade5m | None`; main.py calls `cb.record_trade()` on non-None return.

### v1.16 — 2026-04-18 (pending push)
Cowork filter set: hard_stop gate wired for 15m (240s), soft_exit 300→420s, BTC DOWN regime filter, realized-vol filter (RV_THRESHOLD=0.0029), CROSS_WINDOW_MAX 0.15→0.10, CLOB threshold 0.10→0.15.

### v1.15 — 2026-04-17 (pending push)
Remove signal mirroring: LIVE evaluates `should_enter()` independently. Both bots run the same strategy logic on their own price histories — no mirror lag, no stale entries.

### v1.14 — 2026-04-16 (`6035589`)
Fix FOK exit price fallback: use actual market price at exit time instead of AGGRESSIVE_EXIT_PRICE (0.01) when Polymarket doesn't return average_price. Fixes dashboard entry/exit price inaccuracy and PnL understatement.

### v1.13 — 2026-04-16 (`c3da916`)
Record `resolution_side` and `our_side_won` in live trades CSV for win/loss tracking on resolved markets.

### v1.12 — 2026-04-16 (`6a98752`) — **MAJOR: Live deployment config**
- Per-strategy summary JSON filtered by (asset, window, strategy). Previously all strategies showed identical aggregate numbers.
- **Live deployment settings (Cowork-recommended):**
  - `LIVE_POSITION_SIZE_USD=3` (down from $20; ~0.7× half-Kelly on $500 bankroll)
  - `LIVE_MAX_DAILY_LOSS_USD=25` (down from $50)
  - Enabled: BTC-15m MR, ETH-15m MR, SOL-15m MR
  - Disabled: BTC-5m MR (−$801 paper), BTC-5m momentum (−$168 paper)

### v1.11 — 2026-04-16 (`e8f3a51`)
Size orders by actual wallet balance, not API `size_matched`. Fixes bug where Polymarket's size_matched over-reports by ~4–5%, causing TP sells to fail with "not enough balance." Also handles resolved-market orderbook errors (infinite retry → clean `market_resolved` exit).

### v1.10 — 2026-04-15 (`60d2e3e`)
Fix case-insensitive order status checks. Polymarket returns `"MATCHED"` uppercase; bot was checking `"matched"` lowercase. Caused every entry to time out at 45s even when filled, leaving untracked shares in wallet.

### v1.9 — 2026-04-15 (`bf3c778`)
Entry taker slippage +1¢. GTC limit BUY at exactly `book_ask` was resting as maker when book was 1–2c stale. Now places at `min(book_ask + 0.01, 0.42)` to cross spread as taker.

### v1.8 — 2026-04-15 (`5954580`) — **MAJOR: Signal mirroring**
Live bot follows paper entries via mirror files. Paper and live are separate processes with independent `btc_history` — they computed different `btc_rate_per_min` values, so live missed entries paper took (and won). Mirror file (`output/5m_live/signal_mirror_{ASSET}_{WINDOW}.json`) bridges them.

### v1.7 — 2026-04-15 (`9e281e9`)
Show real wallet balance in Equity tab instead of fake $1000.

### v1.6 — 2026-04-15 (`c754edf`)
`BTC_SKIP_RATE` configurable via .env; default raised 20 → 50 $/min. Too tight at $20 caused false blocks on winning trades.

### v1.5 — 2026-04-15 (`6b94539`)
`CROSS_WINDOW_MIN/MAX` configurable via .env. Default changed from −0.06 → −0.15 because the bot was skipping every entry during slow downtrends.

### v1.4 — 2026-04-15 (`8e5e9ca`)
Immediate TP order placement on fill. Post standing GTC SELL at TP price the moment BUY fills — no poll-loop latency.

### v1.3 — 2026-04-15 (`b72e509`)
Exchange balance reconciliation on startup. Circuit breaker daily loss reduced $50 → $15.

### v1.2 — 2026-04-15 (`631e867`)
Speed: BinanceFeed background thread (non-blocking), 1s live poll interval (was 2s).

### v1.1 — 2026-04-15 (`612047a`)
Fix all 9 live engine audit findings (Findings 1-9). Cancel-entry fill detection, orphan cleanup, pre-save pending_exit, window expiry check, circuit breaker, etc.

### v1.0 — 2026-04-14 (`e383c81`) — **Live engine baseline**
Initial live engine deployment. 18 production-readiness audit findings implemented. GTC limit entries, FOK aggressive exits, per-market CSV state, paper-parity signal logic.

### Pre-v1.0 commits (April 11-14) — Cowork-driven signal improvements

| Date | Commit | Change |
|------|--------|--------|
| 2026-04-14 | `7bb84f7` | Add `multi-live` command for live multi-market trading |
| 2026-04-14 | `8f0556d` | `LIVE_POSITION_SIZE_USD` configurable |
| 2026-04-13 | `c7f141c` | Cowork: ETH-15m window timing + CLOB crowding + BTC-5m 60s return monitor |
| 2026-04-13 | `75ba5f3` | Cowork: BTC-5m late-entry gate + decel debug + ETH velocity monitor |
| 2026-04-12 | `1305497` | Asset-specific entry filters from Cowork segmentation analysis |
| 2026-04-12 | `0065c74` | Tighten entry price and liquidity caps (Cowork) |
| 2026-04-12 | `1f38a92` | Add CLOB midpoint trend filter: skip trades opposing 60s trend |
| 2026-04-11 | `e1c50f2` | Dynamic take-profit by entry price: 65% WR vs 39% actual (Cowork) |
| 2026-04-11 | `979e966` | Add GBM collapse scorer: blocks 60.5% hard_stop_floor at threshold 0.30 |
| 2026-04-11 | `3baf9d1` | Add liquidity floor $22k: HSF rate drops 37% → 9% above $30k |
| 2026-04-11 | `9d30d74` | Phase 1 filters: cross_window, entry floor, drop BTC 5m threads |

---

## Current .env settings (as of 2026-04-16 after stop-loss increase)

**These live on the laptop only — .env is not git-tracked.**

```
# PAPER bot (multi-loop) — 15m mean reversion, BTC/ETH/SOL
PAPER_EDGE_THRESHOLD=0.008
PAPER_EDGE_RATIO_THRESHOLD=0.01
PAPER_MIN_RECENT_TRADES=1
PAPER_MIN_RECENT_NOTIONAL=0.5
PAPER_MIN_BUY_SHARE=0.55
PAPER_MIN_LIQUIDITY=5000.0
PAPER_MAX_HOURS_TO_EXPIRY=8760.0
PAPER_MAX_POSITIONS=50
PAPER_MAX_CANDIDATES=20
PAPER_LOOKBACK_SECONDS=1800
PAPER_LOOP_SLEEP_SECONDS=180
PAPER_MAX_SECONDS_SINCE_LAST_TRADE=3600
PAPER_TAKE_PROFIT_PCT=0.15
PAPER_STOP_LOSS_PCT=0.10         # ← changed 2026-04-16: was 0.04 (too tight, stopping before mean reversion)
PAPER_MAX_HOLDING_SECONDS=28800
PAPER_MAX_FALLBACK_SECONDS=60

# LIVE bot (multi-live)
LIVE_POSITION_SIZE_USD=5         # ← reduced 2026-04-18: was $8 (caution while v1.16 filters bed in)
LIVE_MAX_DAILY_LOSS_USD=30.0     # circuit breaker — raised 2026-04-17: was $15

# Signal filters (apply to both paper and live)
CROSS_WINDOW_MIN=-0.15           # v1.5
CROSS_WINDOW_MAX=0.10            # ← tightened 2026-04-18: was 0.15 (0.02 in old docs was wrong)
RV_THRESHOLD=0.0029              # ← new 2026-04-18: skip if BTC realized vol > this
BTC_SKIP_RATE=50.0               # v1.6

# Polymarket credentials (same both machines)
POLYMARKET_SIGNATURE_TYPE=2      # Gnosis Safe
POLYMARKET_PROXY_ADDRESS=0x0529A7b9bf204488aDF0119D6E70a879bD9C44BB
```

---

## Critical do-not-re-introduce bugs

From `CLAUDE.md` — tested the hard way:

1. **Never use `(left_ts - right_ts)` for Kalshi timestamps** — pandas raises `KeyboardInterrupt` from C-level on overflow. Use `int(left_ts.value) - int(right_ts.value)` arithmetic.
   > **Note:** This refers to historical Kalshi comparison code. Kalshi is no longer used, but if reviving old scripts, preserve this pattern.

2. **Never remove `write_through=True`** from `io.TextIOWrapper` in `main.py` — bot.log stays empty without it.

3. **Never remove the `try/except BaseException: pass`** around `_time.sleep(1)` in `main.py` — pandas SIGINT fires late.

4. **Never set `PAPER_MAX_FALLBACK_SECONDS` above 120** — stale entry prices trigger immediate stop-losses.

5. **Order status checks must use `.lower()`** (v1.10) — Polymarket returns uppercase `"MATCHED"`, not `"matched"`.

6. **Entry BUY must include +1¢ slippage** (v1.9) — otherwise GTC orders rest as maker and time out at 45s.

7. **TP SELL size = floor(wallet_balance, 2)** (v1.11) — not `pos.shares`. Polymarket over-reports `size_matched` by ~4-5%.

---

## Laptop deployment — what's actually running

As of 2026-04-16 20:30:
- **PolyBot** scheduled task → `watch_bot.ps1` → runs `main.py multi-live` (LIVE)
- **PolyDashboard** scheduled task → runs `main.py dashboard`
- **PolyPaper** scheduled task → `watch_paper.ps1` → runs `main.py multi-loop` (PAPER, with watchdog/restart loop) ← **added 2026-04-16**
- **PolyBotLive** scheduled task → `start_live.bat` (redundant, manual-only)
- **RunBot** scheduled task → `run_bot.bat` → `main.py paper-loop` (LEGACY BTC strike bot — last run 2026-03-30)

**✅ FIXED (2026-04-16):** `PolyPaper` scheduled task now runs `watch_paper.ps1` → `main.py multi-loop` continuously with auto-restart on crash. Logs to `watchdog.log` with `[WATCHDOG-PAPER]` prefix.

---

## How to revert strategy changes

1. **Find the version** you want to revert to in "Version history" above
2. **On dev machine:**
   ```powershell
   cd "C:\Users\home user\Desktop\prediction-market-analysis"
   git log --oneline   # find the commit hash
   git checkout <hash>  # or: git revert <hash>
   git push
   ```
3. **On laptop:** `git pull` + restart bot per CLAUDE.md

**Note:** `.env` changes are not git-tracked. To revert parameter changes, refer to this doc's "Current .env settings" section for the current values, and the version history for historical values.

---

## How to update this doc

**Every time a strategy change lands:**
1. Bump `PATCH` in `src/bot/version.py`
2. Add entry to `PATCH_HISTORY.md`
3. Add entry to "Version history" section above
4. If `.env` changed, update "Current .env settings" above
5. Commit with descriptive message including version tag
