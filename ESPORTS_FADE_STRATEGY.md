# Esports Fade-Bottom-Whale Strategy

**Status:** PAPER validation phase (launched 2026-05-15)
**Owner:** Mattias
**Expected edge:** +110% ROI on $5 bets, CS2 markets only, ~hundreds of fade signals per day

## First-day realized result (2026-05-15)

After ~9h of PAPER on this dev PC:
- **189 fade signals** logged
- **20 resolved**: 8 wins / 12 losses (40% WR), **+$121.18 PnL on $100 bet → +121% ROI**
- 169 still open (mostly today's NAVI vs Vitality CS2 series)
- Re-run with `python analysis\evaluate_paper.py`

This is a tiny sample but **points within the +110% backtest band on first contact with live data**. Continuing PAPER collection.

---

## TL;DR

Polymarket has a consistent population of CS2 esports traders who lose persistently. We can identify them from public on-chain history and bet the **opposite** side of every trade they place. Out-of-sample backtest on 30% of held-out 2025–2026 trade data shows **+110% ROI** at $5/bet, **stable across three chronological quarters (+95% / +131% / +114%)**.

This is unrelated to the existing 15m crypto Up/Down bot — different markets (CS2 esports), different signal (wallet-imitation fade), different process.

---

## How we got here

1. **Universe:** 14,316 esports markets / 28,548 outcome tokens scraped from Polymarket CLOB. CS2 dominates (13,376 markets).
2. **Trade history:** 1,576,278 resolved trades scraped from `data-api.polymarket.com/trades` via per-market pagination. 13,261 of 14,316 markets had a winning outcome → ~92% resolution rate.
3. **Ranking:** wallets grouped, PnL computed with realistic price clipping `[0.05, 0.95]` (sub-cent fills don't exist in reality).
4. **OOS backtest** (`analysis/backtest_oos.py`): chronological 70/30 split. Ranked wallets on TRAIN only, evaluated copy-top and fade-bottom strategies on TEST.
   - Copy TOP-10: +57% ROI
   - **Fade BOTTOM-1000: +110% ROI** ← chosen
5. **Stability check** (`analysis/validate_fade_signal.py`):
   - Test set Q1 / Q2 / Q3 chronological: **+95% / +131% / +114%** ROI
   - Active-wallets-only (traded in last 30d of train): +110%
   - CS2 only: +110%
   - Most recent 10% of test: +95%
6. **Active targets** (`analysis/identify_active_targets.py`): filtered bottom-1000 to wallets that (a) traded in the last 14 days of available data, (b) have ≥30 CS2 trades, (c) ROI < -5%. **Result: 481 active losing CS2 wallets** in `cowork_snapshot/esports/fade_targets.json`. Worst target: 7,055 trades at -17% ROI — a true grinder.

## Why this works (hypothesis)

CS2 markets attract emotionally-attached bettors (favorite team fans, scene insiders with biased models) who systematically misprice. The losing tail is **fat and persistent** — these are not one-off bad days, they are recurring bettors who keep funding the market. Polymarket fees + slippage are smaller than the edge they bleed.

---

## Live bot: `esports_fade_bot.py`

- Polls `data-api.polymarket.com/trades?limit=500` every 2s.
- Filters to: target wallet AND CS2 slug AND size ≥ $1 AND price ∈ [0.05, 0.95].
- Fade rule:
  - target BUY Yes @ p → we BUY No @ 1 − p
  - target BUY No @ p → we BUY Yes @ 1 − p
  - target SELL X @ p → we BUY X @ 1 − p (we take the side they're exiting)
- Writes every signal to `output/esports_fade/paper_trades.csv` + `fade_events.jsonl`.
- LIVE order placement intentionally **not yet implemented** (Phase 2).

## Risk caps (already wired)

- `PAPER_BET_USD = $5`, `LIVE_BET_USD = $5`
- `DAILY_LOSS_CAP = $50` → auto-halts new entries until UTC midnight
- Dedup by `transactionHash` (10k LRU)
- CS2-only filter (signal validated only there)
- Price gate 0.05–0.95 (avoids dust + near-resolved)

## Risk caps still needed before LIVE

- Per-market exposure cap (don't pile 10 fades into one CS2 match if multiple targets trade it).
- Per-day fade-count cap.
- Wallet allow-list refresh (re-run `identify_active_targets.py` weekly).
- CLOB order placement + status polling + matched-size handling (mirror v1.10/v1.11 fixes from the 15m bot).
- Token-id mapping (we have `conditionId` and `outcome` — need to resolve the token_id for the side we want to buy).

## Phase plan

| Phase | Goal | Exit criteria |
|---|---|---|
| **1. PAPER (now)** | Confirm signal density and per-trade economics match backtest | ≥200 PAPER fade signals collected; observed ROI within ±30% of +110%; signal frequency ≥20/day |
| **2. LIVE micro** | Implement CLOB order placement; $5/trade; $50/day loss cap | Two weeks live with positive ROI; no infrastructure breakage |
| **3. Scale** | If Phase 2 holds, raise bet size and add LoL/Valorant if validated separately | Discussed before any scale-up |

## Files added this work-stream

- `analysis/build_clob_index.py` — pull every Polymarket market via CLOB pagination
- `analysis/scrape_esports_trades.py` — resumable per-market trades scraper (1.57M trades)
- `analysis/resolve_outcomes.py` — winner extraction (no API calls; index already has it)
- `analysis/rank_wallets.py` — per-wallet PnL aggregation
- `analysis/backtest_oos.py` — chronological OOS backtest
- `analysis/validate_fade_signal.py` — temporal/per-game stability tests
- `analysis/identify_active_targets.py` — produces `fade_targets.json`
- `esports_fade_bot.py` — live PAPER fade monitor

## Data artifacts (untracked, regenerable)

- `cowork_snapshot/esports/clob_esports_markets.parquet`
- `cowork_snapshot/esports/scrape/shards/*.parquet` (281 files)
- `cowork_snapshot/esports/resolutions.parquet`
- `cowork_snapshot/esports/fade_targets.json` ← consumed by the bot

## Things that could kill the strategy

1. **The 481 targets quit Polymarket** — partial mitigation: weekly target refresh. If the losing pool dries up structurally, the edge dies.
2. **Polymarket changes fee structure** — current backtest assumes maker/taker fees are negligible; needs verification.
3. **Order timing** — the backtest assumed instant fill at `1 − their_price`. Real CLOB will have spread/depth. Phase 2 will measure this.
4. **CS2 market liquidity** — many CS2 markets are thin. Real fills may slip materially vs the historical print prices. Phase 1 PAPER will not catch this; only LIVE will.
5. **Signal decay** — every other person reading on-chain data could discover the same pattern. The 481 wallets may stop trading or change behavior.

## Path from PAPER → LIVE

1. Let PAPER run ≥7 days, accumulate ≥200 signals.
2. Sanity-check: do PAPER ROI and fade-frequency line up with backtest?
3. Implement CLOB order placement in `esports_fade_bot.py` (mirror `src/bot/polymarket_executor.py` patterns from the 15m bot: +1¢ slippage on entry BUYs, lowercase status checks, `floor(wallet_balance, 2)` on exits).
4. Token-id resolution: for each `(conditionId, our_outcome)`, look up the corresponding `token_id` from `clob_esports_markets.parquet`.
5. Deploy under a new `PolyBotEsports` scheduled task on the laptop with its own watchdog. **Do not** entangle with `PolyBot` / `PolyBotPaper` lifecycle.
6. Start with $5/trade, $50/day loss cap. Re-evaluate after 2 weeks.
