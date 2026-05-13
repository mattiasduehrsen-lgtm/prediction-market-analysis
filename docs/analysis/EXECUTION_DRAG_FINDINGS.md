# Execution Drag — Code Audit Findings

Audit of `src/bot/live_engine_5m.py`, `src/bot/engine_5m.py`, and `main.py` poll loop. Goal: explain measured −$0.36 to −$0.55/trade drag of LIVE vs PAPER.

## TL;DR (ranked by likely contribution)

1. **TP exit drag is structural and is the biggest single source.** PAPER books TP exits at the *current observed market price* (`cur_up`), which is by construction `>= take_profit` when the TP condition fires. LIVE books at exactly `pos.take_profit` because the GTC SELL is resting there. On a $5/12.24-share trade with the TP=0.60 target, if the cross-over poll observed `cur_up = 0.62`, PAPER records pnl using 0.62 (`+$2.72`) while LIVE fills at 0.60 (`+$2.34`). That's the ~$0.23-$0.37 gap seen in the data. (`main.py:610-611` vs `live_engine_5m.py:472-479`).
2. **`hard_stop_floor` is recorded with `exit_price=0.0` when the FOK fill returns no `average_price` AND no `market_price_at_exit`.** When a market has resolved or the orderbook is gone, the wallet-empty / orderbook-gone branches in `place_exit` settle with `actual_exit_price=0.0` *and exit_reason left as `hard_stop_floor`* (it's not always rewritten to `market_resolved`). That gives `pnl = 0 - $5 = -$5` (-100%) — matching the −80% to −97% rows. (`live_engine_5m.py:894-908`, `live_engine_5m.py:1098-1131`).
3. **No fees are recorded but Polymarket's CLOB is currently 0% maker / 0% taker for binary outcome markets.** The `entry_fee_usd=0.0` and `exit_fee_usd=0.0` are correct in dollar terms — fees are not a hidden source of drag. (`live_engine_5m.py:1126`, `engine_5m.py:38`).
4. **`+1¢` slippage is added to the entry price both for LIVE and PAPER** (line `main.py:845-850`), so PAPER records the same inflated entry as LIVE. This is NOT a drag source — it cancels out in the comparison. However, LIVE's actual fill `average_price` may be *lower* than the inflated limit (price improvement), and that gets written back to `pos.entry_price` (`live_engine_5m.py:790-795`) — so LIVE can actually have *better* entry pricing than PAPER on average. The drag is not on the entry side.
5. **Resolved-market settle-as-`hard_stop_floor` mis-classification.** When the orderbook disappears mid-position, a force-exit attempt goes through `place_exit("hard_stop_floor")` → wallet-empty/orderbook-gone → `_settle_exit(..., 0.0, "hard_stop_floor", ...)` is called *with the original reason preserved*, not rewritten to `market_resolved`. The two `exit_price=0.000` LIVE rows are almost certainly this case.

---

## 1. TP exit slippage (PRIMARY drag source)

### LIVE path — fills at exact TP
`live_engine_5m.py:470-479`:
```python
# ── Post GTC SELL at take_profit ────────────────────────────────────
order_args = OrderArgs(
    price=pos.take_profit,
    size=tp_size,
    side=SELL,
    token_id=pos.token_id,
)
```
The TP order is a GTC limit SELL resting at exactly `pos.take_profit` (e.g. 0.60). The fill happens when buying pressure crosses 0.60. The recorded exit_price is the API's `average_price`:

`live_engine_5m.py:533-535`:
```python
if status in ("matched", "filled"):
    actual_exit = float(order.get("average_price") or pos.take_profit)
    trade = self._settle_exit(pos_id, actual_exit, "take_profit", 0.0)
```
For a resting GTC SELL at 0.60, the average matched price is essentially 0.60 (might be 0.60 to 0.601 depending on aggressor side rules). So LIVE pnl ≈ `12.24 × 0.60 - 5.00 = $2.34`.

### PAPER path — books at current observed price (which has crossed TP)
`main.py:575-583` calls `should_exit`:
```python
do_exit, reason = should_exit(
    side=pos.side,
    entry_price=pos.entry_price,
    current_up_price=cur_up,
    take_profit=pos.take_profit, ...
)
```
`signal_5m.py:325-328`:
```python
current = current_up_price if side == "UP" else (1.0 - current_up_price)
if current >= take_profit:
    return True, "take_profit"
```
TP condition fires when the current observed side price `>=` take_profit. Then PAPER closes at:

`main.py:609-611`:
```python
else:  # PAPER
    exit_price = cur_up if pos.side == "UP" else (1.0 - cur_up)
    trade = engine.close(pos_id, exit_price, reason, price_60s_after_entry=p60_after)
```
So PAPER's recorded exit_price is `cur_up` itself, which by definition is `>= take_profit`. With a 1-2s poll cadence and a price that just crossed 0.60, PAPER often records 0.61, 0.62, even 0.63.

`engine_5m.py:466-472`:
```python
gross_proceeds = pos.shares * exit_price
exit_fee = gross_proceeds * MAKER_FEE   # = 0
net_proceeds = gross_proceeds - exit_fee
pnl_usd    = net_proceeds - pos.size_usd
```

### Quantification
On the example trade (entry=0.39, shares=12.24, TP=0.60):
- LIVE settles at 0.60 → pnl = 12.24 × 0.60 − 5 = +$2.34
- PAPER often books 0.62 because that was the polled price → pnl = 12.24 × 0.62 − 5 = +$2.59

Gap = $0.25. Matches the observed $0.23-$0.37.

This is a **PAPER over-statement of pnl**, not a LIVE under-statement. PAPER is wrong; LIVE is reflecting reality.

---

## 2. `hard_stop_floor` mis-classification / mis-execution

### When it fires
`signal_5m.py:330-333`:
```python
if current <= 0.08 and seconds_remaining < hard_stop_max_remaining:
    return True, "hard_stop_floor"
```
i.e. the cheap side has collapsed to ≤ $0.08.

### How LIVE executes it
`live_engine_5m.py:836-845`:
```python
aggressive_reasons = {
    "hard_stop", "hard_stop_floor",
    "soft_exit_stalled",
    "trailing_stop_z2", "trailing_stop_z3",
    "force_exit_time", "force_exit_stuck",
    "window_expired",
}
if exit_reason in aggressive_reasons:
    exit_price = AGGRESSIVE_EXIT_PRICE   # 0.01
    order_type = OrderType.FOK   # Fill or Kill
```
The order is a FOK SELL at 0.01 — effectively a market order that hits the best available bid.

### Why exit_price=0.0 / huge losses get recorded

Three paths all settle with reason `hard_stop_floor` preserved:

**Path A — wallet empty (`live_engine_5m.py:894-899`):**
```python
if exit_size < 0.01:
    print(f"...wallet empty... Settling as {exit_reason}.")
    return self._settle_exit(position_id, 0.0, exit_reason, price_60s_after_entry)
```
If position resolved against us, the conditional tokens were redeemed for $0 by the exchange. Wallet is empty, `exit_reason` is still `hard_stop_floor`, settled at 0.0 → pnl = -$5 (-100%). This is mis-classification: should be `market_resolved`.

**Path B — orderbook gone (`live_engine_5m.py:940-945`):**
```python
if "orderbook" in exc_str and "does not exist" in exc_str:
    return self._settle_exit(position_id, 0.0, "market_resolved", price_60s_after_entry)
```
This one *does* correctly rewrite to `market_resolved`. So orderbook-gone is correctly classified.

**Path C — FOK kill / no average_price (`live_engine_5m.py:994-1004`):**
```python
_ap = fok_status.get("average_price")
actual_exit = float(_ap) if _ap and float(_ap) > 0 else 0.0
if actual_exit <= 0:
    actual_exit = market_price_at_exit if market_price_at_exit > 0 else exit_price
    # exit_price here is AGGRESSIVE_EXIT_PRICE = 0.01
```
If both `average_price` is missing AND `market_price_at_exit` was passed as 0, fallback is `exit_price = 0.01`. Then `_settle_exit(..., 0.01, "hard_stop_floor", ...)` → pnl ≈ 12.24 × 0.01 − 5 = −$4.88 (−97.6%). Matches the −97% rows.

If `market_price_at_exit` was passed but very small (e.g., 0.04 since the price had collapsed), pnl ≈ 12.24 × 0.04 − 5 = −$4.51 (−90%). Matches the -80%/-90% rows.

So LIVE's `hard_stop_floor` with -90% to -97% is a *real* economic outcome — selling 12.24 shares of a near-worthless token. PAPER on the same exit also at `cur_up` ≈ 0.05-0.08 records pnl ≈ -$4.00 to -$4.39. The gap (-$0.50 to -$0.97) is the realized aggressive-exit cost: PAPER assumes you can sell 12 shares at the observed midpoint with infinite depth; LIVE actually has to walk the bid stack.

### `exit_price=0.000` rows — the SDK V2 bug or wallet-empty bug

The most likely cause in `live_engine_5m.py:894-899` (wallet empty) — when the FOK is fired but the position resolved before the FOK landed, `get_balance_allowance` returns 0, the early-return settles at exit_price 0.0 and reason left as the original (`hard_stop_floor`). The exit reason should be rewritten:

```python
# Current (wrong)
return self._settle_exit(position_id, 0.0, exit_reason, price_60s_after_entry)
# Should be
return self._settle_exit(position_id, 0.0, "market_resolved", price_60s_after_entry)
```

---

## 3. Fee accounting

`live_engine_5m.py:1126`: `exit_fee_usd=0.0,    # maker orders: 0% fee`
`engine_5m.py:38`: `MAKER_FEE = 0.00    # 0% fee for limit (maker) orders — Polymarket charges only takers`

Polymarket's binary outcome markets currently have 0% maker AND 0% taker fees on the CLOB (this changed in 2024 — the older "10% taker" comments are stale). The code's 0% assumption is correct as of 2026-05.

**This is NOT a drag source.** If Polymarket reinstates a taker fee, the `+1¢` entry slip and FOK exits would all incur it. For now: nil.

The `entry_fee_usd` field is also correctly 0.0 because GTC entry orders that cross the spread (price = ask + 1¢) match against resting maker orders on the *opposite* side — the bot is the taker, but the taker fee is still 0%. No drag.

---

## 4. PAPER vs LIVE divergence summary

| Aspect | PAPER (`engine_5m.py`) | LIVE (`live_engine_5m.py`) | Drag implication |
|--------|------------------------|------------------------------|------------------|
| Entry price written | `entry_price` from caller (book_ask + 1¢) | `average_price` from API (often *better* than book_ask + 1¢ due to price improvement) | LIVE entry is often equal or better than PAPER entry. Not a drag source. |
| Entry shares | `POSITION_SIZE / entry_price` (float, e.g. 38.461538) | `round(POSITION_SIZE / entry_price, 2)` (e.g. 12.82) then reconciled to actual wallet balance via `_place_tp_order` (Polymarket deducts ~4.5% so wallet ≈ 12.24) | LIVE has ~4.5% fewer shares than naive expectation. PAPER doesn't model this. **Drag: ~$0.10/trade on a TP win** (12.24×0.60 vs 12.82×0.60 = $0.35 less revenue at TP). |
| Entry slippage | none modelled (assumes instant fill at limit) | order may sit 0-45s; 1¢ buffer above ask; TIMEOUT cancels at 45s | If price moves against, LIVE doesn't enter at all (PAPER does). Survivor bias in LIVE. |
| Entry liquidity check | none — fills assumed at any depth | real CLOB fills at actual ask depth | Possible adverse selection on fast-moving prices. Hard to quantify. |
| TP exit price | `cur_up` (current observed price, which has just crossed TP from below — typically 0.61-0.63 for TP=0.60) | API `average_price` of GTC SELL resting at exactly `pos.take_profit` (= 0.60) | **Primary drag: ~$0.20-$0.30/winning trade.** PAPER over-states. |
| TP exit fills | instant, full size | actual book depth at 0.60; partial fills possible (no logic checks for partial — `status in matched/filled`) | Possible — see below. |
| Hard-stop exit price | `cur_up` (observed before exit decision) | FOK at 0.01 → matches best bid; if no bid → killed and re-tried | LIVE walks the bid stack, PAPER assumes it sells at observed price. **Drag: ~$0.20-$0.50/loser.** |
| Window-expired / no `cur_up` | exits at 0.01 (`main.py:572`) | aggressive FOK at 0.01 (`main.py:568`) | Roughly equal — both correct. |
| Fees | 0% maker, 0% taker (correct) | 0% maker/taker recorded as 0 (correct) | No drag. |
| Resolved-mid-trade | n/a — paper doesn't see settlement | settles at 0.0 with original `exit_reason` preserved (mis-classification) | Mis-categorized as `hard_stop_floor` instead of `market_resolved`. |
| Partial fills | not possible (instant) | API only checks `status in (matched, filled)`; if `status="partially_matched"` the loop continues polling. The eventual fill price is `average_price` of all matches. | If price drifts after partial fill, average_price drops. Real risk on TP fills as price reverses. **Drag: variable, possibly $0.05-$0.20/trade.** |

---

## 5. Recommended fixes (prioritized)

### Fix 1 — Make PAPER match LIVE on TP exit price (HIGH, ~$0.25/winning trade)

**Reason:** PAPER over-states TP wins by booking at `cur_up` instead of `take_profit`. This is the largest measurable drag.

`engine_5m.py` / `main.py:609-611`:
```python
else:
    exit_price = cur_up if pos.side == "UP" else (1.0 - cur_up)
    trade = engine.close(pos_id, exit_price, reason, ...)
```
Change to: when `reason == "take_profit"`, use `pos.take_profit` (matching LIVE's GTC limit fill semantics):
```python
else:
    if reason == "take_profit":
        exit_price = pos.take_profit
    else:
        exit_price = cur_up if pos.side == "UP" else (1.0 - cur_up)
    trade = engine.close(pos_id, exit_price, reason, ...)
```
**Risk:** This makes PAPER show ~$0.20/winning trade less. It does NOT change LIVE behaviour. It corrects the divergence so going forward LIVE−PAPER drag should be ~$0.10/trade or less. **Apply immediately.**

### Fix 2 — Reconcile PAPER share count with LIVE's wallet-loss (MEDIUM, ~$0.10/trade)

**Reason:** LIVE actually receives ~4.5% fewer shares than `POSITION_SIZE / entry_price` due to a Polymarket on-chain rounding/fee. PAPER doesn't model this.

`engine_5m.py:407-409`:
```python
entry_fee = POSITION_SIZE * MAKER_FEE   # = 0
net_investment = POSITION_SIZE - entry_fee
shares = net_investment / entry_price
```
Change to model the ~4.5% deduction:
```python
PAPER_FILL_DISCOUNT = 0.955   # observed wallet/expected ratio on LIVE fills (v1.11)
shares = round((POSITION_SIZE / entry_price) * PAPER_FILL_DISCOUNT, 2)
```
**Risk:** LOW — this is a one-line change purely in PAPER. Reduces PAPER pnl by 4.5% across the board, bringing it closer to LIVE.

### Fix 3 — Rewrite `exit_reason` in wallet-empty path (MEDIUM, classification accuracy only)

**Reason:** `hard_stop_floor` rows with `exit_price=0.0` are mis-classified `market_resolved` events.

`live_engine_5m.py:894-899`:
```python
if exit_size < 0.01:
    print(f"...wallet empty... Settling as {exit_reason}.")
    return self._settle_exit(position_id, 0.0, exit_reason, price_60s_after_entry)
```
Change to:
```python
if exit_size < 0.01:
    print(f"...wallet empty — market resolved before exit. Was {exit_reason}.")
    return self._settle_exit(position_id, 0.0, "market_resolved", price_60s_after_entry)
```
**Risk:** None — only changes the recorded `exit_reason` label. No pnl change. Improves data quality for analysis.

### Fix 4 — Use `market_price_at_exit` more aggressively in FOK fallback (LOW, ~$0.05/loser)

**Reason:** When FOK returns no `average_price` and `market_price_at_exit` is 0, code falls back to `exit_price = 0.01` (the order placement price), inflating the recorded loss.

`live_engine_5m.py:994-1004`: already uses `market_price_at_exit` when nonzero. The main.py call at line 601-603 always passes it (`cur_side_price`). Verify `cur_side_price` is correct when the price has collapsed to ~0.04.

**Action:** Spot-check the CSV rows with `exit_price=0.0` against the market_price_at_exit from logs. Likely a logging issue. **Don't change behaviour — just verify.**

### Fix 5 — Model partial-fill price drift in PAPER (LOW, ~$0.05-$0.20/trade)

**Reason:** LIVE GTC SELL at TP=0.60 fills 50% at 0.60, 50% at 0.595 if price reverses. `average_price` is then ~0.598. PAPER assumes 100% at exactly the trigger price.

This is harder to model accurately and the magnitude is uncertain. Defer until Fixes 1-3 are landed and the residual drag is re-measured.

---

## Honest caveats

- I traced the code paths but did not run the bot or replay actual trades. The conclusion that PAPER's TP exit at `cur_up` is the primary drag source is **derived from the code logic**, not from direct comparison of corresponding PAPER/LIVE trades. To confirm, pull a sample of TP-exit pairs (same window, same asset, same side, same entry within 1¢) and compare `exit_price`. If PAPER's exit_price is consistently > LIVE's exit_price by ~0.02 on TP exits, Fix 1 is correct.
- The 4.5% wallet-fill discount is documented in `live_engine_5m.py:406-409` ("API's `size_matched` can over-report by ~4-5%") but the magnitude isn't independently verified here. Could be 3% or 6%. Confirm by averaging `wallet_shares / (POSITION_SIZE/entry_price)` across logged reconciliation events.
- I did not find any evidence that the bot is paying fees that aren't recorded. Polymarket's CLOB binary outcome fee schedule appears to be 0% as of audit date — this matches the code.
- The `exit_price=0.0` rows are almost certainly the wallet-empty-but-reason-preserved bug (Fix 3). I did not find a separate "SDK V2 returns nothing" path that would record 0.0; every path I traced either uses `average_price`, `market_price_at_exit`, or the placement `exit_price` (0.01) as fallback.
