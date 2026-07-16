# Edge audit — every unventured lane, measured (Cowork Fable 5, 2026-07-15)

**Mandate:** "Analyze all of the data and create a new strategy that can make money.
Find a gap we have not ventured."

**Verdict up front:** the data says there is **no unexploited *prediction* edge left
in the lanes this project can reach** — I scanned five previously unmeasured
surfaces below and killed four of them with your own captured data. But the audit
surfaced one structural lane that is genuinely unventured, is subsidized by
Polymarket itself, and reuses the bot's entire existing infrastructure:
**maker-rebate market making on the crypto Up/Down markets** — the exact markets
this project spent March–May *losing* to as a fee-paying taker. Since January–March
2026 Polymarket charges takers a fee-curve fee (crypto feeRate 0.072 ≈ $1.80 per
100 shares at 50¢) and redistributes **20% of crypto / 25% of sports fees to makers,
daily, per market, pro-rata by filled maker volume** — reportedly **$23.7M net fees
in the first 83 days (≈$57–71k/day flowing to makers)**. The bot has only ever stood
on the paying side of that toll booth. Whether a small maker can collect it without
being run over by adverse selection is a measurable question — and §5 pre-registers
exactly how to measure it for $0 before any order is placed.

Nothing in this session touches LIVE, restarts anything, or alters the two open
pre-registered clocks (R1, in-play). All numbers reproducible:
`analysis/_edge_audit_2026-07-15.py` (runs on `cowork_snapshot/` only).

---

## 1. What was scanned and killed today (new measurements, your data)

