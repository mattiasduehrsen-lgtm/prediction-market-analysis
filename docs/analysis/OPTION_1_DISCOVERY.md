# Option 1: Longer-Horizon Polymarket Markets — Discovery

## Headline

**Yes — longer-horizon Up/Down markets exist on Polymarket for BTC/ETH/SOL (1h, 4h, daily), with confirmed slugs and live liquidity.** The 4h markets use the same `{asset}-updown-4h-{epoch}` pattern as the existing 5m/15m code (a clean drop-in extension). Liquidity is meaningful but smaller than 15m: BTC-4h ~$5–13k, ETH-4h ~$4–10k, SOL-4h ~$3–6k per market — workable for the bot's $5/trade size, marginal at $25. Hourly and daily exist but use a different (date-formatted) slug pattern that requires new discovery code. **Recommendation: small experiment on 4h markets first** — minimal code change, the most natural extension, and a real test of whether longer holding windows produce a different edge profile before committing to a hourly/daily rewrite.

---

## What the existing code does

Market discovery lives in `src/bot/market_5m.py`. The window length is **parameterized** (good news), but support is gated by a small allow-list:

- `WINDOW_SECONDS` dict (`market_5m.py:25-28`) maps `"5m"→300`, `"15m"→900`. **Add a key here and the window math just works.**
- `SLUG_PREFIXES` (`market_5m.py:31-44`) maps `(window, asset) → slug prefix`. The format is hard-coded as `{asset}-updown-{window}` in the per-asset list, but `fetch_market` falls back to that exact string template at line 144 if a `(window, asset)` pair is missing — so any `{asset}-updown-{window}-{epoch}` slug works for free.
- `get_window_start(window)` (`market_5m.py:130`) computes `(now // ws) * ws` from `WINDOW_SECONDS`. Works for any window where Polymarket's epoch boundaries align with `epoch % window_seconds == 0`. **Confirmed for 4h: epoch `1778414400 % 14400 == 0`.**
- `fetch_market` tries offsets `(0, +1, -1)` around the current window-start — generic.

**Slug-format verification (live API calls):**
- `GET https://gamma-api.polymarket.com/events?slug=btc-updown-4h-1778414400` → `liquidity=$5,247`, `volume=$12,864`
- `GET .../events?slug=eth-updown-4h-1778414400` → `liquidity=$10,172`, `volume=$4,104`
- `GET .../events?slug=sol-updown-4h-1778414400` → `liquidity=$3,361`, `volume=$5,734`
- `GET .../events?slug=btc-updown-1h-1778425200` → empty (1h does NOT use this pattern)
- `GET .../events?slug=bitcoin-up-or-down-may-10-2026-11am-et` → `liquidity=$6,737`, `volume=$19,703` (1h uses human-date slug)

**Strategy entry/exit thresholds** in `market_5m.py:46-77` are documented as "5m" constants but are loaded by both 5m and 15m signal paths — they are **not** automatically right for 4h, see below.

**Routing:** `main.py` `multi-loop`/`multi-live` argv accepts `ASSET:WINDOW:STRATEGY` triples (e.g. `BTC:15m:mean_reversion`). To run 4h, you'd pass `BTC:4h:mean_reversion` once `WINDOW_SECONDS["4h"]=14400` is added.

---

## What Polymarket offers (from web research)

| Window | Exists | Slug pattern (API) | Sample liquidity / 24h volume | Notes |
|---|---|---|---|---|
| 5m   | Yes | `{asset}-updown-5m-{epoch}` | (already in code) | currently used |
| 15m  | Yes | `{asset}-updown-15m-{epoch}` | (already in code) | currently used |
| **1h** | **Yes** | `bitcoin-up-or-down-{date}-{time}-et` (also `ethereum-`, `solana-` etc.) | BTC: ~$6.7k liq / $19.7k vol per market | **Different slug format — new discovery code needed.** Confirmed via `bitcoin-up-or-down-may-10-2026-11am-et`. Assets: BTC, ETH, SOL, XRP, DOGE, HYPE, BNB. |
| **4h** | **Yes** | `{asset}-updown-4h-{epoch}` | BTC ~$5–13k, ETH ~$4–10k, SOL ~$3–6k | **Same family as existing 5m/15m — trivial code extension.** Verified live via gamma-api. |
| **Daily** | **Yes** | `bitcoin-up-or-down-on-may-9-2026` (human-date) | $374k+ volume on the May 9 BTC market (much higher than 4h) | Resolves noon-ET to noon-ET via Binance 1m candles. Different slug format. |
| Weekly | Unconfirmed | — | — | No evidence found in surface search; likely doesn't exist as a discrete `updown` product. Polymarket has weekly *strike* markets but not weekly Up/Down. |

