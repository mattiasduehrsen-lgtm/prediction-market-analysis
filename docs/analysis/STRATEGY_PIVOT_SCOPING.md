# Strategy Pivot Scoping (Option C)

**Created:** 2026-05-10 (alongside v1.30)
**Purpose:** Identify alternative strategies worth investigating, given what the v1.28 corrections revealed about the current MR-15m approach.

---

## What we know now (the brutal honest baseline)

After v1.28's accounting corrections to n=693 historical MR-15m PAPER trades:

| Segment | n | Corrected EV | Status |
|---|---|---|---|
| BTC UP | 194 | -$1.05 | off LIVE |
| BTC DOWN | 135 | -$2.16 | off LIVE |
| ETH UP | 145 | -$0.43 | off LIVE |
| ETH DOWN | 123 | -$0.49 | off LIVE |
| **SOL UP** | **74** | **+$0.53** | LIVE-eligible (only +EV segment, marginal) |
| SOL DOWN | 22 | -$4.45 | off LIVE |

**Win/loss asymmetry is structural across all segments.** Average TP win ≈ $7-9; average loss ≈ $9-11. The strategy needs ~57% WR to break even at corrected accounting. Few segments hit that consistently.

**No strategy variation we've tested clears costs at sub-100 trade samples.** ETH was the apparent thesis; turned out to be -EV. SOL UP is the only +EV remainder, and its 95% CI on +$0.53 is roughly [-$2, +$3] — wide enough that it could be noise.

The first-principles question: **why would 15-minute prediction-market mean reversion on Polymarket have an edge in the first place?** The original hypothesis was something like "amateurs pile into one side at window open, smart money waits for reversion." If that hypothesis is false in current markets — or if the edge is too small to clear the structural -$1/win haircut — then no amount of filter tuning will make MR-15m profitable.

---

## Pivot directions worth investigating

### 1. Longer-horizon markets (1h, 4h, 1d Polymarket "Up/Down" markets)

**Hypothesis:** 15m markets are too short for mean reversion to play out. Real moves happen on hourly+ timescales. Longer horizons mean lower transaction-cost-as-pct-of-edge.

**What to test on existing data:**
- Does Polymarket offer 1h/4h/1d versions of Up/Down on the same assets? (Unknown — needs market discovery)
- If yes: pull the same kind of data on those markets and see if the cheap-side reversion holds. Use the same `is_live` infrastructure for PAPER vs LIVE separation.

**Effort:** Medium. Discover available markets → add to `markets.py` discovery → reuse most of the existing engine.

**Risk:** Moderate. Could be the same coin-flip dynamics as 15m. But the math on transaction costs is friendlier on longer holds.

**Why this is appealing:** the v1.28 correction was a structural finding (PAPER over-stated TP fills by $2/win). On longer markets with bigger TP/SL ranges, the per-trade slippage is similar in absolute terms but smaller as a % of pnl. So edge becomes more capturable.

### 2. Different asset class — single-asset prediction markets (politics, sports, etc.)

**Hypothesis:** Crypto markets are crowded. Polymarket's politics/sports markets are less efficient because they attract less HFT interest.

**What to test:**
- Does the cheap-side mean-reversion signal hold on politics or sports markets too? Or is it just a crypto-momentum-fading thing?
- These markets have very different microstructure (longer settlement, less liquid, different participants).

**Effort:** High. Need new market discovery, new feature engineering, new evaluation.

**Risk:** High. We have zero domain knowledge here. The 15m strategy was at least tied to a specific market mechanic (binary outcome + time decay). Politics has none of that structure.

**Why this is appealing:** if there's an edge, it's likely bigger than crypto markets. But the data-collection burden is large.

### 3. Microstructure features → ML

**Hypothesis:** the existing data has signal, we just haven't surfaced it. Specifically:
- `cheap_side_velocity` (price drift in the 30s before entry) — never tested as a filter
- `clob_trades_60s` (order flow intensity) — captured but not used
- Order book depth asymmetry at entry — not captured
- `secs_into_window` interaction with `cw_pct` — not modeled

