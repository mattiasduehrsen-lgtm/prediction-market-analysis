# Perps funding-carry study — results (Cowork Fable 5, 2026-07-19)

**Mission:** determine whether a retail-scale perpetual-futures edge exists for
this project (funding-rate carry, cross-venue divergence, threshold variants).
NON-esports side lane; esports remains primary. Snapshot-only —
`cowork_snapshot/perps/` (Binance 2y × 6 symbols 8h funding; Hyperliquid 1y × 4
coins hourly; Binance 2y daily spot+perp closes). All numbers reproduce via
`analysis/_perps_study_2026-07-19.py` on the snapshot alone. No bot code
touched, nothing restarted, LIVE untouched.

## Verdict line

> **KILL at this bankroll.** Funding carry is real — it is the one lane in this
> project's history that ISN'T a mirage — but at $313 it pays **1.3–4.5
> cents/day** net. The best surviving configuration (Hyperliquid carry) needs a
> **minimum ~$6,700 deployed to clear $1/day**, and ~$11k–21k on the safer
> variants. **Not worth operating below ≈$5,000 of capital the user is willing
> to custody on a crypto-exchange** — and that is a custody/venue decision, not
> an analysis result. No deployment proposed. Reopen conditions at the end.

---

## 1. Pre-registered design (frozen before any result was computed)

- **Trade:** long 1 unit spot / short 1 unit perp, same venue; short receives
  funding when rate > 0. **Capital basis: notional N requires 2N** (spot leg +
  1x short collateral; mission constraint, no cross-collateralization assumed).
  All verdict figures are **on capital** (= notional APR ÷ 2).
- **Costs per full open+close cycle** (% of notional): Binance base **35bp**
  (spot taker 10bp×2 + perp taker 5bp×2 + 5bp spread); sensitivities 20/50bp,
  plus the mission's optimistic 10bp. Cross-venue perp-perp (4 legs): base
  **23bp** (sens 15/35bp).
- **Q3 grid (frozen, 6 variants):** signal = trailing-7d mean funding
  annualized, lagged 1 event; enter>X / exit<Y for (X,Y) ∈ {always-on, (0,0),
  (5%,0), (5%,5%), (10%,0), (10%,5%)}. Choose on H1 (2024-07-20..2025-07-19),
  confirm on H2 (2025-07-20..2026-07-19). No other sweeps were run.
- Annualization: Binance 1095 events/yr; HL 8760/yr. Bootstrap: moving-block
  (7d blocks), 2000 draws.

## 2. Q1 — delta-neutral carry: it exists, and it is small

**Binance, 2 years, gross APR (CI = block-bootstrap 95%):**

| | gross APR notional | gross APR **capital** | net capital (always-on, 35bp) | % events rate<0 |
|---|---|---|---|---|
| BTC | 4.87% | 2.43% | 2.35% | 19% |
| ETH | 4.86% | 2.43% | 2.34% | 20% |
| DOGE | 4.85% | 2.42% | 2.34% | 27% |
| XRP | 3.44% | 1.72% | 1.63% | 32% |
| SOL | 1.25% | 0.63% | 0.54% | 39% |
| BNB | 0.37% | 0.19% | 0.10% | 11% |
| **Portfolio (6, eq-wt)** | **3.27%** [2.27, 4.38] | **1.64%** | **1.55%** | 27% |
| Portfolio BTC/ETH/SOL | 3.66% | 1.83% | 1.74% | 25% |

**Hyperliquid, 1 year:** BTC 6.73% [5.14, 7.98] notional (3.37% capital), ETH
7.05% [5.20, 8.34] (3.53%), HYPE 11.29% [9.35, 12.98] (5.65%), SOL 1.22%
(0.61%). HL pays a persistent ~3–4%/yr venue premium over Binance on the same
coins in the same window (Binance same-period BTC 3.50% / ETH 2.69% / SOL
−1.38%). That premium is compensation for venue risk, not free money.

**Regime dependence (the feast/famine the mission predicted):** quarterly
Binance gross APR (notional) ran **12–14% in 2024Q4** (the feast; the sample's
first half contains it), fell to **≈0–3% through 2026Q1–Q2** (the famine:
portfolio funding PnL spent **171 consecutive days under water, 2026-01-29 →
sample end**), with 2026Q3's first three weeks back at ~6–7%. H2-only portfolio
gross is **1.73% notional [0.60, 2.61]** — i.e. someone starting a year ago
earned **<1% on capital** before costs. Daily funding autocorr is high (0.75
lag-1d) — regimes are persistent, but see §5: timing still doesn't pay.

Costs barely matter for always-on (amortized one cycle: net moves 1.51→1.61%
across 50→10bp assumptions). The binding constraint is the gross level itself.

## 3. Risk honesty

- **Drawdown profile:** funding-only drawdowns are shallow but long — carry
  doesn't blow up, it starves. Max funding drawdown on capital: portfolio
  −0.30%, BTC −0.21%, SOL −1.31%, BNB −1.40%. Time under water: portfolio
  ~54% of the sample; BNB 92% (576 days); SOL 77%. Worst rolling-30d stretch:
  BTC −3.6% annualized, SOL −13.3%, i.e. months where you pay to hold the
  hedge.
