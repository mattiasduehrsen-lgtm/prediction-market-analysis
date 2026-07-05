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

## Re-validation with fresh data (2026-05-15 evening, post-catch-up)

After realizing our scrape was stuck at March 20 due to a 500k-market cap in
`build_clob_index.py`, we re-ran the full pipeline on the laptop. Data now
ends 2026-05-15 (today). New numbers:

| Metric | Before catch-up | After catch-up |
|---|---|---|
| Markets scraped | 14,316 | **32,610** |
| Trades indexed | 1,576,278 | **4,200,152** |
| Active losing CS2 wallets | 481 | **1,817** |
| OOS fade-bottom-1000 ROI | +110% | **+133%** (164k trades) |
| OOS copy-top-10 ROI | +57% | **+255%** (9.5k trades) |

Top fade target by realized loss: `0x47138dc1…` with **119,830 trades** at
**-$67,612 PnL** (-11.3% ROI). This is the wallet that we've been observing
heavily fading NAVI in tonight's live matches.

**fade_targets.json now has top-500 active losers** (vs 481 before). Bot
hot-reloaded the new set automatically via mtime check — no restart needed.

The strategy edge grew, not shrank, with more data. Confidence is much higher.

## Production state (2026-05-15)

Bot runs 24/7 on the laptop (`PolyBotEsports`). Dev PC is no longer required
for any part of the production loop:

| Task | Schedule | What it does |
|---|---|---|
| `PolyBotEsports` | continuous (watchdog) | Polls Polymarket, logs fade signals |
| `PolyBotEsportsEval` | every 30 min | Re-computes realized PnL → dashboard |
| `PolyBotEsportsRefresh` | every 4 hours | Re-scrapes new markets, regenerates `fade_targets.json`; bot hot-reloads |

Dashboard tab `🎮 Esports Fade` (separate from the 15m crypto bot) shows
signals, PnL, recent fades, bot log tail.

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

---

## Live operation log

### 2026-05-15 → 2026-05-19 (Phase 2 LIVE micro: $5/trade, observation)

**Cumulative through 2026-05-19 23:00 UTC:**
- 78 resolved trades, 57.7% WR, +$8.80 PnL on $389 cost = +2.3% ROI
- FADE: 58 trades, 60.3% WR, +$15.62 = +5.4% ROI ✅
- FOLLOW: 20 trades, 50% WR, -$6.83 = -6.8% ROI ⚠️ (watch)
- Cancel rate: 41% (acting as quality filter, matches backtest assumption)
- Entry-price bucket analysis revealed $0.20-0.40 was 0/10 WR, -$50 — single biggest drag

**Key config changes 2026-05-18 → 2026-05-19:**

| Date | Change | Reason |
|---|---|---|
| 2026-05-18 | Entry-price floor: skip if `our_entry < $0.40` (LIVE only) | 0/10 WR in that bucket = pure -$5 drain. PAPER continues unfiltered for ongoing validation. |
| 2026-05-18 | Daily cap: $150 RISK → $150 LOSS | Bot was halting at $150 placed-bet count even on winning days. LOSS cap = halt only on actual realized -$150. RISK cap kept as $500 backstop. |
| 2026-05-18 | `MAX_PER_MARKET_USD`: $10 → $25 | Capture consensus-signal stacking — when multiple wallets fade same market, all fills get placed. |
| 2026-05-18 | `MAX_FADES_PER_DAY`: 100 → 500 | Non-binding sanity ceiling — was never going to fire at $5/trade. |
| **2026-05-19** | **`LIVE_BET_USD`: $5 → $10** | **First scaling step. PAPER stays at $5 for backtest continuity.** |
| **2026-05-19** | **`MAX_PER_MARKET_USD`: $25 → $50** | Preserve 5-fill stacking at the new $10 bet size. |

### Infrastructure changes 2026-05-19
- All 4 scheduled tasks (PolyBotPaper, PolyBot, PolyDashboard, PolyBotEsports) converted from
  "Interactive only" → "Run whether user is logged on or not" via `schtasks /change /ru MSI\matti /rp <pw>`.
  Root cause: laptop logoff/sleep on 2026-05-17 killed all 4 tasks for ~48h. Tasks now survive
  logoff, sleep, reboot — anything short of laptop power-off.
- pUSD balance bug in `analysis/fresh_analysis.py` fixed. Was querying old USDC.e contract
  (`0x2791...`) which returns $0 since Polymarket migrated to pUSD before April 28. Now uses
  CLOB SDK's `get_balance_allowance(COLLATERAL)` which is the authoritative path. All previous
  "$0 USDC" reports during May were spurious — actual cash was always sitting in pUSD.

### Open questions going into the next checkpoint (~n=100 resolved)

1. Is the FADE/FOLLOW gap real or variance? Decide on FOLLOW cut at n=30+ for FOLLOW.
2. Does slippage stay under 2¢ at $10/trade? If yes → headroom to $20.
3. Does cancel rate hold under 50% at $10/trade? If yes → book depth not yet a problem.
4. Does the entry-price filter prevent the $0.20-0.40 bleed from recurring on PAPER? (PAPER
   should continue to show losses in that bucket as a validation that the filter is right.)

