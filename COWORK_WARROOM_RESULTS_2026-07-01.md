# Cowork war-room results — 2026-07-01

All numbers computed this session from `cowork_snapshot/` (23/23 files verified readable).
Every figure below is reproducible from the listed source file.

## Headline — read this before anything else

**The live fade operation is not making money. Realized ROI on real fills is -1.6%
(533 resolved fills, $6,110 staked, 2026-05-16 → 2026-07-01, `live/live_results.csv`).**
The +101%/+110% OOS backtest did not survive contact. This is not a data error and not a
regime change — the mechanism is now understood and fixable (below). Under your own rule
("progress = realized edge that survives real money"), continuing to run the current config
is going backward at ~$15/week. The good news: the fix is validated on your own data and
deployable this week.

## Why the backtest edge vaporized (decomposition, all measured)

1. **The raw fade edge is spread-sized.** At signal prices the 1,572 resolved live fade
   signals return +8.5% per $1. Add a fill penalty: +2¢ → +2.7%, +3¢ → +0.2%, +5¢ → -4.4%.
   The OOS backtest filled at the faded wallet's own trade price — a price you structurally
   cannot get (you arrive after them, on the opposite side of the book).
2. **Measured real fill cost is ~1.7¢ mean** (fill price vs signal price, 533 matched
   fills). That alone eats most of the raw edge.
3. **Selection made the rest negative.** The entry-price floor (`skip_entry_price_floor`,
   445 skips) blocks exactly the band where the edge lives — entries ≤0.35 were the only
   profitable fills (+17.8%, n=21) and the strongest signal band. Fills instead concentrated
   in 0.50–0.65 (41% of capital, -7.9%).
4. **One toxic target ate 17% of capital.** Wallet `0x47138dc1…` (119k trades, -11.3%
   lifetime ROI): 90 fills, $1,051 staked, **-10.4%**. Fading a high-frequency wallet that
   loses only 11% gives you ≤11% gross minus spread ≈ 0. Signal-level confirms: targets with
   >10k lifetime trades are **-22.4%** fill-adjusted (n=50); ≤100 trades are **+9.0%** (n=278).

## What IS validated and deployable

### SHIP #1 — Model-edge gate (replaces "fade everything above the floor")

Bet only when the win-prob model disagrees with the market by ≥0.10, on whichever side is
cheap. Validated on `gamedata/feasibility_joined.parquet` (1,151 resolved CS2 series,
model-vs-market-vs-outcome), **with 3¢ friction baked in**:

| threshold | n | ROI @2¢ | ROI @3¢ | se |
|--:|--:|--:|--:|--:|
| 0.00 | 1151 | +0.6% | -2.3% | 4% |
| 0.05 | 713 | +7.1% | +3.7% | 5.5% |
| **0.10** | **393** | **+25.1%** | **+20.6%** | **8.5%** |
| 0.15 | 207 | +40.8% | +34.8% | 14% |

Monotonic dose-response = signature of real edge; matches the independent OOS backtest in
`esports_model/REPORT.md` (+20.2%/+38.5% at 0.05/0.10 with 2¢). Triple-confirmed by the
**live shadow A/B** (n=97 resolved, late June, real signals): all fades +46% raw, Elo-pass
+62.7% (n=34), shadow-model-pass **+79.2%** (n=26); the 7 trades Elo passed but the model
rejected returned **-17.8%**. Caveat: feasibility_joined may overlap the model's training
window — the REPORT.md backtest is the strictly-OOS reference; live shadow is fully OOS.

**Deployable spec:**
- Trigger: any fade/follow signal OR any book poll on a matched CS2 series market.
- Gate: `model_edge = model_p(our_side) − best_ask ≥ 0.10` (use the v2 predictor,
  `esports_model/src/predict.py`; fall back to Elo only when v2 is `ok:False`).
- Remove the entry-price floor for gated bets; allow entries down to 0.10. Low price +
  model confirmation is the *best* segment, not the worst (underdog side carries the ROI).
- Keep `skip_single_map`? No — map markets are fine if map-Elo edge ≥ 0.12 (higher bar,
  weaker model).
- Kill LIVE for any signal failing the gate. Expected volume: ~34% of matched markets
  cleared thr 0.10 historically — roughly 15–40 bets/week at current market flow.

### SHIP #2 — Fix the wallet target list (1-line config change, do it today)

