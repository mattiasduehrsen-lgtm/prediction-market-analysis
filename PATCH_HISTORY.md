# Patch History

---

## v1.51 — 2026-06-22
**LoL readiness hardening — 100% ready to capture League the moment GRID lists markets, zero manual steps.**

Five pre-emptive fixes against every way we'd otherwise miss the opening:

1. **Periodic token-index reload** (`maybe_reload_token_index`, called from the main
   loop). The bot built `token_index` **once at startup** and went blind to markets
   created afterward — a 3-day-old process had missed ~1,400 tokens, and the on-chain
   listener silently drops trades on unknown tokens. Now it hot-reloads the parquet on
   mtime change → new CS2/LoL markets detected **without a restart**. The #1 miss-risk.
2. **`build_clob_index` LoL patterns widened** (`lol-`, `arch-lol-`) so GRID-era
   head-to-head slugs (e.g. `lol-t1-geng-2026`) get indexed. Valorant unaffected.
3. **`identify_active_targets` game classifier** maps all LoL slug variants
   (`lol-`/`arch-lol-`/`league-of-legends`/`-lol-`) → `league` (Valorant excluded), so
   LoL bettors are captured regardless of GRID's slug format. Was `slug.split('-')[0]`,
   which mislabeled `lol-`/`arch-` markets and excluded those bettors.
4. **Model routing** (`_model_for_slug` + `lol_model.maybe_reload()`): the live model
   filter routes CS2→`cs2_model`, LoL→`lol_model`. **CS2 behaviour identical.** Makes a
   LoL go-live a clean `LOL_OBSERVE_ONLY` flip (still OFF).
5. **LoL Elo daily refresh** (`run_lol_elo_refresh.bat` + `LoLEloRefresh` task) keeps
   `lol_*.parquet` current; the bot hot-reloads it.

Verified: routing, index patterns, and target classifier all correct; CS2 path unchanged.

### Files
- `esports_fade_bot.py`, `analysis/build_clob_index.py`,
  `analysis/identify_active_targets.py`, `run_lol_elo_refresh.bat`, `src/bot/version.py`.

---

## v1.50 — 2026-06-19
**LoL observe-only paper wiring (no real money on League).**

### Context
Built a validated **LoL Elo model** (65.5% accuracy, Brier 0.215, excellent
calibration, 20,878 matches / 1,034 teams) by parameterizing the CS2 pipeline by
game. The LoL audit showed the model + matching are ready (top teams match 100%,
235/294 historical H2H markets matchable), but two questions remain open: live
model edge, and **order-book liquidity** (the mirage that killed CS2 pre-match) —
plus LoL H2H markets are sparse/minor-team-skewed. So: observe, don't bet.

### What this adds (all paper / zero risk)
- `self.lol_model = CS2Model(game="lol")` loaded alongside the CS2 model.
- `_is_lol_slug()` — detects LoL, **excludes Valorant VCT** (slugs contain
  "league" — the contamination the audit found).
- `process_trade` routes LoL slugs to `_observe_lol()`: prices via the LoL model,
  logs **live order-book depth** (`_clob_book`), writes
  `output/esports_fade/lol_observations.csv` + a `lol_observation` event, then
  **returns without placing**. CS2/CSGO live path is unchanged.
- On-chain gate (`_load_cs2_windows`) now opens during **LoL** match windows too
  (Valorant excluded) so the listener actually detects LoL trades.
- `ESPORTS_PREFIXES` + heartbeat `lol_obs=` counter.

### Still OFF
`LOL_OBSERVE_ONLY = True` — no LIVE LoL orders. Flip only after the observations
show a real, fillable edge.

### Files
- `esports_fade_bot.py`, `src/bot/version.py`.

---

## v1.49 — 2026-06-18
**Fade-of-SELL mispricing — 4th blocker (orders placed but never filled).**

### Why
After v1.47/v1.48 the bot finally *placed* orders again — but all 3 came back
`canceled, shares=0`. We bid **Vitality @ 0.30 for a token trading at ~0.70**, so
the order rested far below market and timed out. Root cause: when fading a target's
**SELL** we correctly buy the *same* outcome they sold, but `our_entry` was
`1 - their_price` for **both** branches. For the SELL branch that's the *complement*
price. Target sold Vitality @0.705 → we bid `1-0.705 = 0.295` for Vitality.

It also **corrupted the model edge**: `model_p(Vitality)=0.66` vs the bogus `0.295`
entry = fake **+0.37** edge that passed the filter. With the correct `0.705` entry
the edge is ~−0.04 → correctly *rejected*.