**Sources (verified):**
- BTC 1h: https://polymarket.com/event/bitcoin-up-or-down-april-27-2026-8pm-et
- ETH 4h: https://polymarket.com/event/eth-updown-4h-1771664400/eth-updown-4h-1771664400
- BTC daily: https://polymarket.com/event/bitcoin-up-or-down-on-may-9-2026
- Hourly hub (lists BTC/ETH/SOL/XRP/DOGE/HYPE/BNB): https://polymarket.com/crypto/hourly
- Gamma API: https://gamma-api.polymarket.com/events?slug={slug}

**Liquidity caveat:** Per-market liquidity figures above are *current snapshots*, not averages. Daily markets carry far more $ volume than 4h, but each daily window only resolves once per day → only ~1 entry opportunity per asset per day. 4h yields 6 windows/day × 3 assets = 18 windows/day, comparable to or below the current 15m count (96 × 3 = 288).

**$5/trade tradeability:** Comfortable on 4h (slip ~1¢ at $5 against a $5k book). Daily at $25 is also fine. Hourly at $5 likely OK. **$25 trade size starts to push slippage on 4h SOL** (only $3k liquidity).

---

## Engine adaptation cost

**For 4h (cheap):** ~30–60 LoC across 3-4 files. Specifically:

1. `src/bot/market_5m.py:25` — add `"4h": 14400`, `"1h": 3600` to `WINDOW_SECONDS`. Add the slug prefixes to `SLUG_PREFIXES`. **(~10 lines)**
2. `main.py:301-310` — extend the window-conditional logic that currently branches on `"5m"` vs `"15m"`:
   - `soft_exit_secs` (line 305): currently `115 if "5m" else 420` — needs explicit 4h value (~30 min before close?)
   - `hard_stop_max_remaining` (line 310): currently `240 if "15m" else inf` — re-derive for 4h
   - `window_duration` (line 807): currently `900 if "15m" else 300` — replace with `market.window_seconds` (already a property — refactor opportunity)
   - `len(btc_history) >= 10` Chainlink-history gate (line 922): re-tune for 4h cadence
3. `src/bot/signal_5m.py` — currently has hard-coded `if asset == "X" and window == "Y"` branches (lines 97, 118, 139, 152). For 4h these will fall through to default behaviour. **Probably wrong** — see TP/SL section.
4. `main.py:1148` `multi-live` default config — add `BTC:4h:mean_reversion` etc.
5. Per-window state (the `reset_window` machinery in `live_engine_5m.py`) is already keyed by `(asset, window, strategy)` so it parallel-runs without conflict.

**Risk areas:**
- The `chainlink_feed.py` history buffer is sized assuming 5m/15m cadence; at 4h windows the history may not retain enough samples for the realized-vol filter (`main.py:370` extended buffer to 450 samples for 15m).
- Cowork-derived constants (ENTRY_MIN=0.32, ENTRY_MAX=0.40, MIN_LIQUIDITY=15k) were tuned on 15m data. **Do not assume they transfer.** MIN_LIQUIDITY=15k would reject every 4h market in my snapshot — must lower for 4h.
- The "force_exit at 5s remaining" pattern is right for 5m/15m. For a 4h market, exiting 5s before resolution gives no benefit; could be 30–60s without hurting.

**For hourly + daily (expensive):** Different slug format means a new code path in `market_5m.py` — discovery via `bitcoin-up-or-down-{Mon}-{D}-2026-{Hh}am-et`. Date string formatting in non-padded English-month slugs (`may-10` not `05-10`, `9am` not `09am`) is fiddly and locale-fragile. Add ~80–120 LoC and a unit test before trusting it.

---

## TP/SL re-tuning needs

**Almost certainly yes — current thresholds are 15m-tuned and won't transfer cleanly.**