| # | Lane (never measured before) | Result | Verdict |
|---|---|---|---|
| 1 | **Settlement-lag parking** — buy the "decided" side (bid ≥0.97) at ask ≤0.99, hold to resolution | 4,138 resolved captured markets: market-level reversal rate is only 0.2–0.4%, but the *rule* loses **−2.2% to −3.1% ROI** (9/198 triggered buys reverse) — asks still resting ≤0.99 mid-match are adversely selected (Bo3 comeback risk); median depth only ~$500 and ~2.4h capital lockup | **DEAD** |
| 2 | **Ladder arbitrage** — monotonicity violations across totals/kills strike ladders (the "consistency arb" the 07-01 war-room couldn't test) | 482k ladder snapshots, 641 families, 2,350 two-sided adjacent-strike pair-minutes: **3 violating minutes, one episode, $0.03 capturable in 16 days** | **DEAD** — the prop MM never quotes an incoherent ladder; books are one-sided |
| 3 | **Calibration pockets** — any price band where buying beats the price (1.8M fills, 6.6k markets, Mar 28–Apr 15 + GRID-era repeat) | Fresh, active mid-band (0.20–0.80): edge **+0.0008** (n=1,436). Apparent tail edges (3¢ tokens "winning 40%") are stale-print artifacts — vanish under fresh-quote filters. GRID-era T−1 calibration: edge −0.008, z=−0.22 (n=173) | **DEAD** — the market is calibrated everywhere it actually trades |
| 4 | **Steam/momentum** — follow or fade the pre-start drift (T−6h→T−15m vs resolution) | All drift buckets z ≤ 1.5 and sign-flipping (n=1,312 legs) | **DEAD** |
| 5 | **Naive maker on esports** — wallet-level cash-flow PnL, full Mar 29–Apr 14 tape (1.8M fills, 23,350 wallets), wallets segmented by maker-share of notional | **Pure makers (≥90% maker legs): −1.13% of $33M notional. Mostly-maker: −1.04% of $96M.** The biggest maker wallets lost $792k / $336k / $192k. Winners were *mixed* wallets (+2.06% of $74M) — the (pre-GRID) latency snipers | **DEAD as naive play** — resting liquidity without a fair-value anchor is food, even for professionals |

Row 5 is the pivotal measurement: it proves making is **not** automatically the
house side — and it dates from *pre-GRID* esports, where makers lacked the fast
official feed. It defines exactly what a maker strategy must have to survive:
a real-time fair-value anchor and fast cancels. On crypto Up/Down markets the
anchor is Binance spot — **which the bot already runs as a 1s background feed.**

Standing verdicts re-confirmed, not re-litigated: wallet-fade well dry
(τ=0.001, `WALLET_SELECTION_V2_2026-07-13.md`); WTA live killed −$62; props
untouchable as taker (−9%…−61% at quotes); in-play contrarian negative on the
GRID tape; market out-sharps bookmakers (follow-the-book 0–6); MR-15m/RS crypto
taker strategies structurally noise (`ML AUC 0.496`).

---

## 2. The regime change nobody here priced in

Polymarket introduced **taker fees** Jan 7, 2026 (crypto 15m first), extended to
sports Feb–Mar and a broad schedule Mar 30. Verified from the primary sources
(help.polymarket.com "Trading Fees" + "Maker Rebates Program", July 2026):

- **Crypto Up/Down:** feeRate **0.072**, fee ≈ `C × 0.072 × p(1−p)` → **1.8¢/share
  at p=0.5** (~3.6% of notional at mid). *This applied to every LIVE crypto trade
  the bot made after January — unmodeled.* Part of the "execution drag" v1.28
  attributed to accounting was plausibly just fees.
- **Sports/esports:** fee ≈ `C × p × 0.03 × p(1−p)` → peak ~0.75% at 50/50 —
  confirmed empirically: the fee field is non-zero on **94.9%** of legs in your
  own Mar 28+ esports tape. Every fade/in-play backtest priced at "+1¢" was in
  reality "+1¢ + fee."
- **Maker side: zero fees, plus rebates.** 20% (crypto) / 25% (sports) of taker
  fees, pooled **per market**, distributed daily pro-rata by the fee-equivalent
  of your **filled** maker volume. Sell-side taker orders are fee-free.
- Scale: ~$23.7M net fee revenue in the first 83 days; crypto 15m alone reached
  ~$292M weekly notional in Feb 2026, and the newer 5m markets overtook 15m.
  ~86% of 5m taker volume is bot-like flow.

`src/bot/engine_5m.py` line 7 has known this since April: *"Small maker rebate
(~1-2% of fill, **not yet modelled**)."* It was never modelled. That is the gap.

Corollary for every future *taker* idea in fee-enabled categories: the bar is now
`edge > spread + 1¢ + fee(p)`. The fee alone is bigger than most edges this
project has ever measured.

---

## 3. The proposal: updown maker-rebate lane ("be the toll booth, not the traffic")

**Mechanism.** Quote both sides of BTC/ETH/SOL/XRP Up/Down windows (15m and 1h
first — 5m is the sniper pit) around a Binance-anchored fair value, wide enough
to only meet uninformed flow, tiny clips, hard inventory caps, flatten before
window end. Revenue = spread + 20% fee-curve rebate on every fill; cost =
adverse selection + inventory that rides to resolution.

**Why this fits *this* project specifically:**
- The bot already has: 24/7 laptop + watchdogs, CLOB auth/order machinery (incl.
  the v1.9–v1.11 execution scar tissue), a 1s Binance feed, GBM fair-value code
  (from the RS era), the 15m market discovery module (`market_5m.py`, XRP already
  wired), dashboards, and a proven pre-registration discipline.
- Rebate income scales with **turnover, not bankroll** — $300 turning over 10–15×/day
  at mid prices generates roughly `300 × 12 × 0.018 × 0.20 ≈ $13/day` in rebates
  *before* spread capture, if fills happen. On a $313 wallet that is not a toy
  number — it is ~4%/day gross, and the binding question is only how much adverse
  selection eats.
- Polymarket's **dynamic fee** change explicitly targets latency arbitrageurs —
  the platform is actively protecting makers from the flow that killed them in §1.5.

**Why it can still fail (stated before any data):** pro MMs with ms-latency will
hold the touch; our 1s loop means we quote wider and capture less; adverse
selection at window-open and on spot jumps may exceed rebate+spread exactly as it
did for pre-GRID esports makers; rebate pools are per-market and dilute with
maker competition. **If Phase 1 shows net negative, this dies like everything else.**

---

## 4. What ships today ($0 at risk, no restarts without your say-so)

1. **`updown_book_capture.py` + `watch_updown_capture.bat`** — read-only logger:
   books (touch + 2¢ depth), real taker prints, Binance spot, every ~10s, for all
   active updown windows. This is the fill-true referee: in the Phase-1 sim, a
   hypothetical resting quote counts as filled **only if a real taker print crossed
   it**, and adverse selection is measured as mark-vs-fill 10s/60s/expiry later.
2. **`analysis/updown_rebate_probe.py`** — one-shot sizing: confirms `feesEnabled`
   + exact fee params on live updown markets, measures per-family taker notional
   and the implied daily rebate pool, projects small-maker income at 0.5–5% fill
   share. (Dev sandbox has no API egress — run on the laptop.)
3. **`analysis/_edge_audit_2026-07-15.py`** — full reproduction of §1.

To start collecting (needs your go-ahead, creates a new scheduled task, touches
nothing else):
```powershell
schtasks /create /tn UpdownCapture /tr "C:\Users\matti\Desktop\prediction-market-analysis\watch_updown_capture.bat" /sc onstart /ru SYSTEM
schtasks /run /tn UpdownCapture
.venv\Scripts\python.exe -u analysis\updown_rebate_probe.py   # one-shot, prints pool sizes
```

---

## 5. Pre-registered gates (set now, before any data — house rules apply)

**Phase 0 — sizing (days 1–3, $0).** Probe + capture running.
- **Continue to Phase 1 only if:** measured rebate pools across (asset×window)
  families sum to ≥ $500/day AND at least 3 families show median touch-depth
  < $2,000 (i.e., room for a small maker to matter). Otherwise **KILL the lane**
  and write the number down.

**Phase 1 — offline maker sim (days 3–12, $0).** Simulate conservative quoting
(±k around Binance-GBM fair value, cancel-on-move, flatten at T−90s) against
captured books with prints-only fills.
- **GO to Phase 2 only if:** net simulated edge (spread + rebate − adverse
  selection − end-inventory losses) > 0 with cluster-bootstrap P(≤0) < 0.05 over
  ≥ 300 simulated fills spanning ≥ 5 distinct days, in at least one
  (asset, window, hour-band) cell **chosen on the first half of capture days and
  confirmed on the second half** (no cell-shopping on the full set).
- **KILL if:** no cell passes, or the passing cell's projected income < $3/day.

**Phase 2 — micro-live (weeks 2–4).** One asset, one window family, $100
inventory cap, $5 clips, maker-only orders, existing daily-loss circuit breaker.
- **KILL:** cumulative net PnL < **−$25**, OR realized fill-level adverse selection
  exceeds (spread+rebate) for 3 consecutive days, OR rebate payouts don't appear
  within 48h of qualifying fills (mechanics mis-read).
- **SCALE to $300 inventory:** n ≥ 200 live maker fills AND net ROI > 0 with
  cluster-t ≥ 2 AND live tracks Phase-1 sim within 30%.
- No re-derivation of any trigger after seeing results. New parameters = new
  pre-registration, clock restarts.

---

## 6. Everything else on the board (kept honest)

- **R1 paper gate:** 12/150 gated bets; clock runs to ~early Aug; expectation
  KILL (tape says the frozen curve doesn't beat the market). Untouched.
- **In-play contrarian:** 207 rows logged (gate at contrarian n≥100, p<0.02).
  Counted only — **no interim significance computed** (pre-registration honored).
- **CDL / CoD Champs (Jul 16–19):** stays **observe-only per v1.64**. Note: the
  market index shows CDL slugs only for **Jul 24–25** league dates as of this
  snapshot — Champs match markets may not be listed yet. **Verify tomorrow on the
  laptop** that new `-cdl-` markets enter the index and the capture window:
  `python -c "import pandas as pd; m=pd.read_parquet('cowork_snapshot/esports/clob_esports_markets.parquet',columns=['slug','game_start']); print(m[m.slug.str.contains('cdl',na=False)].game_start.min(), m.slug.str.contains('cdl',na=False).sum())"`
  If the index refresher isn't picking them up, day-one books are lost forever.
- **Sports paper watchlist (NOT signals — the WTA lesson):** last 30d paper:
  MLB +5.8% (n=2,082), WTA +5.5% (n=1,278), ATP −14.3% (n=2,269). MLB's fill-true
  tape check was t=0.45 — noise. **NBA (+14% paper, out of season) is the one
  worth a fresh pre-registered tape-check when the season starts ~late Oct.**
- **Prop-tape maker measurement (blocked):** the −9%…−61% taker ROI on props is
  someone's maker income; measuring GRID-era prop maker PnL needs prop fill tapes
  (`analysis/tape_backfill.py` fetch extended to prop slugs — laptop, resumable).
  Curiosity only: the winner-market maker result (§1.5) already says don't fight
  the resident prop MM on its own turf.

---

## 7. The honest one-paragraph summary

Eight taker strategies have now been designed, measured, and killed in this
project, and today's audit adds four more corpses (settlement-lag, ladder arb,
calibration bands, steam). Your own tape shows the market is calibrated to
within a tenth of a cent where it trades, out-sharps the bookmakers, and — since
January — charges every taker a fee larger than any edge this project ever
found, then hands 20–25% of that fee to the other side of the trade. The one
economically-grounded seat left at this table is the subsidized side. The bot
owns every piece of infrastructure that seat requires except one number:
**how much adverse selection a 1-second maker eats on updown books** — and §5
measures that number for zero dollars before a single order is placed. If it
comes back negative, the honest end-state is that this market offers a small
retail bot no seat at all, and the capital belongs elsewhere.

*Session artifacts: `updown_book_capture.py`, `watch_updown_capture.bat`,
`analysis/updown_rebate_probe.py`, `analysis/_edge_audit_2026-07-15.py`, this doc.
No bot code touched. No tasks created or restarted. LIVE stays paused.*