### Fix
Fade-SELL branch: `our_entry = their_price` (the bought outcome's own price).
Fade-BUY unchanged (`1 - their_price` is correct there — we buy the other side).

### Effect
- Fade-of-SELL orders now price at market → **can fill**.
- The model filter sees the **true** edge → only real-edge fades trade (so some
  phantom-edge fade-SELLs that used to "pass" will now correctly be skipped).

### Files
- `esports_fade_bot.py` — move `our_entry` into each fade branch; SELL → `their_price`.
- `src/bot/version.py` — v1.49.

---

## v1.48 — 2026-06-18
**Phantom-exposure fix — the 3rd blocker behind 2 days of zero trades.**

### Why
`market_exposure` — read by both the **per-market $ cap** (`MAX_PER_MARKET_USD`)
and the **opposite-side hedge guard** — was incremented at **signal time** in
`process_trade`, before the order was placed/confirmed. Any signal that was then
floored, errored, or never filled left **fake exposure** on that `(market,outcome)`.
That phantom $ then blocked the entire market: furia-9z showed **$45 exposure +
opposite-side block with ZERO real orders** (verified: cid absent from both
`live_orders.jsonl` and `live_results.csv`).

### Fix
- LIVE: `market_exposure` is incremented **only on a confirmed matched fill**
  inside `place_live_order` (by actual matched `cost`).
- PAPER: unchanged (still counts every simulated fade at signal time).
- A restart also clears the stranded phantom (rebuild from `live_orders.jsonl` = $0).

Now the cap + hedge guard gate on **real positions**, so unfilled/failed attempts
can't self-block a market.

### Known related (not changed — smaller, separate)
The per-wallet daily-fade counter (`fades_by_wallet_today`, `MAX_FADES_PER_WALLET_PER_DAY`)
still counts *attempts* not fills. Left for a focused follow-up.

### Files
- `esports_fade_bot.py` — guard signal-time increment with `if not self.live`;
  add fill-time increment in `place_live_order`.
- `src/bot/version.py` — v1.48.

Combined with v1.47 (model name-collision + floor 0.40→0.20), this clears all
three identified blockers.

---

## v1.47 — 2026-06-18
**Two fixes after 48h of ZERO live orders despite 1066 target signals.**

### Diagnosis
`_why_no_trades.py` over 48h: 1066 signals, **0 orders**. Top skip reasons —
`skip_single_map` 321 (deliberate), `skip_debounce` 284 (deliberate),
**`skip_model_unmatched` 253**, `skip_model_filter` 63 (filter working),
`model_filter_pass`/`fade_signal` **10** → but **`skip_entry_price_floor` 10**
killed every one. Two fixable blockers.

### Fix 1 — CS2 model name-collision bug
`name_to_id` was built first-writer-wins, so when two teams normalize to the same
key (`Team Falcons` [308 games] and a minor `Falcons` [7 games] both → `falcons`)
the **low-games minor team often claimed the name** → `predict()` returned
`low_games` → every real matchup against that team was wrongly skipped. This blocked
**238 series-moneyline fades across 5 matchups** (vit-fal2 ×89, tdk-nem ×116,
sparta-inox ×10, …). Fix: `CS2Model._register()` resolves collisions by **preferring
the higher-games team** (the established roster = the intended team). Verified
Vitality/Falcons, TDK/Nemiga, Sparta/Inox now evaluate `ok=True`. Affects all three
model-using bots (esports live filter, cs2_model, cs2_inplay).

### Fix 2 — entry-price floor 0.40 → 0.20
`LIVE_MIN_OUR_ENTRY` was 0.40 (from a 0/5-WR sample in [0.20,0.40) collected
*before* the v1.41 model filter existed). The model filter now screens every fade
for value, so 0.40 was redundantly blocking the strategy's best setups — **all 10
model-approved fades in 48h** were underdog buys at 0.25–0.39. Lowered to 0.20:
trust the model filter for the 0.20–0.40 band, keep only an extreme-longshot guard.
Daily loss/risk caps still bound downside.

### Files
- `cs2_model.py` — `_register()` collision resolver (prefer more games).
- `esports_fade_bot.py` — `LIVE_MIN_OUR_ENTRY` 0.40 → 0.20.
- `analysis/_why_no_trades.py` — new skip-reason diagnostic.
- `src/bot/version.py` — v1.47.

---

## v1.46 — 2026-06-17
**On-chain listener polls ONLY during live CS2 match windows (Alchemy CU fix #2, no trading-logic change).**

### Why
v1.45 slowed polling to 15s, but the bigger waste remained: we poll `eth_getLogs`
24/7 even though **most of the day has no live CS2 match**, so the target wallets'
on-chain activity in those hours is all non-esports and dropped anyway.

### What
- New gate `esports_fade_bot._onchain_gate()` passed to `OnChainListener(gate=...)`.
- Windows are built from `clob_esports_markets.parquet`. A **real** CS2 match
  market has a populated `game_start` (prop/futures markets like
  `will-cs2-market-cap-reach-6-billion-...` don't), so requiring `game_start`
  cleanly isolates matches. Window = `[game_start − 2h, game_start + 5h]`.
- When no window is open the listener makes **zero RPC calls** and re-checks every
  5 min (`POLL_INTERVAL_IDLE`). Window list cached, rebuilt ≤ every 5 min.
- Heartbeat shows `gate=active` or `gate=IDLE(no-cs2)`.

### Impact
Measured duty cycle across the live dataset = **~31% active**, so on-chain CU burn
drops ~3× (≈1M → ≈310K CU/day; 30M lasts ~3 months).

### Safety (why a gate bug can't cost money)
- Fails **OPEN** on any error or before the first successful load — never silently
  blinds detection.
- Generous buffers so pre-match bets and long Bo5s aren't missed.
- The **data-api poll still backstops** any window we misjudge (catches it slowly).
- Worst case of a gate bug = a *missed fade*, never a financial loss.
- Disable entirely via `ONCHAIN_GATE_ENABLED=0`.

### Files
- `onchain_listener.py` — `gate` param, `POLL_INTERVAL_IDLE`, idle path in `run()`.
- `esports_fade_bot.py` — `_load_cs2_windows()`, `_onchain_gate()`, gate wired in,
  `import os`, heartbeat `gate=` field, window constants.
- `src/bot/version.py` — v1.46.

---

## v1.45 — 2026-06-17
**On-chain listener `POLL_INTERVAL` 3s → 15s (CU-budget fix, no trading-logic change).**

### Why
The Alchemy RPC key hit its **30M CU spending cap in ~6 days**. The on-chain
listener polls `eth_getLogs` every 3s, 24/7 (2 getLogs + 1 blockNumber per poll
≈ 160 CU) ≈ **~5M CU/day**. Alchemy now returns `429 Too Many Requests`.

### Impact (before the fix)
The listener auto-rotated to its free public-RPC fallbacks (`conn=True`,
detections still climbing — **not blind**), but the public nodes are flaky:
frequent `Read timed out`, lag ~14s vs ~3s on Alchemy.

### Decision
The fade edge is currently ~0 (daily PnL $0, strategy under reconsideration), so
paying to raise the Alchemy cap isn't justified. Slowed polling to **15s** →
**~1M CU/day** so 30M lasts a full month, and cut the public-RPC thrash now.
Detection latency ~15s is still ~15× better than the ~220s data-api the on-chain
path replaced — a non-issue at a flat edge.

### Files
- `onchain_listener.py` — `POLL_INTERVAL = 15.0` (was `3.0`), comment updated.
- `src/bot/version.py` — v1.45.

### Not done (deliberate, one-change-at-a-time)
Bigger CU win: **gate polling to active CS2 match windows only** (we poll 24/7
even when no CS2 is live). Revert toward 3–5s if the edge proves real and the CU
budget is raised.

---

## v1.41 — 2026-06-02
**Elo model filter on the live fade bot (fade + model hybrid).**

### Why

Built a CS2 Elo model from PandaScore match history (57k matches). Backtest vs Polymarket prices:
- Model-only (bet when model disagrees with market by >0.10): **+13-19% ROI** out-of-sample, after 2¢ friction.
- **Fade + model** (fade only when the model also likes our side): **+30% ROI** (thr 0.10), **+42% (thr 0.15)** — beats model-only (+19%) and fade-only (+10%).

Why the combination wins: the fade signal tells us **when the model's edge is real**. When the model likes side Y *and* a known loser bet the other side, the edge is strong. When a loser is on the model's *own* side, the edge is weak — and those are exactly the bets the filter discards.

### What changed

`esports_fade_bot.py`:
- `MODEL_FILTER_ENABLED = True`, `MODEL_FILTER_MIN_EDGE = 0.10`.
- Loads `cs2_model.CS2Model` at startup.
- In `process_trade`, before a LIVE fade is placed: compute the model's probability for our fade side; place only if `model_prob(our side) − our_entry > 0.10`.
- CS2/CSGO markets where teams don't match, and non-CS2 (LoL) markets, are **skipped on LIVE** (logged: `skip_model_no_coverage` / `skip_model_unmatched` / `skip_model_filter`; passes logged as `model_filter_pass`).
- PAPER mode unaffected (logs all fades for data collection).
- Elo hot-reloaded hourly via the heartbeat (`cs2_model.maybe_reload()`).

### Effect

The live fade bot now bets only model-confirmed fades — the +30% backtested config — combining v1.40's ~2s on-chain detection with the Elo value check. Expect **much lower fade volume** (only CS2 matched markets where the model agrees), higher quality.

### Caveats

Backtest prices aren't guaranteed fills; team-matching misses some top teams (3DMAX, Falcons) which are then skipped. The standalone `cs2_model_bot.py` paper bot runs in parallel to validate the model + measure real order-book liquidity.

---

## v1.40 — 2026-05-29
**On-chain real-time signal source — the latency fix (data-api was ~220s stale).**

### Diagnosis

Measured the full fade pipeline latency on 665 live orders:

| Segment | What | p50 | p90 |
|---|---|---|---|
| A: their fill → we see it | **data-api indexer lag** | **108s** | **280s** |
| B: see → submit | our processing | 0.00s | 0.3s |
| C: submit → sign | local crypto | 0.30s | 0.5s |
| D: sign → CLOB response | network | 0.20s | 0.3s |

**Segment A is 99.7% of latency.** Direct probe: the data-api `/trades` newest row is 220–350s old. 27% of target signals were skipped as stale (>300s); 77% of acted trades were already >60s old. We were fading minutes after the market had absorbed the target's bad bet — the likely reason the edge is ~0.

**A VPS would do nothing** — segment D (network) is already 0.2s.

### Fix

`onchain_listener.py` — a background thread that watches Polygon directly:
- ERC-1155 `TransferSingle` events on the Conditional Tokens contract `0x4d97…6045`, filtered via `eth_getLogs` (every 2s) to our target wallets (indexed `to`=BUY / `from`=SELL topic).
- Decodes token id + shares from event data; resolves outcome/market via the token index; price via CLOB midpoint at detection.
- **Decode validated 100%** on side+outcome vs data-api ground truth.
- Detection latency **~2-4s vs ~108-280s = 30-50x faster**.

Integration:
- Listener pushes data-api-shaped trades to a queue; the main loop drains it into the **same `process_trade`** (all gates apply: entry floor, per-wallet cap, single-map filter, hedge guard, daily loss cap).
- The data-api poll **stays on as a backstop**; dedup by tx hash means whichever source sees a trade first wins.
- **Orders are LIMIT** at our computed entry, so a price-decode error cannot make us overpay.
- Any signal where token/market/price can't be resolved sanely is **dropped**, never fired.
- RPC configurable via `POLYGON_RPC_URL` env (defaults to public endpoints).

### What this is

The test of whether latency was killing the edge. If the cleaned target list + 2s latency produces a positive edge over the next stretch, the strategy is real. **If the edge stays dead at 2s, the CS2 fade is not exploitable and we stop** — this removes the last "maybe it's just latency" excuse.

### Monitoring

Heartbeat now logs `onchain[conn= detected= emitted= dropped= last_lag=]`. Every emitted signal writes an `onchain_signal` event. Esports is a small slice of current Polymarket volume, so signals will be infrequent — that's expected.

---

## v1.39 — 2026-05-29
**Three esports fade fixes after a −$240/3-day bleed. Diagnostic: the edge is marginal.**

### The diagnostic (415 live trades)

Market-efficiency test — win rate vs entry price by bucket:

| Entry price | Avg price | Win rate | Edge (WR − price) |
|---|---|---|---|
| 0.45–0.55 | 0.50 | 51.2% | +0.013 |
| 0.55–0.65 | 0.60 | 52.9% | **−0.068** |
| 0.65–0.75 | 0.69 | 70.4% | +0.015 |
| 0.75–0.85 | 0.79 | 79.3% | +0.008 |
| 0.85+ | 0.90 | 90.9% | +0.012 |

**Trade-weighted edge = −1.3%.** Win rate tracks entry price — the signature of an efficiently-priced market with ~no exploitable edge. The first 11 days (+$36) was variance; we scaled $10→$15 at the peak (v1.35) and mean-reverted hard. Last 3 days: 51% WR at 0.63 avg entry = −0.117 edge = −$240.

### Root causes of the concentrated losses

1. **Fading a market maker.** Wallet `0x47138dc1`: 95,730 trades, −11% naive ROI, −$53k. Faded 90× (22% of our volume) for −$109. MMs capture the spread and show mildly-negative *directional* PnL, but they are not recreational losers — fading them just pays the vig.
2. **Single-map/Bo1 markets are coin flips.** −8.1% ROI vs −3.5% for series moneylines.
3. **The target-list ranking surfaced bots.** LIVE subset was sorted by *absolute PnL*, which just ranks the highest-*volume* wallets (bots), not the worst-*edge* wallets.

### Fixes (user-selected 3 of 4)

**`esports_fade_bot.py`:**
- `MAX_FADES_PER_WALLET_PER_DAY = 3` — no single wallet can dominate the book
- `SKIP_SINGLE_MAP_MARKETS = True` + `is_single_map_market()` regex (`-game\d`, `-map-`)

**`analysis/identify_active_targets.py` (target rebuild):**
- Exclude bot/MM wallets trading >30/day. Removed **91 wallets**, including 3 with *positive* ROI (+1.4%, +6.2%, +6.4%) we'd been fading.
- Rank LIVE subset by ROI ascending (worst edge first), **not** absolute PnL.
- Tighten LIVE: full-window ROI < −15% **AND** recent-window ROI < −5%, cap 300 (was 800).
- Recent-window persistence requirement (don't fade reformed wallets).
- New list **hot-reloaded live** (300 wallets, −500 dropped, toxic MM gone) — no restart needed for the list itself.

**Not done:** the [0.55,0.65) price-band filter. It's the worst bucket in-sample but has no causal mechanism — almost certainly overfit. Rejected.

**Not done (user kept):** bet size stays $15. Given edge ≈ 0, smaller size would reduce variance, but user's call.

### Honest assessment

These fixes remove the worst *structural* leaks (MM fading, coin-flip maps, concentration). But the core finding stands: **on directional accounting the strategy is close to break-even.** If the next ~150 trades on the cleaned target list don't show a positive edge, the fade thesis on CS2 may simply not be exploitable at our latency, and we should stop or rethink rather than keep paying the vig.

### Activation

- Target list: live now (hot-reload).
- `MAX_FADES_PER_WALLET_PER_DAY` + single-map filter: **require bot restart** to take effect.

---

## v1.38 — 2026-05-28
**MLB live trading DISABLED — paper edge did not survive live execution.**

### What happened

v1.36 deployed MLB live at $5/trade on 2026-05-27 based on paper data showing **+7-10% ROI over 355 trades**. First ~24 hours of live trading bled hard. User halted via `/pause` and asked to disable MLB.

### Fix

`LIVE_SPORTS_PREFIXES` set to empty tuple `()`. With no eligible sports, `effective_live` is always False in `process_trade` — every signal falls back to paper logging. Bot continues running (NHL/Tennis/NBA/MLB all paper-logged) so data collection isn't lost.

### What needs to happen before re-enabling

This is the second time a strategy has looked great in backtest/paper and failed live (cf. crypto 15m bot). Don't redeploy any sport without understanding **why** the live PnL diverged from the paper PnL.

**Leading hypothesis (user insight, 2026-05-28):** MLB/NBA/NHL/Tennis markets on Polymarket are arbitraged against traditional sportsbooks (DraftKings, FanDuel, Pinnacle) within seconds. There is no persistent mispricing for the fade strategy to exploit — by the time a target wallet places a "bad" bet, arb bots have already snapped the price back to Vegas consensus. We can paper-trade favorable-looking signals all day, but at execution time the edge is gone.

Esports doesn't have this problem because CS2 odds are largely set by Polymarket's own order flow (no traditional book runs CS2 lines at the same scale and speed). So mispricings persist long enough for the fade strategy to capture them.

If this hypothesis is right, **no traditional sport will work for this strategy as currently designed.** Re-enabling MLB would just bleed the wallet again. Possible alternatives:
- Test strategies that exploit the arbitrage rather than fight it (cross-book arb if we can read DraftKings odds, but that's a different bot)
- Stick to markets without external price discovery (esports, niche prediction markets)

Secondary candidates worth ruling out:
1. **Execution friction higher than modeled** — but probably a small effect; paper was already +7% with realistic friction modeled
2. **Different game slate during live window** — possible but the strategy should generalize across slates
3. **Latency effect** — by the time we fade a signal, the market has moved. Could check this with `analysis/evaluate_sports_live.py`

Esports bot is **unaffected** — still LIVE on CS2 at $15/trade.

---

## v1.37 — 2026-05-28
**Fix opposite-side hedge bug — `market_exposure` now persists across days and restarts.**

### What broke

Discovered on `cs2-3dmax-mgc-2026-05-27`:
- 17:24 UTC: bought 3DMAX @ $0.50, 30 shares, $15 → `market_exposure[(cid, "3DMAX")] = $15`
- 00:00 UTC: UTC day rollover → `market_exposure.clear()` wipes the dict
- 01:44 UTC: bought magic @ $0.52 → no prior exposure visible → opposite-side guard misses it
- **Locked guaranteed loss: -$1.15** (best case $0, worst case -$1.15)

The v1.34 hedge guard checked the right thing (`market_exposure[(cid, other_outcome)]`) but the dict was wiped nightly *and* on every bot restart, so any prior-day or pre-restart position was invisible.

### Fix

**Two changes in both `esports_fade_bot.py` and `sports_fade_bot.py`:**

1. **Removed `self.market_exposure.clear()` from UTC day rollover.** Positions persist across days; only daily counters (`daily_pnl`, `daily_risk_usd`, `fades_today`, `last_signal_ts`) reset.

2. **Added `_rebuild_market_exposure()` called at startup.** Scans `live_orders.jsonl`, sums matched BUY cost minus matched SELL cost per `(cid, outcome)`, excludes markets already flagged WIN/LOSS/TP_* in `live_results.csv`. Prints a startup summary including how many markets currently have dual-side holdings.

### Why this is subtle

The `market_exposure` dict was confusingly used for two purposes:
- Per-market position cap (`MAX_PER_MARKET_USD`)
- Opposite-side hedge guard

The first works fine with daily reset (we *want* a fresh cap each day on volume). The second needs lifetime-of-position tracking. Same dict, two semantics — easy to miss when reading the code.

### Damage assessment

- Specific instance (3DMAX/magic): max -$1.15
- Bug latent since v1.34 (2026-05-24, 4 days). A `_scan_dual_positions.py` helper checks all open positions on both wallets — see scan output for full list.
- Scales with bet size: at $20/trade would be -$3–4 per occurrence, at $50/trade -$10+.

### Operational note

Bot needs restart to pick up the fix. The `_rebuild_market_exposure` will print exposure summary on next start — if it reports "N markets with dual-side holdings" > 0, those are existing locked positions and the hedge guard will now correctly block any *new* trades on them.

---

## v1.36 — 2026-05-27
**Sports fade bot enters LIVE mode (MLB only at $5/trade).**

### Why now

4 days of paper data on the v2 sports bot. Per-sport breakdown showed clean separation:

| Sport | Trades | WR | ROI | Verdict |
|---|---|---|---|---|
| **MLB** | 355 | 58.6% | **+7.2%** | Deploy LIVE |
| NBA | 137 | 60.6% | +10.6% | Season ending; skip |
| NHL | 34 | 70.6% | +50.9% | Sample too small |
| Tennis | 569 | 52.4% | **-19.3%** | Excluded — collapsed May 27 |

Tennis went from +2.5% to -19% in a single day (+311 new trades net -$581). Decisive exclusion.

### What changed

**`sports_fade_bot.py`:**
- `LIVE_BET_USD` 10.0 → 5.0 (conservative starting size)
- `DAILY_LOSS_CAP` 150.0 → 75.0
- New `LIVE_SPORTS_PREFIXES = ("mlb-",)` constant
- New `is_live_eligible_sport(slug)` method
- `process_trade` computes `effective_live = self.live and is_live_eligible_sport(slug)`. Real-money gates (bet size, daily caps, order placement) all use `effective_live`. Non-MLB markets in LIVE mode still write to `paper_trades.csv` so NHL/Tennis/NBA data collection continues.
- `main()` re-enables `--live` and `--dry-live` argparse (was hardcoded `args.live = False`)

**`watch_sports_fade.bat`:** launches with `--live` now.

**`analysis/evaluate_sports_live.py`** (NEW):
- Mirror of esports `evaluate_live.py`
- Reads `output/sports_fade/live_orders.jsonl`
- Writes `output/sports_fade/live_results.csv` + `live_daily_pnl.json`
- No wallet-equity tracking (wallet shared with esports; that lives in esports evaluator)

**`run_sports_eval_live.bat`** (NEW): cron entry point.

**New scheduled task `PolyBotSportsLiveEval`** (every 10 min) — refreshes `live_daily_pnl.json` so the bot's `DAILY_LOSS_CAP` can actually fire.

### Wallet & data separation

- **Wallet**: shared with esports for operational simplicity. One Polymarket account.
- **Data**: fully separate. Sports writes to `output/sports_fade/`, esports to `output/esports_fade/`. Different orders ledger, different daily PnL JSON, different evaluator, different cron task.

### Risk profile

- $5/trade × ~90 MLB trades/day expected ≈ $450/day exposure
- Daily loss cap $75 = 15% of expected exposure (won't false-trip on normal variance)
- Bankroll bumps after 200+ live trades hold ≥ +3% ROI

### What's still in PAPER

NHL, Tennis, NBA continue to be paper-logged in `paper_trades.csv` and evaluated by `evaluate_sports_paper.py` (existing cron). When MLB is proven LIVE we can revisit deploying others.

---

## v1.35 — 2026-05-24
**Esports LIVE bet size $10 → $15 (first scale-up). Evaluator switched to wallet-equity as canonical lifetime PnL.**

### Why now

9 days into esports LIVE at $10/trade, my evaluator was reporting **-$24 realized / +$10 MTM** lifetime — essentially breakeven. The user pushed back: "we should be up $170."

Reconciled against on-chain wallet:
- pUSD balance: $836.19
- Open positions MTM: $133.86
- Total equity: **$963.05**
- Starting deposit: **$749**
- **Real lifetime PnL: +$214 / +28.6% ROI in 9 days**

Discrepancy explained: the user keeps winning shares parked at ~$0.999 to skip the redemption fee delta. My evaluator credited those as "realized at $1.00" only after redemption, so ~31 unredeemed wins were silently missing from the headline number.

### What changed (code)

**`esports_fade_bot.py`** — `LIVE_BET_USD` 10.0 → 15.0. Sample size at scale-up: 275 resolved trades. ROI gate (+2% over 400+ trades) was past on ROI, short on sample, but +28.6% is well outside variance noise. Conservative escalation continues at $20 if trend holds another ~1 week.

**`analysis/evaluate_live.py`** — added wallet-equity reconcile:
  - Fetches actual pUSD via CLOB `get_balance_allowance` each run
  - Reads optional `ESPORTS_STARTING_DEPOSIT_USD` from env
  - Writes new JSON fields: `wallet_pusd_cash`, `wallet_total_equity_usd`, `lifetime_equity_pnl_usd`, `lifetime_equity_roi_pct`
  - These are the new canonical lifetime numbers; the realized-from-CSV fields stay (used by the bot's `DAILY_LOSS_CAP` guard) but are now informational

**`.env` (manual on laptop, not in git)**:
  - `LIVE_MAX_DAILY_LOSS_USD` 50.0 → 75.0 (scale proportionally with bet size)
  - `ESPORTS_STARTING_DEPOSIT_USD=749` (added)

### Risk note

9 days is short. A +28% run can occur from variance even on a real +3% edge. Scaling is justified by current data but no further size increases until lifetime equity ROI stays positive after one full ugly week.

---

## v1.34 — 2026-05-12
**ETH-15m re-enabled on LIVE, gated by recent-WR filter. Brain narrowed to ETH-only observation.**

### Why now

24h of v1.33 brain output showed the rewritten prompt fixed conservatism bias (0% degraded, 100% normal). But a synthetic replay test forced the question: does the brain's regime call have FORWARD predictive value?

**Replay test** (15 windows, 5 each of clear degraded/normal/strong): 15/15 correct classification. Brain is well-calibrated.

**Forward-EV check** on 556 historical 10-trade windows: brain regime classification correlates with next-trade EV ONLY for ETH. For BTC and SOL, the correlation is inverted — strong-regime predicts WORSE forward EV (regime reversion at the regime level).

| Brain says (pooled) | n | Next-trade EV (v1.28 corrected) |
|---|---|---|
| degraded | 101 | -$0.07 |
| normal | 320 | -$0.64 |
| strong | 135 | **-$1.05** ← worst |

**ETH-only:**
| Brain says | n | Next-trade EV |
|---|---|---|
| degraded | 36 | -$0.95 |
| normal | 115 | +$0.14 |
| **strong** | 74 | **+$0.52** |

ETH strong vs degraded gap: +$1.47/trade. This is the only segment where brain regime has positive forward signal.

### What changed

1. **`_recent_trade_wr(asset, window, n=8)` helper** in main.py. Reads `output/5m_trading/trades.csv` and returns (wins, total) over the most recent N closed trades for that segment. Deterministic, no API, runs in milliseconds.

2. **ETH-15m LIVE conditional entry filter** in the MR entry path. When `live AND asset=="ETH" AND window=="15m"`:
   - If fewer than 8 recent trades exist → skip (no filter signal yet)
   - If recent wins < 5/8 → skip with `[WR-FILTER]` log line
   - Else allow entry (normal flow)
   - **PAPER ETH continues to enter unconditionally** to keep collecting data

3. **`multi-live` default config: ETH-15m re-added** alongside SOL-15m. BTC stays off LIVE.

4. **Brain narrowed to ETH-15m only.** BTC, SOL, and all 4h threads no longer initialize WindowBrain — those API calls were producing anti-predictive noise. Saves ~70% of brain cost while preserving the signal for the segment where it works.

### What this does NOT do

- **Does NOT unpause LIVE.** `paused.live.flag` is preserved through this deploy. User must explicitly remove the flag for v1.34 to actually place LIVE trades. The configuration is staged; the activation is deliberate.
- Does NOT change PAPER behavior for any asset. PAPER continues entering on all 6 (asset, window) combos to keep building history.
- Does NOT promote the brain to authoritative. Brain stays advisory-only on ETH — used for observation/research, not gating.

### Why use raw WR instead of the brain

The replay confirmed the brain just echoes the WR threshold (since we filtered windows by WR to construct the test). The brain is essentially a regime-classifier-of-the-WR-input. Using WR directly:
- Removes API dependency (no timeout, no rate limits, no model drift)
- Cost: $0 vs $0.05/day
- Latency: microseconds vs 1-2 seconds
- Determinism: every restart, same input → same answer
- Auditable: the function is 20 lines, completely transparent

Brain stays around (ETH-only) as a research tool: when WR filter passes AND brain says strong, that's the highest-confidence segment. We can compare brain-strong-WR-passes vs brain-normal-WR-passes once we have data.

### Expected production behavior

At current rate (~6 ETH-15m entries/week on PAPER, with maybe 30% in strong-WR regime): roughly **1-2 ETH LIVE trades per week** when filter passes.

Per-trade EV: +$0.52 (point estimate, wide CI). At $5 size: +$0.50-$1/week if signal holds. Not transformative; **first defensible positive-EV LIVE configuration** since project inception.

### Risks

- ETH-strong EV +$0.52 has 95% CI roughly [-$1.50, +$2.50]. Could be noise on n=74.
- The WR filter is computed from PAPER history. PAPER and LIVE diverge (v1.28 execution drag analysis). LIVE EV may differ.
- The "regime persistence" hypothesis the filter relies on is statistically weak (autocorrelation +0.158). It works on ETH but the mechanism isn't fully understood.

### Files changed
`main.py` (helper + filter + multi-live config + brain scope), `src/bot/version.py`, `PATCH_HISTORY.md`, `STRATEGY_HISTORY.md`.

### Reference
`BRAIN_RESEARCH_DATA.md` (forward-EV signal table), `replay_brain_test.py` (calibration validation), `replay_forward_ev.py` (forward-EV by regime).

---

## v1.33 — 2026-05-11
**Brain prompt rewrite #1 — counter conservatism bias**

### Evidence triggering the rewrite

35h of v1.32 observation produced 48 brain calls. The distribution is the textbook conservatism-bias failure mode the research predicted:

| Field | v1.32 distribution | Expected |
|---|---|---|
| mr_edge=strong | 0 (0%) | ~25% |
| mr_edge=normal | 2 (4%) | ~50% |
| mr_edge=degraded | 39 (95%) | ~25% |
| modifier mean | +0.029 | ~0.000 |
| modifier negative | 0 | should exist |
| modifier positive | 39 | should be balanced |
| reasoning contains "skip" | 7 (15%) | 0 (forbidden) |
| reasoning mentions "zero edge" | 18 (38%) | 0 |
| 4h-vs-15m confusion | 4 | 0 |

Brain has never said "loosen the gate." Brain has never said "regime is strong." Brain's reasoning routinely uses patterns the v1.32 prompt explicitly forbids. This is the same root cause as the v1.0 `claude_advisor.py` failure (96% block rate).

### Rewrite (rewrite #1 of allowed 2)

`_SYSTEM` prompt v2 changes:

1. **modifier=0.00 is explicit default**, not the "neither" fallback. "Most calls should return modifier=0.00."
2. **Anti-conservatism warning**: "LLMs in trading consistently exhibit conservatism bias. Counter this bias actively."
3. **Baseline anchor**: "This bot's historical EV is approximately -$1/trade. Loss clusters and negative cumulative PnL are NORMAL background noise, not regime alarms."
4. **NORMAL reasoning examples** (v1 had zero — only STRONG and DEGRADED): "5/10 wins with mixed exits. Typical noisy conditions." / "No history yet — default neutral."
5. **Anti-patterns enumerated and forbidden by name**: "Skip", "Edge zero / no edge signal", "Cumulative pnl negative" alone, "Soft-exit cluster" alone, "Mixed outcomes" → modifier=+0.02, "4h window too long".
6. **Edge field handling**: "edge=0.0 means this metric is NOT computed for mean-reversion. IGNORE."
7. **4h equal weight with 15m**: "Window length is informational only."

User prompt: removed `edge` and `rv_std` fields entirely (v1.32 model misread 0.0 as bearish in 38% of calls). Added a reminder line: "REMEMBER: default is modifier=0.00 (NORMAL). Only deviate if evidence is SPECIFIC and CLEAR."

### What this version is NOT

- **Still advisory-only.** Brain output is logged; bot ignores it. Same as v1.32. No LIVE impact.
- **Not a v1.33 promotion** to authoritative. The architecture review's v1.33 spec (activate modifier behind A/B, add confidence field) requires passing the observation gate first. We're re-running observation with a better prompt; this is structurally still "phase 1."

### Operational plan

- Reset call counter. Next 80 brain calls = fresh observation set.
- After 30 calls, check the four diagnostic signals: is `mr_edge=strong` non-zero? is modifier mean near 0? does reasoning still use forbidden patterns? does brain reference recent_wr in its reasoning?
- After 80 calls AND if `mr_edge=strong` mean pnl ≥ `mr_edge=degraded` mean pnl + 1 SE: proceed to real v1.33 (activate modifier behind A/B).
- If this prompt also fails the gate: ONE more rewrite is allowed per the research rules. If three fail, kill the brain.

### Files changed
`src/bot/window_brain.py` (prompt v2), `src/bot/version.py`, `PATCH_HISTORY.md`, `STRATEGY_HISTORY.md`.

### Reference
`BRAIN_RESEARCH_FINDINGS.md` Finding 1 (why v1.32 prompt was set up to fail), Finding 3 (modifier=0 should be common), and the "Three specific things to look for during observation" section.

---

## v1.32 — 2026-05-10
**Wire WindowBrain (per-trade Claude reasoner) in advisory-only mode**

User strategic insight: "Successful bots running on these markets exist; we need a strategy that thinks on every trade instead of placing based on different markets hitting or missing." The current architecture is a static filter cascade. Each candidate gets the same heuristic. That doesn't capture context (regime, recent flow, microstructure) that informs whether a specific setup is worth taking.

The codebase already had `src/bot/window_brain.py` (310 lines): a per-trade Claude Haiku reasoner that classifies regime + recent-history performance and returns a continuous edge modifier. It was designed but **never wired into main.py**. Reason for caution: the older `claude_advisor.py` (binary ENTER/SKIP) was disabled because it blocked 96% of in-range windows — wrong mental model.

WindowBrain is structurally different:
- Continuous modifier `[-0.05, +0.05]`, not binary gate
- Asks "is mean-reversion working right now?" — does NOT predict direction
- Maintains rolling history of last 10 resolved trades per asset
- Uses prompt caching → ~$0.005/day cost
- Fails open (neutral) on any error

### What this version does

1. Generalized `WindowBrain` to take `(asset, window)` in `__init__` so it can run per-window (was 15m-hardcoded). `sync_from_csv` filters by both. Prompt mentions actual window.
2. Wired into `main.py` for `mean_reversion` strategy on `15m` and `4h` windows:
   - Brain initialized once per thread at startup
   - History synced from `output/5m_trading/trades.csv` at every window transition
   - `brain.advise()` fires once per entry candidate per window (cached for the rest of the window)
   - Decision logged via `print()` → bot.log: `[BRAIN] {asset} regime={...} mr_edge={...} modifier=±0.0XX (Nms cache r=X w=X) — {reasoning}`
3. **Brain output does NOT alter trade entry yet.** Pure observation phase.

### Plan

- **Phase 1 (this version):** Brain advises in observation mode. After 50+ brain-evaluated trades, analyze: did brain's regime classification correlate with realized EV?
- **Phase 2 (v1.33+, conditional):** If brain signal is real, promote to authoritative. Two ways:
  - Use `edge_modifier` to dynamically tighten/loosen entry band, or
  - Set `BRAIN_VETO=true` to let high-modifier (degraded regime) skip entries entirely.
- **Phase 3 (longer-term):** Replace regime-classifier prompt with full per-trade reasoning agent that returns structured `{enter, tp, sl, size_scalar, confidence, reasoning}`.

### Files changed
`main.py` (brain init, per-window state, advise call), `src/bot/window_brain.py` (generalized window param), `src/bot/version.py`, `PATCH_HISTORY.md`, `STRATEGY_HISTORY.md`.

### Configuration

Env (defaults):
- `ANTHROPIC_API_KEY` — required (already set on laptop)
- `BRAIN_ENABLED=true`
- `BRAIN_MODEL=claude-haiku-4-5-20251001`
- `BRAIN_TIMEOUT=6.0`
- `BRAIN_HISTORY_LEN=10`
- `BRAIN_VETO=false` — must stay false in v1.32 (advisory only)

---

## v1.31 — 2026-05-10
**4h PAPER experiment (longer-horizon strategy pivot)**

### Why

ML feature exploration on n=721 MR-15m PAPER trades (v1.28-corrected) returned **AUC = 0.496** — statistically indistinguishable from chance. Critically, every probability threshold from 0.50 to 0.70 produced a predicted-positive subset *worse* than baseline. **Higher confidence → worse outcomes.** This is decisive evidence that 15m mean-reversion has no learnable signal in the features captured. Reference: `ML_FEATURE_EXPLORATION.md`.

Per `STRATEGY_PIVOT_SCOPING.md`, the next experiment is Option 1: longer-horizon Polymarket Up/Down markets. Discovery (`OPTION_1_DISCOVERY.md`) confirmed 4h markets exist with `{asset}-updown-4h-{epoch}` pattern — the same family as the existing 5m/15m code. 1h and daily exist but use different slug formats and require new discovery code; deferred until 4h shows signal-or-null.

### What changed

`market_5m.py`:
- `WINDOW_SECONDS["4h"] = 14400`
- `SLUG_PREFIXES["4h"]` for BTC/ETH/SOL
- `MIN_LIQUIDITY_BY_WINDOW["4h"] = 2000` (was 15k for 5m/15m — would reject every 4h market)
- `ENTRY_MIN_BY_WINDOW["4h"] = 0.28`, `ENTRY_MAX_BY_WINDOW["4h"] = 0.45` (wider than 15m's [0.32, 0.40])

`signal_5m.py`:
- Liquidity check uses per-window floor
- Entry band uses per-window edges
- Cross-window filter **skipped** on 4h (15m-tuned thresholds inappropriate at 4h cadence)
- BTC DOWN hard-skip **only fires on 5m/15m** (the "negative EV across all bands" finding was 15m-specific)

`main.py`:
- `soft_exit_secs`: 5m=115, 15m=420, **4h=3600** (last 1h)
- `hard_stop_max_remaining`: 15m=240s, **4h=3600s**, else inf
- `window_duration` uses `market.window_seconds` (was hardcoded 900/300)
- `multi-loop` default adds `("BTC", "4h", ...)`, `("ETH", "4h", ...)`, `("SOL", "4h", ...)`
- `multi-live` default **unchanged** — LIVE still runs SOL 15m only

### Expected behavior

6 4h windows/day × 3 assets = 18 4h evaluation cycles/day on PAPER. Trade frequency depends on how often the cheap side falls into [0.28, 0.45]. Estimating 10-15 trades/day across all 4h assets initially. Reach n=200 in ~2 weeks for first Cowork pass.

**Live verification at deploy time:** all three 4h markets discovered cleanly:
- BTC-4h slug=`btc-updown-4h-1778414400`, liq=$5.8k
- ETH-4h slug=`eth-updown-4h-1778414400`, liq=$9.5k
- SOL-4h slug=`sol-updown-4h-1778414400`, liq=$3.4k

### What this is NOT

- Not a LIVE deployment of 4h. multi-live config is unchanged. Zero LIVE risk.
- Not abandonment of 15m PAPER data collection. 15m runs in parallel.
- Not a commitment to longer-horizon as the pivot — purely a 2-week PAPER experiment to test whether 4h has a different edge profile.

### Files changed
`main.py`, `src/bot/market_5m.py`, `src/bot/signal_5m.py`, `src/bot/version.py`, `PATCH_HISTORY.md`, `STRATEGY_HISTORY.md`. Reference: `OPTION_1_DISCOVERY.md`, `ML_FEATURE_EXPLORATION.md`, `STRATEGY_PIVOT_SCOPING.md`.

---

## v1.30 — 2026-05-10
**Widen SOL UP band on PAPER for data collection (LIVE band unchanged)**

48h after the v1.29 deploy: 21 new MR-15m PAPER trades total, **ZERO SOL UP**. Of 246 SOL windows skipped post-v1.28: 51% `price_too_high` (>0.35), 33% `btc_filter`, 16% `price_too_low` (<0.33). The narrow [0.33, 0.35] band is functionally unreachable in current market conditions.

The plan to "grow SOL UP n past 200" before re-evaluating LIVE was structurally broken at the current rate. Three options were considered: (a) widen SOL band, (b) wait longer (rate ≈ 0/month), (c) pivot strategy. Going with (a) on PAPER only — LIVE band stays at [0.33, 0.35] until the wider band is shown to be +EV under v1.28 corrected accounting.

### Implementation

`should_enter()` gets a new `is_live: bool = False` kwarg. The SOL ceiling is then:
- LIVE (`is_live=True`):  0.35  (unchanged from v1.21)
- PAPER (`is_live=False`): 0.40  (widened by 5¢)

Floor stays 0.33 in both cases. SOL DOWN remains hard-disabled.

```python
sol_ceiling = 0.35 if is_live else 0.40
```

### Expected effect

Estimating from May 5 data: [0.35, 0.38) had n=50 over the data history (vs n=16 for [0.33, 0.35)). Widening should give us roughly 3-4x the SOL UP trade rate on PAPER. With the v1.28 corrected accounting now applied to all new entries, we'll have a clean dataset for evaluating whether [0.35, 0.40] is also +EV.

### Risk

LIVE behavior unchanged (LIVE config = SOL only with [0.33, 0.35] ceiling). PAPER going wider only generates more data. If the wider band turns out to be -EV under correction, we narrow back. Cost of being wrong: zero (PAPER only).

### What this is NOT

This is NOT a re-enable of any LIVE asset. LIVE remains paused, BTC and ETH remain off LIVE, SOL band on LIVE remains narrow. v1.30 is purely a PAPER data-collection change.

### Files changed
`main.py` (passes `is_live=live` to `should_enter()`), `src/bot/signal_5m.py` (SOL ceiling depends on `is_live`), `src/bot/version.py`, `PATCH_HISTORY.md`, `STRATEGY_HISTORY.md`.

### Reference
`V1_28_RETROACTIVE_FINDINGS.md`, `analyze_postv129.py` (the 48h analysis that motivated this change).

---

## v1.29 — 2026-05-07
**ETH disabled on LIVE — corrected baseline shows no positive-EV configuration except SOL UP**

Retroactive application of v1.28's accounting corrections (TP exit at exact `take_profit`, share count × 0.955) to all n=693 historical MR-15m PAPER trades. Method: `analyze_v1_28_retro.py`.

### The headline finding

The "+$0.12/trade PAPER EV" baseline that drove the entire v1.27 + v1.28 decision tree was entirely an artifact of PAPER over-stating TP wins. Corrected EV by segment:

| Segment | n | Old EV | v1.28 corrected EV |
|---|---|---|---|
| MR-15m all | 693 | +$0.12 | **-$0.98** |
| ETH UP | 145 | +$0.87 | **-$0.43** |
| ETH DOWN | 123 | +$0.61 | **-$0.49** |
| **SOL UP** | **74** | **+$1.72** | **+$0.53** |
| BTC UP | 194 | +$0.05 | -$1.05 |

TP-win detail: avg recorded `exit_price` 0.668 vs avg `take_profit` 0.644 → ~2.4¢ gap → **$2.07/winning-trade overstatement**. This single correction explains the bulk of the apparent LIVE-vs-PAPER drag.

### Decision

LIVE configuration:
- BTC: off (v1.21 + v1.27)
- ETH: **off this version** — same risk-management logic as v1.27 BTC disable (negative point estimate at meaningful n)
- SOL: stays eligible — only segment with corrected positive EV (+$0.53/trade, n=74, marginal)

ETH stays on PAPER for data collection. ETH t-stat=-0.71 — not statistically negative, just point-estimate negative. Could be noise. Decision is reversible.

### Implications for next steps

The plan was: wait for ~50-100 post-v1.28 PAPER trades to confirm corrections worked, then resume LIVE if PAPER ETH still showed edge. **This is short-circuited:** PAPER ETH was never +EV under honest accounting; new ETH PAPER trades won't change that.

Next session should consider:
1. Continue PAPER on all assets to grow SOL UP's n
2. Pivot the strategy hypothesis (different markets, time horizons, ML)
3. Accept the bot as a data-collection / learning exercise

The bot does not currently have confirmed positive edge at meaningful sample size. The honest framing matters.

### Files changed
`main.py` (multi-live config), `src/bot/version.py`, `PATCH_HISTORY.md`, `STRATEGY_HISTORY.md`. New: `V1_28_RETROACTIVE_FINDINGS.md`, `analyze_v1_28_retro.py`.

---

## v1.28 — 2026-05-06
**Execution-drag root cause: PAPER over-reporting, NOT LIVE underperforming**

Code audit of `live_engine_5m.py` and `engine_5m.py` (v1.27 left LIVE paused pending this investigation) found the measured -$0.36 to -$0.55/trade LIVE-vs-PAPER drag is mostly a PAPER pnl over-statement, not a LIVE execution problem. Three fixes:

### Fix 1 — TP exit price: PAPER → `pos.take_profit` (was `cur_up`)
**File:** `main.py` close-position branch (PAPER path)

PAPER booked TP exits at `cur_up` (the just-crossed observed price), which is by definition `>= take_profit` when the TP condition fires. With 1-2s poll cadence and price crossing 0.60, PAPER often recorded 0.61-0.63. LIVE's GTC SELL rests at exactly `pos.take_profit` (0.60) and fills there. On a 12.24-share trade, that's $0.25-$0.37 over-stated per winning trade — explaining the bulk of measured drag.

```python
# v1.28
if reason == "take_profit":
    exit_price = pos.take_profit         # match LIVE's GTC limit fill
else:
    exit_price = cur_up if pos.side == "UP" else (1.0 - cur_up)
```

### Fix 2 — Share count: PAPER models 4.5% wallet-fill discount
**File:** `src/bot/engine_5m.py` `open()` method

LIVE actually receives ~4.5% fewer shares than `POSITION_SIZE / entry_price` because Polymarket's API `size_matched` over-reports vs wallet balance (documented in `live_engine_5m.py:406-409`, v1.11 reconciliation). PAPER didn't model this. ~$0.10/trade over-statement.

```python
PAPER_FILL_DISCOUNT = 0.955   # observed wallet/expected ratio (v1.11)
shares = round((net_investment / entry_price) * PAPER_FILL_DISCOUNT, 2)
```

### Fix 3 — LIVE wallet-empty path: rewrite `exit_reason` to `market_resolved`
**File:** `src/bot/live_engine_5m.py` `place_exit()` wallet-empty branch

When position resolves against us (token redeemed for $0 by the exchange) before the FOK can fill, the wallet is empty. The code settled at exit_price=0.0 but preserved the original exit_reason (`hard_stop_floor`, `soft_exit_stalled`, etc.) — distorting exit-reason analytics. The orderbook-gone branch correctly rewrote to `market_resolved`; this branch did not. Now both do.

### Implications

The "LIVE EV is worse than PAPER EV" framing was largely an artifact. With these fixes:
- Historical PAPER MR-15m EV +$0.12/trade becomes retroactively ~-$0.20/trade once the TP/share corrections are accounted for. **The strategy was never positive-EV at $5 LIVE size.**
- Going forward, PAPER and LIVE should converge to within ~$0.10/trade.
- BTC remains off LIVE (v1.27 decision is unchanged).
- LIVE remains paused. Resume threshold: re-measure matched-pairs drag on n=20+ post-v1.28 trades; if ≤$0.10/trade, the strategy economics are honest and we can reassess sizing.

### Files changed
`main.py`, `src/bot/engine_5m.py`, `src/bot/live_engine_5m.py`, `src/bot/version.py`, `PATCH_HISTORY.md`, `STRATEGY_HISTORY.md`. Reference: `EXECUTION_DRAG_FINDINGS.md`.

---

## v1.27 — 2026-05-06
**Disable BTC on LIVE — execution-drag-driven decision**

Cowork May 5 Opus reanalysis surfaced two findings the original May 5 review missed:

1. **Population confound.** The "strategy is net-negative -$1,150" framing pooled 4 retired sub-strategies with the live MR-15m one. Filtering to MR-15m only (n=693): EV=+$0.12/trade, total=+$86. Current strategy is statistically flat, not broken.

2. **Execution drag is the dominant LIVE signal.** Matched-pairs LIVE-vs-PAPER on the same `(asset, side, window_end_ts)` shows:
   - BTC: LIVE−PAPER = -$0.36/trade (t=-3.76, n=22)
   - ETH: LIVE−PAPER = -$0.55/trade (t=-2.52, n=15)
   - On $5 positions this is 7–11% per trade in pure execution cost
   - This is the most statistically significant result in the dataset

**Decision: BTC fully off LIVE.**
- BTC DOWN: already disabled v1.21
- BTC UP: now disabled (this commit). LIVE n=13, WR=23%, EV=-$2.80, total=-$36.38
- BTC stays on PAPER for continued data collection

**LIVE remains paused** (`paused.live.flag` retained) until execution-drag root cause is identified. Suspected sources:
- TP SELL fills below 0.60 (sample: trade 5 entered 0.39 × 12.24 shares; theoretical $2.57 gain at 0.60; actual pnl $2.34 → $0.23 slippage)
- `hard_stop_floor` exits show -80% to -97% losses (stop placed at price 0.10 → fills below 0.10 in fast moves)
- Possible fee leakage (`entry_fee_usd=0.0` recorded but actual fees absorbed in fills)

**Recommendations explicitly NOT acted on (Opus disagreed with prior review):**
- UTC 17–20 blackout: zero hours survive Bonferroni or BH-FDR on MR-15m. Walk-forward shows 5/8 H1-bad hours reverse in H2. ETH-only p=0.38. This was bin-hunting.
- SOL band widening to [0.33, 0.38): bin-hunting on n=50 in [0.35,0.38). Collect more data first.

**Files changed:** `main.py`, `src/bot/version.py`, `PATCH_HISTORY.md`, `STRATEGY_HISTORY.md`. Reference docs: `COWORK_REVIEW_2026-05-05.md`, `COWORK_REVIEW_2026-05-05_OPUS.md`.

---

## v1.26c — 2026-05-03
**HOTFIX: Corrected v1.26a cross-window filter band edges**

v1.26a generalized the ETH v1.22 cw filter to all assets but mistakenly copied the ETH-specific band edges (`+0.03` lower bound on positive side, `-0.10` lower bound on negative side) instead of using Cowork's validated specification:

```
Cowork §7 spec:
  CW_BAND_NEG = (-0.15, -0.02)   # allow
  CW_BAND_POS = (+0.02, +0.10)   # allow
  CW_DEADZONE = (-0.02, +0.02)   # block
```

**Effect of the bug:** BTC's cross-window was reading `+0.022%` — which falls in `(+0.02, +0.03)`. Under v1.26a this was blocked (needed `>=+0.03`). Under the correct spec it passes (needs `>=+0.02`). Zero PAPER trades were placed for 24h.

**Fix:** Changed `signal_5m.py` global filter from `[-0.10,-0.02]∪[+0.03,+0.10]` to `[-0.15,-0.02]∪[+0.02,+0.10]`. This is exactly what Cowork specified, matches the validated filter cascade Step 2, and unblocks the windows that were incorrectly skipped.

**Verified:** Bot.log was showing `[SIGNAL] Skip BTC — cw +0.022% outside [-0.10,-0.02]∪[+0.03,+0.10]` continuously. After this fix, BTC `+0.022%` now correctly passes as in-range.

**Files changed:** `src/bot/signal_5m.py`, `src/bot/version.py`, `PATCH_HISTORY.md`, `STRATEGY_HISTORY.md`.

---

## v1.26b — 2026-05-02
**Phase 2: Crash regime filter — avoid extreme-volatility windows**

Cowork analysis of 1633 trades found April 27 & May 1 crashes: both RS and underlying MR edge vanish when BTC swings >10% from window start. Root cause: cascading liquidations, margin calls, thin markets, execution slippage. Threshold: skip entries when |BTC % change from window start| > 10%.

**Changes:**
1. **New constant `BTC_CRASH_PCT_THRESHOLD` in `market_5m.py`** (default 0.10, env configurable).
2. **Filter gate in `main.py` MR entry logic** (lines ~879-887): after GBM collapse check, compute `btc_pct_chg_abs = abs(btc_pct_chg_entry)`; if exceeds threshold, skip with `[CRASH]` reason.
3. **Logged to trades.csv:** new column `skip_reason = "BTC_CRASH"` in skipped_windows.csv for monitoring.

**Impact (Cowork backtest on 1633-trade history):**
- Projected: +$200 PnL (loss avoidance, no WR change)
- Frequency: ~8-15 skipped entries/month during volatile windows
- Side effect: none expected (avoids true systematic-risk regimes where edge collapses anyway)

**Mechanism:**
- April 27 crash: BTC fell ~7% morning, bounced ~18% afternoon → UP trades crushed in high-volatility chop
- May 1 crash: BTC oscillated 0.002 ↔ 0.745 → DECEL filter firing constantly, RS whipsawed into losses
- 10% threshold empirically identified by Cowork as the inflection point where MR win rates cross breakeven

**Files changed:**
- `src/bot/market_5m.py` — new BTC_CRASH_PCT_THRESHOLD constant
- `main.py` — import new constant, add filter gate after GBM collapse check
- `src/bot/version.py` — bumped to v1.26b
- `PATCH_HISTORY.md`, `STRATEGY_HISTORY.md` — documentation

---

## v1.26a — 2026-05-02
**Cowork May 1 deep dive: kill RS entirely + generalize cross-window filter**

Cowork reanalysis of 1633 PAPER trades (2026-04-04 to 2026-05-01, 3x since April 25 analysis) found that the April 25 RS findings were a **false positive at small N**. With current data:

- All RS sub-strategies are net-negative over the last 7 days
- April 25 finding: ETH+SOL DOWN RS: z=2.43, p=0.0151 (n=55)
- Recompute at 3x data: t≈1.98, p≈0.05 (exactly Bonferroni noise floor, no correction applied)
- Structural payoff asymmetry unsalvageable: avg_loss/avg_win = 7.7/3.5 requires ~69% WR to break even; actual max achieved is 61%

Specifically:
- ETH DOWN RS: 56% WR, -$86 (down from 75% WR, +$16 on rolling 50-trade window April 25)
- SOL DOWN RS: 60% WR, +$6 (down from 79% WR, +$46)
- BTC RS (all sides): uniformly unprofitable

**Changes:**
1. **Removed all RS threads from `multi-loop` default argv** (lines 1176-1178 deleted, replaced with comment explaining the kill decision).
2. **Removed `is_live` parameter from `should_enter_resolution_scalp()`** in `signal_5m.py`. Function now marked [DEAD CODE] in docstring with Cowork reference.
3. **Generalized v1.22 ETH cross-window filter to all assets (BTC, ETH, SOL)**. Changed from:
   - Global filter (non-ETH only): `CROSS_WINDOW_MIN to CROSS_WINDOW_MAX` (approx -0.15 to 0.02)
   - ETH-only union: `[-0.10,-0.02] ∪ [+0.03,+0.10]`
   
   To:
   - All assets: `[-0.10,-0.02] ∪ [+0.03,+0.10]` (BTC-momentum-continuation regimes)

   Mechanism per Cowork analysis: BTC → ETH/SOL momentum is directional, not symmetric; outside these windows, MR edge disappears.

**Impact:**
- PAPER: 6 sub-strategies → 3 (MR only). No RS running. Data collection cleaner.
- LIVE: Unchanged (still 3 MR threads, no RS).
- Expected PAPER WR improvement: MR alone should run cleaner without RS drag.

**Files changed:**
- `main.py` — removed RS configs from multi-loop argv (3 lines)
- `src/bot/signal_5m.py` — removed `is_live` param, generalized cw filter, marked RS dead code
- `src/bot/version.py` — bumped to v1.26a
- `PATCH_HISTORY.md`, `STRATEGY_HISTORY.md` — documentation

**Next:** v1.26b will implement crash regime filter (`|btc_pct_change_at_entry| ≤ 0.10`) to avoid entries during extreme-volatility windows. See Cowork rec (c).

---

## v1.25 — 2026-04-28
**HOTFIX: revert v1.24 RS-on-LIVE rollout — `LiveEngine5m` has no `open()` method**

v1.24 added `("ETH","15m","resolution_scalp")` and `("SOL","15m","resolution_scalp")` to the `multi-live` default argv. Discovery on 2026-04-28 (Polymarket V2 cutover day): bot.log was full of `'LiveEngine5m' object has no attribute 'open'` errors firing every second. Root cause:

- The MR call site (line ~962) has a proper `if live: engine.place_entry(...) else: engine.open(...)` branch.
- The RS call site (line ~743) has **no `if live:` branch** — it calls `engine.open(...)` unconditionally.
- `Engine5m` (PAPER) has `def open(...)`. `LiveEngine5m` has only `place_entry` / `place_exit`.
- Therefore every RS entry attempt on LIVE since v1.24 deployed has thrown AttributeError silently in bot.log.
- Beyond the missing method: `LiveEngine5m`'s exit logic (`hard_stop_floor`, `soft_exit_stalled`) is MR-style and would mishandle RS positions, which need `TP=0.99 (unreachable)` + `force_exit_at_window_end`. Even fixing the missing method would not give correct LIVE RS behavior without further engine work.

**Changes:**
1. Removed RS threads from `multi-live` default argv. Default is back to MR-only (3 threads) as in v1.23.
2. Added defensive `if live: print(...); continue` guard at the RS call site in `main.py` so this can't recur if RS is re-added to LIVE argv without proper engine support.

**Impact:** RS continues to run on PAPER (all 6 sub-strategies). LIVE returns to MR-only. The Cowork-validated 75–82% WR ETH DOWN RS / SOL DOWN RS strategies remain available — they just need a proper `LiveEngine5m` RS code path before they can deploy. Tracked as future work.

**Coincidental timing:** Today is also the Polymarket V2 CLOB migration cutover (April 28 11:00 UTC). v1.18 already migrated to `py-clob-client-v2` ahead of the deadline. The V2 SDK is functioning (`py_clob_client_v2 import` succeeds at runtime; balance reads work via `BalanceAllowanceParams`). The error storm we found was unrelated to V2 — it was the v1.24 RS bug.

**Files changed:** `main.py` (argv revert + guard), `src/bot/version.py`, `PATCH_HISTORY.md`, `STRATEGY_HISTORY.md`.

---

## v1.24 — 2026-04-25
**RS rollout to LIVE — ETH DOWN RS + SOL DOWN RS added to multi-live**

Both ETH DOWN RS and SOL DOWN RS cleared all rollout gates set in v1.23:

| Strategy | Last 20 WR | Last 50 WR | Last 50 PnL | Gate |
|---|---|---|---|---|
| ETH DOWN RS | >= 70% PASS | 75.0% PASS | +$16.27 PASS | [OK] |
| SOL DOWN RS | >= 70% PASS | 79.2% PASS | +$46.00 PASS | [OK] |

**Change:** Added `("ETH", "15m", "resolution_scalp")` and `("SOL", "15m", "resolution_scalp")` to the `multi-live` default argv in `main.py` (lines ~1135-1141). No signal logic changes — v1.23 `is_live` filter already in place blocks BTC RS (both sides) and ETH/SOL UP RS automatically. Only ETH DOWN RS and SOL DOWN RS will actually enter on LIVE.

**Files changed:**
- `main.py` — multi-live default configs (2 lines added)
- `src/bot/version.py` — bumped to v1.24

---

## v1.23 — 2026-04-25
**Cowork comprehensive analysis — Resolution-scalp UP/DOWN asymmetry → LIVE-only RS filter**

Cowork analysis of 785 active-strategy trades (618 MR + 167 RS, 2026-04-04 to 2026-04-25) surfaced a sharp UP/DOWN asymmetry within the resolution-scalp strategy that wasn't visible at the per-asset level. Root cause: BTC drives ETH/SOL during 15m windows; in-window BTC falls propagate cleanly to ETH/SOL DOWN resolution, while in-window BTC rises do not produce a comparable UP edge. BTC RS itself is structurally negative because BTC is the *source* of the signal — by the time GBM is confident, the market has already priced the move.

### The finding (per asset × side, 167 RS trades total)

| Sub-strategy | n  | WR    | PnL      | avg_win | avg_loss | Breakeven WR |
|--------------|----|-------|----------|---------|----------|--------------|
| ETH DOWN RS  | 32 | 81.2% | +$47.59  | +$3.42  | -$6.88   | 66.8%        |
| SOL DOWN RS  | 23 | 82.6% | +$52.08  | +$4.17  | -$9.04   | 61.9%        |
| ETH UP RS    | 23 | 65.2% | -$13.11  | +$3.10  | -$7.46   | 70.6%        |
| SOL UP RS    | 20 | 50.0% | -$49.26  | +$2.98  | -$7.91   | 72.6%        |
| BTC UP RS    | 43 | 65.1% | -$28.92  | +$3.79  | -$9.01   | 70.4%        |
| BTC DOWN RS  | 26 | 69.2% | -$30.75  | +$2.13  | -$8.63   | 80.2%        |

- Combined ETH+SOL DOWN: 55 trades, **81.8% WR, +$99.67**.
- Combined UP-side + all BTC RS: 112 trades, **63.4% WR, -$122.03**.
- Two-proportion z-test on WR: **z = 2.43, p = 0.0151**.
- Walk-forward (H1 vs H2 across 3-day window): UP-side EV is consistently negative in both halves; DOWN-side is consistently positive.

### Why BTC RS is structurally bad (Cowork Section 2)
At entry price `p` and exit at force_exit_time, the realised payoff is roughly `±(1−p)` for a win and `−p` for a loss. For BTC RS the GBM signal pushes entries toward `p ≥ 0.85`, so wins pay ≤ $0.15/share while losses are -$0.85+/share. The breakeven WR is approximately `p` itself. Empirical 67% can never clear that bar at any threshold.

### Changes (signal_5m.py — LIVE only)
1. **`should_enter_resolution_scalp` gains `is_live: bool = False` argument.**
2. **When `is_live=True`:**
   - BTC RS rejected on both UP and DOWN branches.
   - ETH UP / SOL UP branches rejected.
   - ETH DOWN / SOL DOWN branches preserved.
3. **When `is_live=False` (PAPER):** no change. All 6 sub-strategies continue running for ongoing monitoring (Cowork's explicit recommendation — we want to know if UP-side recovers in a different regime).
4. **`main.py` passes `is_live=live`** to the call site (line ~736).

### What did NOT change
- **MR filters** (BTC, ETH, SOL): all v1.21 + v1.22 filters preserved. Cowork validated v1.22 ETH cw filter against the same dataset.
- **`multi-live` default** still MR-only — there is no RS thread on LIVE today, so the v1.23 filter is *dormant* until the user explicitly adds e.g. `("ETH", "15m", "resolution_scalp")` to the multi-live argv. The filter is wired now so that whenever LIVE re-activates, only the validated sub-strategies fire.
- **Position sizing**: PAPER stays at $15/trade (engine_5m.py:37), LIVE stays at $5/trade (.env). Cowork explored Kelly sizing and recommended *not* sizing up ETH DOWN RS until n ≥ 100 (currently n=32).

### Rejected from Cowork's options (with reasoning)
- **ETH-MR regime skip on top of v1.22**: Cowork backtested `soft_last5 ≥ 0.6` skip and found it *net-negative* once the v1.22 cw filter is in place — the cw filter and regime counter solve the same problem (avoid trending regimes), so they cancel rather than compound. Defer until v1.22 cw filter degrades in production.
- **Size up ETH DOWN RS to $30/trade on PAPER**: Cowork Monte Carlo at 70% WR regression scenario gave median +$13 / 95% CI [-$90, +$116]. Wait for n ≥ 100.
- **BTC RS entry-price bucket filter** (e.g. keep only entries in `[0.70, 0.80) ∪ [0.90, 1.00)`): bucket sizes are n ≤ 17, too thin to trust. Clean cut is safer.
- **Disable UP-side RS on PAPER too**: would lose monitoring data. Reconsider after 100 more PAPER UP-RS trades.

### LIVE rollout plan (deferred ~2 weeks per user)
When LIVE capital is available, follow Cowork's gated rollout:
1. Add `("ETH", "15m", "resolution_scalp")` to multi-live argv.
2. Watch for 20 LIVE trades. Pass: WR ≥ 70% (≥14 wins of 20).
3. Continue to 50 LIVE trades. Pass: WR ≥ 70% AND cumulative PnL > $0.
4. Then add `("SOL", "15m", "resolution_scalp")` to multi-live argv. Same gates.
5. Throughout, never enable BTC RS or UP-side RS on LIVE.

### Architecture clarifications discovered during investigation
- **CLAUDE.md's claim "LIVE follows PAPER entries via signal-mirror files (v1.8)" is stale.** No signal-mirror files exist in the codebase. PAPER and LIVE are fully independent processes; each runs its own per-(asset, window, strategy) thread and makes its own decisions via the same `signal_5m.py` functions. The selection of *which* strategies run on LIVE vs PAPER is purely an orchestration decision (multi-live argv vs multi-loop argv).
- **Position size discrepancy**: PAPER trades.csv shows `size_usd = 15.0` because `engine_5m.py:37` hardcodes `POSITION_SIZE = 15.0`. Cowork's $15-not-$5 correction was right. All PnL projections in Cowork's report are at $15 — divide by 3 for LIVE-equivalent.
- **`LIVE_MAX_DAILY_LOSS_USD` drift**: laptop `.env` has 50.0; CLAUDE.md says 15.0. Not a v1.23 issue but worth flagging.

### 30-day projection (Cowork Scenario B, "current PAPER + drop all BTC RS + drop UP-side RS")
At PAPER $15/trade: **+$649/30d**, EV/trade +$1.41, bootstrap 95% CI [+$0.22, +$2.58].
At LIVE-equivalent $5/trade: **+$216/30d**.
*Caveat: Cowork explicitly notes the lower CI bound straddles zero — even after the cuts, the bot is not provably profitable. Point estimate is positive.*

### Caveats (do not skip — verbatim from Cowork)
- 3-day RS window. The "DOWN edge persists across both halves" finding is across 2 days, not 2 weeks.
- Bootstrap CIs straddle zero on the low end. Point estimate is positive.
- No multiple-comparison correction. ~30 sub-strategy tests run; Bonferroni at section level (α=0.01) only marginally clears for the headline z=2.43 result.
- v1.22 ETH filter is in-sample on this dataset.

### Files changed
- `src/bot/signal_5m.py`
- `src/bot/version.py`
- `main.py`
- `PATCH_HISTORY.md`

### Reference documents
- Prompt: `PolyData/COWORK_COMPREHENSIVE_2026-04-25.txt`
- Reply: `COWORK_REPLY_2026-04-25.md`

---

## v1.22 — 2026-04-24
**Cowork ETH deep dive — BTC→ETH momentum continuation reframing**

Cowork analysis of 214 ETH mean-reversion trades (2026-04-24) revealed that ETH's profitable pattern is not symmetric mean-reversion — it's **BTC→ETH momentum continuation**. Two non-contiguous cross-window zones drive all the edge, with a "dead zone" in the middle where there's no BTC impulse to ride.

### The finding
- `cw ∈ [-0.10, -0.02]`: BTC just fell ~0.05% → ETH DOWN on Polymarket wins **77%**
- `cw ∈ [+0.05, +0.10]`: BTC just rallied ~0.05–0.10% → ETH UP wins **79%**
- `|cw| < 0.02`: no BTC impulse → WR collapses to ~40%, -$86 on 20 trades

The global cross-window filter `[-0.15, +0.02]` (BTC-tuned) was blocking 34 profitable positive-side ETH trades while allowing the dead zone. Replacing it for ETH with the union `[-0.10, -0.02] ∪ [+0.03, +0.10]` is the big win.

### Changes (ETH-15m only)
1. **Cross-window filter**: union `[-0.10, -0.02] ∪ [+0.03, +0.10]` (skips global filter for ETH). Scenario C backtest: n=98→75, WR 53.1%→72.0%, PnL +$23→+$306, Welch p=0.012.
2. **Dead-zone skip `[0.38, 0.39)`**: 42 trades, 38% WR, -$68. ETH UP in this specific band is 25% WR, -$92 on 20 trades.
3. **Spread cap 0.03**: eliminates the 0.03–0.05 spread tail (25% WR, -$36 on 8 trades). Free removal, no downside.

### Rejected from Cowork's options (with reasoning)
- **Tighten to 10s**: Welch p=0.68 once Scenario C is applied — timing edge was a proxy for "BTC impulse still fresh," which C already captures.
- **Floor to 0.39**: drops below 5 trades/day constraint.
- **ETH DOWN restriction**: UP/DOWN asymmetry is noise (p=0.82) once price band controlled.
- **`pnl_today ≤ -$10` skip**: would skip +$116 of ETH late-day recovery trades — counterproductive for ETH specifically.
- **ETH-only `soft_last5` regime skip**: deferred. Add only if W15-style regimes recur post-v1.22.

### BTC and SOL filters unchanged
BTC and SOL continue to use the global `CROSS_WINDOW_MIN / MAX` envelope. This change is ETH-only.

### 30-day projection
+$612 (v1.22) vs +$47 (v1.21 baseline), holding per-day trade rates constant.

### Caveats
- Cowork saw 207 trades, live dataset has 214 — 7-trade gap. Distributions match.
- n=34 for `[+0.05, +0.10]` band is thin — individually p=0.126. The union is what's significant.
- Sample covers one W15 (trending) + one W16 (ranging) cycle. Two more weeks of live data before declaring final victory.

### Files changed
- `src/bot/signal_5m.py`
- `src/bot/version.py`
- `PATCH_HISTORY.md`

---

## v1.21 — 2026-04-22
**Cowork Scenario B filters — 582-trade analysis**

Three changes to `signal_5m.py` derived from 582 PAPER mean-reversion trades (2026-04-04 to 2026-04-22). Backtest delta: +$419, expected WR 52.6% on 312 trades vs 43.3% on 582 baseline.

### Changes
1. **Hard-disable BTC DOWN** — negative EV across all price bands (t-test p=0.028, 95% bootstrap CI entirely negative). Lost −$327 on 161 trades. Loses even in ranging weeks (W16: 48.8% WR, −$85) — structural, not regime-dependent. BTC's upward drift makes cheap DOWN tokens a value trap.
2. **BTC-15m floor raised 0.35→0.38** — the 0.35–0.38 band is a dead zone: 22.4% WR, −$199 on 49 trades. BTC UP 0.38–0.41 is the profitable bucket (56% WR, +$50 on 78 trades).
3. **SOL-15m floor added at 0.33** — 0.28–0.32 SOL band has n=5 trades (too thin to trust). 0.32–0.35 is the main profitable SOL bucket.

### What did NOT change
- ETH floor stays at 0.35 — ETH's 0.35–0.38 band is its *best* (63.6% WR, +$131). A uniform 0.38 floor would destroy +$131 of ETH edge.
- Resolution scalp (v1.20) unchanged.
- Cross-window, spread, CLOB, and all other existing filters unchanged.

### Next step (v1.22)
Regime skip rule after 100 trades under v1.21: `recent_soft_rate_last5 ≥ 0.6 OR daily_pnl_prior ≤ −$10`. AUC 0.705 walk-forward validated. Deferred: needs state tracking + at least 100 OOS trades to re-calibrate threshold.

### Files changed
- `src/bot/signal_5m.py`
- `src/bot/version.py`
- `PATCH_HISTORY.md`

---

## v1.20 — 2026-04-20
**Resolution-edge scalp — Cowork Phase 2 (Strategy #4)**

New parallel strategy running alongside 15m mean-reversion. PAPER only until validated.

### What it does
Fires in the **last 10–90s** of a 15m window. At that point Binance has near-determined the outcome but Polymarket pricing still lags. Entry when:
- `GBM implied_p_up > 0.75` AND `up_price < implied_p_up − 0.05` → BUY UP
- `GBM implied_p_up < 0.25` AND `down_price < (1 − implied_p_up) − 0.05` → BUY DOWN

Holds to `force_exit_time` (~5s remaining). No TP, no SL, no soft exit.

Synthetic backtest (Cowork, 3,212 windows): 79% WR, +$0.72/trade @$5, ~8 trades/day/asset.

### Files changed
- `src/bot/signal_5m.py` — `should_enter_resolution_scalp()` + `import math, os`
- `main.py` — resolution_scalp branch in `run_5m_loop`; soft_exit_secs=0 + hard_stop_max=0 override; 6-strategy default config for multi-loop
- `src/bot/version.py` — v1.20

### Env overrides
- `RESSCALP_IMPLIED_MIN` (default `0.75`) — lower to capture more trades
- `RESSCALP_GAP_MIN` (default `0.05`) — minimum price gap to entry

### Deploy notes
- PAPER (`multi-loop`) picks up automatically on next restart — adds 3 new threads
- `multi-live` unchanged — resolution scalp NOT added to live until PAPER shows WR ≥ 70% on 100 trades
- Success criterion: WR ≥ 70%, avg PnL ≥ +$0.40 @$5 after 100 PAPER trades

### Phase 1 (edge gate) status at deploy
- 90 OOS trades, 40% WR — below 55% target
- Diagnosis: strong trending DOWN market Apr 19-20 (DOWN bets 33% WR vs UP 44%)
- Decision: regime-driven, not code bug — continue collecting data

---

## v1.19 — 2026-04-19
**Cowork 2026-04-19 analysis deploy — Strategies #1 (fair-value edge gate) and #8 (soft daily loss stop)**

Phase 1 of the `cowork_new_strategies_2026-04-19.md` deployment plan. Phase 2 (Strategy #4 resolution-edge scalp) deferred until Phase 1 has ≥100 out-of-sample trades; Phase 3 (Strategy #5 edge-proportional sizing) deferred until Phase 1 has ≥200 trades.

### Strategy #1 — Binance fair-value edge gate (15m MR entries)
- `main.py` (`run_5m_loop`, inside the MR branch): compute GBM implied P(our side wins) from Binance spot + trailing 15-min realized σ + seconds remaining; skip entry when `implied_p − entry_price < EDGE_GATE_MIN`.
  - Reuses the `_std` already computed for the realized-vol filter (no extra Binance load).
  - Per-2s-bar σ converted to per-second via `σ/√2`, then scaled to τ via `σ·√τ`.
  - Pass-through on insufficient data (short history, missing btc prices, numerical issue).
- Env: `EDGE_GATE_MIN` (default `0.0`). Set to a negative number to loosen, positive to tighten.
- Backtest (448 paper trades Apr 8–19, rescaled to $5/trade): +$0.11 → +$0.42 avg, Sharpe 0.55 → 1.74, N dropped ~50%.

### Strategy #8 — Soft daily loss stop (LIVE only)
- `src/bot/circuit_breaker.py`: add `is_soft_stop(threshold_usd)` — non-tripping check against today's realised P&L.
- `main.py` (entry gate at `cb_open` computation): block new LIVE entries when `cb.is_soft_stop($10)` while still managing open positions. Hard $50 circuit breaker unchanged.
- Env: `LIVE_DAILY_SOFT_STOP_USD` (default `10.0`). Set `<=0` to disable.

### Files touched
- `main.py` (2 blocks: vol+edge gate, entry-gate soft-stop)
- `src/bot/circuit_breaker.py` (+`is_soft_stop`)
- `src/bot/version.py` (v1.19)

### Risks / things to watch
- Edge gate relies on Binance spot + `btc_at_window_start` being populated; if the Binance feed lags or restarts mid-window, the gate passes through rather than blocking — no worse than today.
- Backtest is re-labeling on training data; true OOS edge likely 0.5–0.7× headline.
- Soft stop is LIVE-only (PAPER has no `cb`); PAPER continues data collection unchanged.

### Deploy steps
1. `git pull` on laptop
2. Ask user before restarting `PolyBot` + `PolyDashboard`
3. Verify first LIVE entry in logs shows `[EDGE] ... OK` line

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
