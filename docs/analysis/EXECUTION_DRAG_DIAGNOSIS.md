# Execution Drag Diagnosis — Next Investigation

**Created:** 2026-05-06 (v1.27)
**Status:** Open. LIVE paused until resolved.

---

## The finding

Matched-pairs analysis on the same `(asset, side, window_end_ts)` between PAPER and LIVE:

| Asset | n matched | LIVE EV | PAPER EV (scaled to $5) | LIVE − PAPER | t-stat |
|-------|-----------|---------|--------------------------|--------------|--------|
| BTC   | 22        | -$2.29  | -$1.93                   | **-$0.36**   | **-3.76** |
| ETH   | 15        | -$0.23  | +$0.32                   | **-$0.55**   | **-2.52** |
| SOL   |  7        | -$0.87  | +$0.76                   | -$1.63       | -1.37  |

This is paired, not noise. Same windows, same signals — LIVE consistently underperforms by $0.36 to $0.55 per trade. On a $5 position, that is 7–11% of capital per trade in pure execution cost. PAPER MR-15m EV is +$0.12; LIVE EV after drag is roughly **-$0.33** even at the strategy's PAPER edge.

This swamps any filter improvement. Until execution drag is reduced, every PAPER win is eaten by slippage on LIVE.

---

## Suspected sources (in priority order)

### 1. TP SELL fills below 0.60
**Evidence:** LIVE BTC `take_profit` exits show pnl below theoretical:

| Trade | Entry | Shares | Theoretical pnl @ 0.60 | Actual pnl | Slippage |
|-------|-------|--------|-------------------------|------------|----------|
| 5     | 0.39  | 12.24  | +$2.57                  | +$2.34     | -$0.23   |
| 7     | 0.39  | 12.24  | +$2.57                  | +$2.34     | -$0.23   |
| 10    | 0.37  | 20.62  | +$4.74                  | +$4.37     | -$0.37   |
| 11    | 0.40  | 19.12  | +$3.82                  | +$3.47     | -$0.35   |

TP exits average ~$0.30 below theoretical. Three possibilities:
- (a) GTC SELL at 0.60 doesn't fully fill at 0.60 — partial fills at lower prices
- (b) Polymarket fees on the SELL side aren't accounted for in PAPER's pnl calc
- (c) Order rests as maker, eventually crossed by a taker hitting at 0.59 instead of 0.60

**Investigation:** Pull LIVE order fill logs for a TP exit. Inspect the actual matched price(s). Compare to PAPER's `pnl = (TP_price - entry_price) × shares`.

### 2. `hard_stop_floor` exits at price < 0.10
**Evidence:** LIVE BTC `hard_stop_floor` trades show -80% to -97% losses. With stop placed at 0.10 from entry ~0.40, the maximum loss should be (0.10 - 0.40) × shares ≈ -75% of position. Anything beyond -75% is slippage past the stop price.

| Trade | Entry | Stop | pnl% | Excess slippage |
|-------|-------|------|------|------------------|
| 2     | 0.40  | 0.10 | -97.5% | -22.5pp past stop |
| 4     | 0.375 | 0.10 | -97.45% | -23pp past stop |
| 14    | 0.4   | 0.10 | -82.09% | -7pp past stop |
| 18    | 0.39  | 0.10 | -80.78% | -5.8pp past stop |

Some `hard_stop_floor` exits have `exit_price=0.0` recorded — likely the position resolved against us (market settled to 0) before the stop matched. **A market-resolution loss is NOT a hard stop — it's a stop that failed to execute.** The bot should not be classifying these as `hard_stop_floor` if the actual exit was market resolution.

**Investigation:**
- (a) Are `hard_stop_floor` orders being placed late (after price has already gapped past 0.10)?
- (b) Are they GTC limit at 0.10 that don't match because the bid is below 0.10 already?
- (c) Should the stop be a market order or a tighter price target?

### 3. Possible fee leakage
`entry_fee_usd` and `exit_fee_usd` are recorded as 0.0 in all LIVE trades. Polymarket charges no maker fees but takers pay; partial-fill logic may make us a taker on entry. PAPER ignores fees entirely.

**Investigation:** Polymarket ops log for fee debits. Compare `wallet_balance` change against `(exit_price × shares) - (entry_price × shares)`.

### 4. The two `exit_price=0.000` LIVE rows from April 26
Mentioned in the May 1 Cowork review and still unresolved. Likely SDK V2 exit-price reporting bug. Stripping these rows: LIVE ETH EV improves from -$0.35 to -$0.04, but the matched-pair drag persists.

---

## What to investigate (concrete steps)

1. **Pull recent LIVE TP fill data.** For each `take_profit` exit, get the actual matched price from Polymarket order history. Quantify the average gap to 0.60.

2. **Check `hard_stop_floor` order state.** For each such trade, verify whether the exit order matched at 0.10 or whether the market resolved before the order hit. If the latter, fix the exit_reason classification.

3. **Re-run matched-pairs on a smaller window.** The current matched-pairs analysis spans the full LIVE history (some trades pre-v1.21 when filters differed). Restrict to v1.26+ trades (small n, but cleaner) to confirm drag still holds.

4. **Trace one round-trip.** Pick a single LIVE trade. Walk through the full lifecycle: order placement timestamp, fill timestamp, fill price, fees, exit order placement, exit fill, exit fees, final pnl. Reconcile against PAPER's idealized pnl on the same window.

5. **Verify `entry_fee_usd=0.0` is not a recording bug.** If actual fees are being paid but not logged, that fully explains 1¢/share drag.

---

## Until this is resolved

- LIVE remains paused via `paused.live.flag`
- BTC fully off LIVE in code (v1.27)
- ETH and SOL still LIVE-eligible if user resumes — but at $5 size, ETH PAPER edge does not clear the $0.45 drag. Either size up to $15-20 once drag is identified-and-bounded, or accept LIVE-as-paid-sandbox.

## Decision triggers for resuming LIVE

LIVE should resume only after:
- (a) Root cause(s) of drag identified
- (b) At least one drag source materially reduced (e.g., fix TP slippage to <$0.10/trade)
- (c) Re-run matched-pairs on n=20+ post-fix LIVE trades to confirm drag has narrowed