### Current bot constants (esports_fade_bot.py)

| Constant | Value | Notes |
|---|---|---|
| `PAPER_BET_USD` | $5 | Held at $5 for backtest continuity |
| `LIVE_BET_USD` | $10 | Raised from $5 on 2026-05-19 |
| `LIVE_MIN_OUR_ENTRY` | $0.40 | Entry-price floor (LIVE only) |
| `DAILY_LOSS_CAP` | $150 | Primary stop (realized PnL) |
| `DAILY_RISK_CAP_USD` | $500 | Safety backstop only |
| `MAX_PER_MARKET_USD` | $50 | Up to 5 stacked fills per (market, outcome) |
| `MAX_FADES_PER_DAY` | 500 | Sanity ceiling |
| `POLL_INTERVAL` | 2.0s | Polymarket data-api polling cadence |
| `ENTRY_SLIPPAGE` | $0.01 | +1¢ buffer on BUY (v1.9 pattern) |

---

## v1.54 TURNAROUND (2026-07-01) — historical

**The table above is historical.** War-room analysis found the fade-everything
config at **−1.5% realized** on 567 fills; the entire loss was one high-frequency
wallet plus spread costs on unfiltered fades. The strategy became:

1. **Model-edge gate (primary):** a fade fires ONLY if the v2 gradient-boosted
   win-prob model (`esports_model/`) rates our side underpriced by
   `MODEL_FILTER_MIN_EDGE = 0.10` (validated +20.6% ROI @3¢ friction, monotonic
   dose-response, triple-confirmed incl. live shadow A/B). Elo is fallback only.
2. **Entry floor lowered to 0.10** — model-confirmed cheap entries were the only
   profitable segment (+17.8%); the old 0.40/0.20 floor blocked the edge.
3. **Toxic-wallet filter:** targets we've faded ≥20× at a net loss are auto-excluded
   (self-maintaining from `live_results.csv`).
4. **Quarter-Kelly sizing** implemented but **OFF** (`KELLY_ENABLED=0`) until the
   gate shows positive ROI on its first ~50 live fills. Flat $15 until then.
5. **Price-capture logger** (`price_capture.py`, task `PriceCapture`) logs bid/ask/
   depth for all near-start esports markets → unblocks prop/arb/LoL backtests.

Full analysis: `COWORK_WARROOM_RESULTS_2026-07-01.md`. History: `PATCH_HISTORY.md`.

---

## v1.59 R1 PAPER VALIDATION (2026-07-05) — CURRENT STATE

**LIVE is PAUSED** (`output/esports_fade/paused.flag`, set at v1.58) and stays
paused. The v1.54/v1.57 gate went **1–8 (−$83)** post-v1.57; GRID-era realized is
**−$141.29 on 44 fills**. The live calibration referee (117 resolved shadow
signals) shows market Brier .222 < Elo .246 < v2 .258 — raw v2's dose-response is
inverted on the GRID-era population: the bigger its claimed edge, the more wrong
it is. Full adjudication: `COWORK_GRID_REFIT_RESULTS_2026-07-05.md`.

What runs now:

1. **R1 recalibrated PAPER gate** (`_r1_paper_gate`, `esports_fade_bot.py`) — the
   one lever with positive out-of-sample direction (+16–32% ROI fill-true on July
   captured asks; n≈21–24, not significant). Prices every CS2 series fade signal
   through a **frozen** calibration table, paper-bets iff
   `p_r1 − best_ask ≥ 0.05`, `0.20 < ask < 0.95`, depth ≥ $10, tier known & non-S,
   max 1 gated entry per match per day. Output: `r1_paper_trades.csv` +
   `r1_eval`/`r1_paper_bet` events. Never places orders.
2. **Pre-registered triggers** (frozen 2026-07-05, do not re-derive):
   - **GO-LIVE**: ≥150 resolved R1 bets AND ROI > +10% AND price-matched excess
     P(≤0) < 0.05 → first read ~early August.
   - **KILL R1**: any n ≥ 60 with running ROI < −10%.
   - **Health**: rolling 200-signal Brier of `p_r1` vs market; drift >.02 worse →
     refit = new pre-registration, clock restarts.
3. **LoL is observe-only again** (`LOL_OBSERVE_ONLY` defaults 1) — failed both the
   July Brier eval and the fill-true sim (−12.6%).
4. **Props are banned permanently** (v1.58 regex): every prop class ran −9%..−61%
   at executable quotes, both sides. The spread *is* the market maker's model.
5. **In-play stays paper**: pre-registered test (run 2026-07-05) at contrarian
   n=51, p=0.22 — undersampled; re-run once at n≥100. No peeking.
6. **Weekly hygiene during accumulation**: model-state + tier-index refresh
   (13 GRID-era teams missing from model state), maker/taker tagging accrues
   toward the ~100-fill adverse-selection read.