**What to test:**
- Build a feature matrix from the existing 1686-trade PAPER history
- Train a logistic regression or gradient-boosted classifier on `pnl > 0` (or directly on pnl)
- See if predicted-positive trades have better WR/EV than the unfiltered baseline
- Honest validation: out-of-sample on the most recent ~200 trades

**Effort:** Medium-low. We have all the data; need a few hours of analysis.

**Risk:** Low. If ML can't find signal, that's also informative — it tells us the strategy is fundamentally noise.

**Why this is appealing:** 1686 trades is enough to fit a small classifier. If there's a feature interaction we missed, ML will find it. If there isn't, we know to pivot away from MR-15m entirely.

**This is probably the highest-information-per-effort step.**

### 4. Pure infrastructure pivot — be a market maker on Polymarket binaries

**Hypothesis:** instead of taking directional bets, post bid-ask quotes and earn the spread. Polymarket has 0% maker fees (we verified). If you post both sides at fair value, you collect spread on every fill.

**What to test:**
- What's the typical spread on these binary markets in the [0.30, 0.70] zone?
- Could we post 100-share quotes at bid+0.01 and ask-0.01 and get filled?
- Risk model: when do positions become directional (e.g. one side fills more than the other)?

**Effort:** Very high. This is a different bot entirely. Order management, inventory management, auto-quoting.

**Risk:** Very high. Adverse selection — informed traders pick off our quotes when news hits.

**Why this is appealing:** classic positive-EV strategy if we can manage inventory. But it's a multi-month project, not a "next step."

### 5. Accept the bot as a research apparatus — stop trying to make it profitable

**Hypothesis:** We learned something valuable: a naive MR-15m strategy on crypto prediction markets does not have positive edge for retail at $5-15 size. That IS a finding.

**What to test:** Nothing. Document the lessons, archive the bot, move on.

**Effort:** Low.

**Risk:** Low (no money at risk).

**Why this is appealing:** it's the honest answer if none of options 1-4 pan out. And we've spent enough time tuning a hypothesis that may just not have been viable to begin with.

---

## Recommended sequence

1. **Run option 3 first (ML on existing data) — 1-2 hours of work.** This is cheap and tells us whether the strategy has any unfiltered signal we missed. If ML finds a +EV subset, that's the new filter. If not, we know to pivot harder.

2. **In parallel, let v1.30 collect SOL data on the wider band for 2-4 weeks.** Cost is zero. By the time we make a real LIVE decision, we'll have ~60-100 SOL UP trades on the wider band with v1.28 accounting. That's a clean dataset.

3. **If both 1 and 2 are negative, escalate to option 1 (1h/4h Polymarket markets).** This is the lowest-risk genuine strategy pivot — same engine, same UP/DOWN mechanic, just different timescale.

4. **Defer options 2 and 4** indefinitely. They're high-effort with uncertain return.

5. **If options 1, 3 all turn up nothing**, accept option 5 as the answer.

---

## What I'd run NEXT, concretely

**ML feature exploration** on the existing 1686-trade PAPER history. Specifically:

- Apply v1.28 corrections to all historical pnl (already scripted in `analyze_v1_28_retro.py`)
- Build feature matrix from columns already in trades.csv:
  `entry_price, secs_remaining_at_entry, btc_pct_change_at_entry, cross_window_pct, liquidity, spread_at_entry, price_60s_before_entry, price_30s_before_entry, price_velocity, asset, side, hour_of_day_utc`
- Target: `pnl_corrected > 0`
- Method: gradient-boosted classifier (sklearn) with 5-fold time-series cross-validation
- Output: feature importance ranking + predicted-positive precision/recall/EV vs baseline

This is a few hours of work, no LIVE risk, and either:
- Validates the bot has signal we missed (rebuild filters around top features), OR
- Confirms the strategy is structurally noise (pivot to option 1 or option 5)

---

## What this scoping doc is NOT

- A commitment to do any of these. It's a menu.
- A claim that any of options 1-4 will work. They're hypotheses.
- An argument against the current MR-15m strategy. v1.30 is still running. SOL UP at +$0.53 is still the active LIVE thesis. We can pursue both pivot research AND continued data collection — they don't conflict.