- `ENTRY_MIN=0.32` / `ENTRY_MAX=0.40` were Cowork-derived on 15m mean-reversion data. The intuition is "buy when the market has skewed away from 50/50 because the underlying just moved." On a 4h window, a mid-window 0.35 quote means something different — the underlying has moved a meaningful amount and has 2+ hours left to mean-revert. The *band* probably exists but its location and width need re-derivation.
- `TAKE_PROFIT=0.92` is replaced at runtime by `tp_optimizer.compute_take_profit(entry_price)`. That function was fit on 5m/15m. For 4h, time-decay of the option-equivalent is much slower — same logic likely says hold for higher TP. Should refit.
- `PAPER_STOP_LOSS_PCT=0.10` was raised from 0.04 specifically because "15m markets need room for mean reversion." On 4h the room needed is *bigger*, so 0.10 is probably still too tight. My gut: 0.15–0.20 SL on 4h. Test in PAPER first.
- `BTC_CRASH_PCT_THRESHOLD=0.10` (max % move in-window) — for 4h the natural in-window range is much larger, so 10% rejection threshold becomes nearly never-triggered. Probably want 5% or asset-specific.
- `SOFT_EXIT_SECS` (115s for 5m, 420s for 15m). Pro-rata for 4h would be ~6720s (1h 52m), but the underlying exit logic's intent was "if reversion hasn't happened by now, give up." On 4h that intuition probably caps at 1h before close (3600s).
- `MIN_LIQUIDITY=15000` — must lower; current 4h books are ~$3-10k.

**Bottom line:** every numeric constant in `market_5m.py:46-77` and the ENV file needs to be re-validated. None of them should be assumed right for 4h.

---

## Edge profile speculation (longer windows)

Reasons to be optimistic:
- **Wider TP–SL gap:** at 4h the underlying can move far enough that mid-window prices like 0.30/0.70 happen organically and reflect *real* information, not microstructure noise.
- **Lower fixed-cost burden:** Polymarket fees + spread cost is a constant per round-trip. At 4h hold the per-hour cost is 1/16th of a 15m trade. If alpha-per-hour is even slightly lower than alpha-per-hour on 15m, the *net* could still be positive when 15m's was negative.
- **Different participant mix:** the 15m markets attract HFTs and bots running similar mean-reversion strategies (the no-edge ML result on 700 trades is consistent with crowded). 4h-and-up likely have more directional retail and less HFT competition. Less crowding = more mispricing.

Reasons to be cautious:
- **Lower trade count:** 4h gives ~6 windows/day/asset = 18/day. Reaching the 150-trade Cowork milestone takes ~10 days at full deployment, vs ~8 hours at 15m. Slow feedback loop.
- **Resolution risk:** longer windows mean more time for Polymarket / Chainlink / Binance to do something weird. The 15m settlement bugs we've already seen would manifest worse at 4h.
- **Capital tie-up:** $5 × open positions × 4 hours = significant lockup vs. 15m where capital cycles 96 times/day. Less of a concern at $5 size, more so if scaling.
- **MIN_LIQUIDITY problem:** at 4h liquidity floors of $3–6k, a $5 entry is fine but exit-FOK may walk the book by 2–3¢. SL slippage could be larger in absolute %.

The 700-trade ML null result is a strong signal that 15m mean-reversion isn't learnable — so the prior on "longer windows are different" should be modestly positive, not strongly so. Could just as easily find that 4h has the same null.

---

## Recommendation

**Small experiment first: PAPER-only 4h on all three assets, two-week run, no LIVE deployment.**

Specifically:

1. Add `"4h": 14400` to `WINDOW_SECONDS` and `SLUG_PREFIXES`. (~15 LoC; same family as existing code.)
2. Replace the `"5m"`/`"15m"` literals with `market.window_seconds` references where possible. Keep 5m/15m branches that have data-derived constants.
3. Add `BTC:4h:mean_reversion`, `ETH:4h:mean_reversion`, `SOL:4h:mean_reversion` to `multi-loop` defaults (PAPER) only — do NOT touch `multi-live`.
4. Lower `MIN_LIQUIDITY` to $2,000 for 4h (env-overridable per window or just hardcoded conditionally).
5. Loosen entry band to `[0.28, 0.45]` and `STOP_LOSS_PCT=0.18` as starting guesses.
6. Run for 2 weeks → ~250 4h trades across 3 assets → enough for first Cowork pass.
7. **Do not adapt 1h or daily yet.** Their slug format is different and they deserve a separate ticket once 4h shows signal-or-no-signal.

**Go signal:** if 4h PAPER WR > 52% and PnL/trade > 5¢ over 200+ trades, build a thinner LIVE deployment.
**No-go signal:** if 4h PAPER looks like 15m (45-50% WR, near-zero edge), abandon longer-horizon Up/Down entirely and look at strike markets or a different product.

**Do not pursue hourly/daily yet** — different slug format = real engineering work, and we want the cheap test result first.