- **Liquidation (the real tail):** the short leg at 1x collateral liquidates
  near +100%. Worst forward run-ups in the sample: **XRP +100% in 7 days,
  +442% in 30d** (Nov 2024); **DOGE +242% in 30d**; ETH +138% in 90d; BTC
  +48% in 30d / +84% in 90d. A passive 1x short on XRP/DOGE **would have been
  liquidated** — those carries are only survivable with active margin top-ups
  from the spot leg. BTC/ETH at 1x survived the whole sample but with
  uncomfortable margins. On split-custody HL carry (spot on Binance, short on
  HL — required for BTC/ETH since HL native spot for them is thin), top-ups
  cross venues and are NOT fast; this materially worsens the tail.
- **Basis:** perp trades ~4bp *below* spot on average (σ 2–5bp; worst 1-day
  widening 21bp) — entry actually captures a sliver; MTM noise immaterial at
  1x. Not a risk factor at this scale.
- **Venue risk:** unhedgeable and uncompensated at our size — exchange custody
  (the project wallet would move off Polymarket), and for the best number on
  the board (HYPE 11.3%) the risk is concentrated: newest venue, its own
  token, 1 year of history, premium likely decays as the borrow market
  matures.

## 4. Q2 — cross-venue divergence: DEAD

Aligned 8h buckets (HL hourly summed into Binance windows), BTC/ETH/SOL,
2025-07-20 → 2026-07-19, n=3,285:

- Median |Binance−HL| divergence: **0.45–0.54bp per 8h** vs 23bp round-trip
  cost → **0.00% of 8h periods clear the cost bar** (also 0.00% at 15bp).
- The divergence trade (position toward trailing 7d divergence): gross
  1.4–1.7%/yr on capital, **net NEGATIVE at base costs at every rebalance
  frequency tested** (8h: −1.4%; daily: −1.2%; weekly: −0.2%; weekly at
  optimistic 15bp: +0.3%/yr — noise). ~14–27 flips/coin/yr eat everything.
- The only real structure is the *persistent sign* (HL richer): captured
  better, with fewer legs, by simply doing carry ON Hyperliquid (§2). The
  perp-perp divergence trade adds nothing beyond single-venue carry. **DEAD.**

## 5. Q3 — threshold timing: DEAD (split-half, frozen grid)

Portfolio net APR on capital, 35bp/cycle:

| rule | H1 (choose) | H2 (confirm) | avg % in market |
|---|---|---|---|
| **always-on** | **2.23%** | **0.69%** | 100% |
| gt0 | 1.04% | −0.95% | 73% |
| gt5_exit0 | 1.87% | 0.23% | 56% |
| gt5_exit5 | −0.07% | −1.62% | 33% |
| gt10_exit0 | 1.55% | 0.29% | 24% |
| gt10_exit5 | 1.29% | −0.02% | 15% |

**No variant beat always-on on H1; H2 confirms the ordering.** Negative-funding
stretches are too shallow for exit rules to save more than the churn they cost.
(Consistent with high funding persistence: the signal "works" directionally but
the payoff for acting on it is smaller than two crossings of the book.) Also
note always-on itself decayed 2.23% → 0.69% H1→H2 — the famine, again. **DEAD.**

## 6. Bankroll math (the mission's hard constraint)

Net APR on capital, base costs; $/day = bankroll × APR/365:

| strategy (net capital APR) | $300 | $1,000 | $5,000 | min for $1/day |
|---|---|---|---|---|
| Binance BTC/ETH/SOL always-on (1.74%) | $0.014 | $0.048 | $0.24 | **~$21.0k** |
| Binance all-6 always-on (1.55%) | $0.013 | $0.042 | $0.21 | ~$23.6k |
| HL BTC+ETH (3.27%) | $0.027 | $0.090 | $0.45 | **~$11.2k** |
| HL HYPE solo (5.47%) | $0.045 | $0.150 | $0.75 | **~$6.7k** |

At the actual $313: **~1.3–4.5 cents/day.** One open+close cycle at $150
notional costs ~$0.53 — roughly **12 days of income** at the best rate. Even
the single best cell in the entire dataset (HYPE, concentrated venue+token
risk) does not reach $1/day below ~$6.7k.

## 7. Verdict and reopen conditions

**KILL — bankroll-bound, not existence-bound.** Carry is a real risk premium
(bootstrap CIs exclude zero for BTC/ETH/HYPE on both venues) and it survives
honest costs when always-on. It fails on scale: at $313, best case ~$16/year
against exchange-custody risk, XRP/DOGE-style liquidation tails, and operational
overhead on a second/third venue. Q2 and Q3 are dead outright.

**Pre-registered reopen conditions** (all three, else the lane stays closed —
no re-derivation after seeing future data):

1. User decides to custody **≥ $5,000** on Binance and/or Hyperliquid
   (custody/venue decision is the user's alone, made outside this analysis);
2. Trailing-90d funding on the target venue ≥ **5% annualized notional**
   (refetch via `analysis/perps_data_fetch.py`, rerun this script);
3. A Phase-0 paper re-verification in house style before any order: 2 weeks of
   live-quoted fee/spread capture confirming the 35bp cycle assumption, frozen
   KILL trigger = realized net carry < 50% of the then-measured trailing APR
   over the first 90 days, micro-live only after explicit user approval.

Until then: the $313 belongs where the infrastructure already is. The
updown-maker Phase-1 read (edge audit §5/§8) remains the live question on the
board; this study closes the perps side-lane with numbers.

*Artifacts: `analysis/_perps_study_2026-07-19.py` (reproduces every figure,
snapshot-only), this doc. Data: `cowork_snapshot/perps/` as of 2026-07-19.*
