# Microstructure-Driven Per-Trade Decision — Experiment Scope

**Created:** 2026-05-13
**Hypothesis:** Retail Polymarket Up/Down bots that DO make money use rich microstructure features at decision time — order book depth, CLOB trade flow, cross-market deltas, counterparty inference — not the static-filter cascades we've been tuning.

**Prior research found a null on 17 entry-time features.** Those features were all summary-level (asset, side, entry_price, time_of_day, recent_wr, etc.). The microstructure layer was never captured. This experiment closes that gap.

**Probability of finding real edge: ~25-35%.** Not high, but the work is reusable for correlation arb / market making if MR turns out null.

---

## Three-phase plan, ~2-3 weeks

### Phase 1 — Feature capture (~1 week, no LIVE risk)

Build `src/bot/microstructure.py`. At every entry candidate, snapshot:

| Group | Features |
|---|---|
| **Order book** | Top-5 bid/ask depth on UP and DOWN tokens (10 numbers); midpoint; spread; book imbalance (bid_volume / (bid_volume + ask_volume)) |
| **CLOB flow** | Trades in last 10s/30s/60s: count, total volume, buy/sell ratio, largest single fill, time-since-last-fill |
| **Spread dynamics** | Spread now vs 30s ago vs 60s ago (widening / tightening) |
| **Cross-market** | BTC/ETH/SOL Binance % move in last 10s/30s/60s/300s; correlation sign with our asset; relative-strength signals |
| **Token-level** | Last 20 fills on each token: avg price, std, momentum, whale-presence flag (any single fill > $50) |
| **Realized vol** | Std of midpoint over last 30/60/180s; volatility regime (high/normal/low) per asset |

Write to `output/5m_trading/microstructure_features.csv` keyed by `position_id`. **No bot decision changes** in this phase — pure observation.

### Phase 2 — Validation (~1 week of running)

Run PAPER for 5-7 days. Should accumulate 100-200 entries with full feature snapshots.

Then run analysis:
1. Apply v1.28 corrections to pnl
2. Train gradient-boosted classifier on `pnl_corrected > 0` with the new ~30-50 features (vs. old 17)
3. 5-fold time-series CV (same methodology as `analysis_opus_ml.py`)
4. Check forward-EV by predicted probability bucket
5. Honest binary verdict: AUC > 0.55 + monotone EV gradient = real signal. AUC ~0.50 = null, pivot.

### Phase 3 — If signal exists (~1 week, conditional)

Build live decision logic. Options:
- (a) Deploy the classifier in production: every entry candidate gets a model score, only enter if score > threshold
- (b) Translate top features into rule-based filters (more interpretable, but loses subtlety)
- (c) Feed features to the brain (Claude) for per-trade reasoning — but only if (a) clearly works first

A/B test on PAPER for 50+ trades before any LIVE change.

### Phase 3 fallback — If null

Don't tune. **Accept that 15m crypto MR is dead** and pivot to correlation arb (next session, ~2 weeks). The microstructure capture infrastructure carries over directly.

---

## Implementation details

### Files

- **New:** `src/bot/microstructure.py` — single `Snapshot` dataclass + `capture(market, clob_feed, binance_feed, ...)` function
- **Modify:** `main.py` line ~895 (just before `should_enter` call): call snapshot, store in local variable, write to CSV when entry actually fires
- **New:** `output/5m_trading/microstructure_features.csv` — append-only, position_id keyed
- **New:** `analysis/ml_microstructure.py` — Phase 2 evaluation script

### Cost / risk

- Feature capture cost: ~5-10ms per entry candidate (book read + math). Negligible.
- No new API calls — `clob_feed` already streams the book; `binance_feed` already streams prices. Just consume what's there.
- No LIVE behavior change in Phase 1. LIVE keeps trading on the v1.34 WR filter while we collect data.

### Pre-conditions to start

None — all infra (CLOB websocket, Binance feed, clob_feed.recent_fills, market_store) already exists. We just plumb it.

### What "win" looks like

Phase 2 returns AUC ≥ 0.58 with a monotone EV-by-decile gradient. Predicted-positive trades have EV ≥ +$0.50/trade. Lift over baseline ≥ $1.00/trade. That's a real edge worth deploying.

### What "loss" looks like

AUC < 0.55, flat or inverted EV gradient. Then microstructure features are not the missing piece. Pivot to correlation arb without further MR tuning.

---

## Why this is the right next experiment

We've been honest:
- Static filters: dead. n=700 confirms.
- LLM reasoning over same features: marginal. Brain replay confirmed.
- ML over same features: null. AUC 0.496 confirmed.
- **Untested:** richer features that are observable but never fed into the decision.

This closes the last reasonable hypothesis for MR-15m specifically. If it fails, we move on with conviction. If it works, we have a money-printer. Either outcome is decisive.

Effort: 2-3 weeks. Code reuses ~80% of existing infrastructure. Worst case, the microstructure capture itself becomes the foundation for correlation arb / market making.