- **Drop all targets with >10,000 lifetime trades** (the 0x47138dc1-class whales): they are
  -22.4% fill-adjusted on your own signals.
- Prefer wallets with lifetime ROI in **[-30%, -15%]** and <1,000 trades: +24.1%
  fill-adjusted on live signals (n=64 — thin, so treat as tilt, not proof).
- Follow-mode stays off (25 fills, -9.4%; too thin to judge, not worth capital under the clock).

### SHIP #3 — Maker-first execution (saves the 1.7¢ that is most of the raw edge)

Post GTC at the signal price; escalate to taker (+1¢, per v1.9 lesson) only when
`model_edge ≥ 0.15`. At a 3–8% net edge per bet, 1.7¢ on a ~$0.50 token is ~3.4% ROI —
execution alone roughly doubles the net edge. Risk: adverse selection on maker fills;
monitor maker-fill WR vs taker-fill WR for the first 100 fills.

### SHIP #4 — Quarter-Kelly sizing (multiplier on everything above)

Binary market, fill price `p`, model prob `q`:
`stake = bankroll × min(0.25 × (q−p)/(1−p), 0.025)`, floor $1, cap additionally at 25% of
book depth within 1¢ of ask. Replayed on the 393 gated bets (order-independent,
multiplicative): **$1,000 → $5,421 vs $2,216 flat-$15** — 2.4× the growth of flat sizing,
never risking >2.5% per bet. Do NOT deploy sizing before the gate: Kelly on a -1.6% edge
just loses money faster.

## Verdicts — one line each

| Avenue | Verdict | Basis |
|---|---|---|
| 1. Scale wallet fade as-is | **DEAD as-is → redirect into gated version (Ship #1+#2)** | -1.6% realized, 533 fills |
| 1b. Follow winners | dead-redirect | -9.4% on 25 fills; signal-level flat |
| 4. Kelly sizing | **SHIP after gate** | 2.4× growth on gated stream |
| 2. GRID props | iterate — model targets exist, **zero price history to backtest** | prematch_prices: 3 prop rows total |
| 5. Consistency arb | iterate — same blocker, live-scanner only | no concurrent multi-market prices captured |
| 6. In-play repricing | not touched this session | needs bo3 live data review |
| 3. More games (Dota etc.) | behind price capture; listing flow also shrinking (6.5k→1.5k mkts/wk since mid-June) | clob market counts |
| 7. Model v2 tier features | iterate — after Ship #1 is live | shadow already ≥ Elo |
| 8. Sports | not touched this session | — |
| 9/10. Price capture | **PREREQUISITE** for props/arb/LoL backtests — highest research ROI | see below |

## The one infrastructure task that unblocks three avenues

Log best bid/ask + depth for **every** matched esports market (series, maps, handicaps,
totals, kills) every 60s from the bot's existing poll loop into a parquet/jsonl. Cost: ~1h
of wiring. It unblocks: prop model backtests (avenue 2), series-vs-map consistency arb
(avenue 5), LoL edge validation (153 obs so far, median depth $324, median model_edge
**-0.07** on fade side = LoL fade confirmed thin; only model-gated LoL is worth capital).

## Ranked pipeline

1. **Today:** Ship #2 (target-list filter) + pause ungated fades on LIVE.
2. **This week:** Ship #1 (model-edge gate ≥0.10, maker-first) → LIVE at flat $5–15.
3. **When gate is live:** Ship #4 (quarter-Kelly, cap 2.5%).
4. **Parallel:** price-capture logger → unlocks props/arb/LoL backtests next week.
5. **Next Cowork pass:** first 100 gated fills vs this session's +20% projection;
   prop (totals/map-winner) models on captured prices.

## Killed and why

- Ungated wallet fade at taker prices: edge (~+8.5% raw) ≈ spread (+3¢ ≈ -8.3%) → net ~0.
- Fading high-frequency whales: structurally can't clear spread (their loss rate is too shallow).
- Follow-the-winners as standalone: no positive evidence in 25 live fills or signal-level data.
- Prop/arb *backtests* this session: impossible offline — no historical prop prices exist.

*Not financial advice; sizing/deployment decisions are yours. All PnL figures are from your
own logged data and small samples where noted — the 8.5% se on the headline gate number
means real-world results from +4% to +37% are consistent with the evidence.*
