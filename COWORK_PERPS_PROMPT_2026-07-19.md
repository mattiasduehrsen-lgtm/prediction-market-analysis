# Cowork mission — perps funding-carry study (prepared 2026-07-19)

> **Prompt:** You are Cowork working in `prediction-market-analysis`. Mission:
> determine whether a retail-scale perpetual-futures edge exists for this
> project, using ONLY the data in `cowork_snapshot/perps/` (your sandbox has no
> API egress — everything you need is pre-fetched). House rules apply: measure,
> pre-register, and kill without sentiment. Read `CLAUDE.md` §house-rules and
> `COWORK_EDGE_AUDIT_2026-07-15.md` §7 for the project's epistemics before
> starting. **This is explicitly a NON-esports side lane** (user-proposed
> 2026-07-19; esports remains the primary mission).

## Framing — what is and isn't plausible here

This project has measured and killed every *prediction* edge it ever touched;
perps are the sharpest venue on earth and directional signals are presumed dead
on arrival — do not spend effort there. The candidate that deserves real
measurement is **funding-rate carry**: the structural payment stream between
perp longs and shorts. It is a risk premium, not a prediction — the category of
thing that can genuinely persist. The questions are whether it survives fees,
drawdowns, and our bankroll, and whether any secondary structure (cross-venue
divergence) adds anything.

## Data (all in `cowork_snapshot/perps/`)

- `binance_funding.parquet` — 13,140 rows: 2 years of 8-hour funding events for
  {BTC,ETH,SOL,XRP,BNB,DOGE}USDT perps (`symbol, ts, rate, mark`).
- `hyperliquid_funding.parquet` — 35,040 rows: 1 year of HOURLY funding for
  {BTC,ETH,SOL,HYPE} (`coin, ts, rate, premium`). Note the venue pays hourly
  (8760/yr) vs Binance's 3/day.
- `binance_basis.parquet` — 2 years daily closes, spot AND perp per symbol
  (`symbol, kind∈{spot,perp}, ts, close, volume`) → basis series.
- Refetch/extend anytime via `analysis/perps_data_fetch.py` (dev machine).

## Questions, in priority order

1. **Delta-neutral funding carry** (long spot / short perp, same venue): realized
   gross and NET APR over the sample, using honest cost assumptions stated up
   front (taker fees both legs both directions ~5–10bp round trip per venue,
   spread, no leverage beyond 1x notional on the short). Include: drawdown
   profile when funding flips negative (bear regimes), time-under-water,
   per-asset and portfolio versions, and regime dependence (funding is famously
   feast/famine).
2. **Cross-venue funding divergence** (Binance vs Hyperliquid, overlapping
   coins/period): does shorting the high-funding venue vs longing the low one
   add net-of-fees return beyond single-venue carry, at what rebalance
   frequency, and how often does the divergence exceed the round-trip cost?
3. **Threshold/timing variants** — only enter carry when funding > X: does any
   simple rule beat always-on after costs, split-half validated (rule chosen on
   first half of the sample, confirmed on second)? No optimizer sweeps beyond a
   small pre-declared grid.
4. **Anything else you find** must survive the same split-half + cost honesty.

## Hard constraints on the deliverable

- **Bankroll honesty:** the project wallet is ~$313 (pUSD, on Polymarket).
  Deploying to perps means moving capital to Binance/Hyperliquid — a user
  decision with custody/venue risk. Your report MUST state the minimum bankroll
  at which the best surviving strategy clears $1/day net, and the realistic
  $/day at $300 / $1k / $5k. If the answer is "not worth operating below $X",
  say so in the verdict line.
- **Risk honesty:** liquidation mechanics on the short leg (funding accrues to
  the position that gets squeezed in rallies), venue risk, and the historical
  worst drawdown of the strategy in the sample. No "APR" without its drawdown.
- **Kill-friendly verdicts:** a clean KILL with numbers is a first-class
  deliverable. If carry survives, end with pre-registered Phase-0/1 gates in
  the house style (paper/sim first, micro-live only after explicit user
  approval, frozen KILL/SCALE triggers) — do NOT propose immediate deployment.
- Reproduction script committed as `analysis/_perps_study_<date>.py`, runnable
  on the snapshot alone. Results doc: `COWORK_PERPS_RESULTS_<date>.md`.
