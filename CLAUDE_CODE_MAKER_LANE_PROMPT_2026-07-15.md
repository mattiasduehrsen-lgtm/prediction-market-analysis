# Claude Code handoff — updown maker-rebate lane (compiled from Cowork edge audit, 2026-07-15)

> **Prompt:** You are Claude Code working in `prediction-market-analysis`. Your mission
> is to execute Phase 0 and build Phase 1 of the maker-rebate lane defined below,
> under the constraints in §6. Read this whole file first, then `CLAUDE.md`, then
> `COWORK_EDGE_AUDIT_2026-07-15.md`. Do NOT re-derive strategy from older docs —
> everything before this file's date is superseded by the findings compiled here.
> Before doing anything, print the §7 checklist and confirm each item.

---

## 1. State of the project (as of 2026-07-15, verified against data)

- **LIVE: nothing trading.** Esports fades paused since v1.58 (`paused.flag`), WTA
  live experiment KILLED 2026-07-13 (−$62, pre-registered trigger). Wallet ≈ **$313 pUSD**.
- **Two machines:** dev PC `C:\Users\home user\Desktop\prediction-market-analysis`
  (edit, commit, push) → laptop `C:\Users\matti\Desktop\prediction-market-analysis`
  (`ssh matti@192.168.2.212`, runs 24/7 tasks). `.env` lives on the laptop only.
- **Never restart or stop any scheduled task without explicit user confirmation.**
  Restart protocol, task inventory, and do-not-reintroduce bugs: `CLAUDE.md`.
- Two pre-registered clocks are RUNNING and must not be touched or peeked at (§5).

## 2. Compiled findings — the graveyard (do not re-litigate any of these)

Every number below was measured from the project's own data. Reproduction:
`analysis/_edge_audit_2026-07-15.py` (+ the older verdict docs cited).

| Lane | Result | Status |
|---|---|---|
| 15m/5m crypto mean-reversion (taker) | ML on 17 features, 721 trades: CV AUC 0.496; corrected EV ≈ −$1/trade | DEAD (v1.29–v1.34 era) |
| Resolution scalp (crypto) | Apr 25 "edge" was small-N false positive; needs 69% WR, max 61% | DEAD (v1.26a) |
| Esports wallet-fade | τ=0.001 skill dispersion; 0 wallets clear posterior floor; OOS fade −15.1% (t=−2.55); live −$141/44 fills | DEAD (`WALLET_SELECTION_V2_2026-07-13.md`) |
| WTA live fade | Killed at n=60, −20.8% ROI, −$62 | DEAD (`WTA_LIVE_PLAN_2026-07-09.md`) |
| Follow-the-bookmaker | 0–6 on disagreements; Polymarket beats book Brier (corr .96) | DEAD |
| Props as taker | −9%…−61% ROI at executable quotes, all classes, both sides; spreads 0.05–0.88 | DEAD-REDIRECT (never fade into props) |
| In-play contrarian (GRID era) | tape join n=106: −26.3% ROI, z=−1.58 | expect FAIL (clock §5 decides) |
| R1 recalibrated fade gate | frozen curve doesn't beat market on enlarged tape; Jun −19%/Jul +33% instability | expect KILL (clock §5 decides) |
| **Settlement-lag parking** (new) | buy "decided" side ≤0.99: −2.2%…−3.1% ROI; 9/198 reversals; ~$500 depth, 2.4h lockup | DEAD (audit §1.1) |
| **Ladder arbitrage** (new) | 482k prop-ladder snapshots: 3 violating minutes, $0.09 capturable in 16 days | DEAD (audit §1.2) |
| **Calibration-band buying** (new) | fresh mid-band edge +0.0008 (n=1,436); GRID T−1 edge −0.008 (z=−0.22); tail "edges" = stale-print artifacts | DEAD (audit §1.3) |
| **Steam momentum** (new) | all drift buckets z ≤ 1.5, sign-flipping (n=1,312) | DEAD (audit §1.4) |
| **Naive maker on esports** (new) | Mar 29–Apr 14 tape, 23,350 wallets: pure makers −1.13% of $33M; mostly-maker −1.04% of $96M; winners were mixed/latency wallets (+2.06% of $74M) | DEAD as naive play — defines the design constraints in §3 |

**Meta-finding:** the market is calibrated to ~0.1¢ where it trades, out-sharps
bookmakers, and since Jan–Mar 2026 charges takers a fee larger than any edge this
project ever measured. Stop looking for taker edges in fee-enabled categories
unless `edge > spread + 1¢ + fee(p)` is demonstrated fill-true.

## 3. Compiled findings — the fee/rebate regime (the gap)

Primary sources: help.polymarket.com → "Trading Fees", "Maker Rebates Program"
(fetched 2026-07-15). Verify live values in Phase 0 — docs show two formula variants.

- **Taker fees** (rolled out Jan 7 → Mar 30, 2026): crypto feeRate **0.072**
  (≈ `C×0.072×p(1−p)` → **1.8¢/share at p=0.5**, ~3.6% of notional at mid);
  sports **0.03** (≈ `C×p×0.03×p(1−p)` → peak ~0.75% of notional). Sell-side
  taker orders fee-free. Geopolitics fee-free. `feesEnabled` flag on market object.
- **Makers pay zero** and receive **rebates: 20% (crypto) / 25% (sports)** of
  taker fees, pooled **per market**, distributed **daily** pro-rata by the
  fee-equivalent of **filled** maker volume; $1 minimum payout.
  Effective rebate ≈ `0.20 × 0.072 × p(1−p)` per filled share ≈ **0.36% of
  notional at mid** — before spread capture.
- **Scale:** ~$23.7M net fees in first 83 days (≈$57–71k/day to makers);
  crypto 15m ≈ $292M weekly notional (Feb); 5m markets have since overtaken 15m;
  ~86% of 5m taker volume is bot-like. Polymarket added dynamic fees explicitly
  to curb latency arbitrage (platform is protecting makers).
- **The bot paid these fees unmodeled** on every LIVE crypto trade after Jan 7
  (fee field non-zero on 94.9% of legs in the Mar 28+ esports tape too). The
  maker rebate is name-checked in `src/bot/engine_5m.py` ("not yet modelled") —
  it was never modelled. Nobody in this project has ever stood on the maker side.

**Thesis:** quote both sides of `{btc,eth,sol,xrp}-updown-{15m,1h}-{epoch}`
around a Binance-anchored fair value; revenue = spread + rebate; risk = adverse
selection + end-of-window inventory. §2's maker row is the warning: making
without a fair-value anchor and fast cancels is food. The bot has the anchor
(1s BinanceFeed) — whether that is fast ENOUGH is precisely what Phases 0–1
measure for $0.

## 4. Your mission (in order; each step gated)

**Phase 0a — deploy the referee (laptop; requires user confirmation for the new task):**
1. `git pull` on the laptop. Verify shipped files exist: `updown_book_capture.py`,
   `watch_updown_capture.bat`, `analysis/updown_rebate_probe.py`.
2. Smoke-test capture in foreground ~2 min:
   `.venv\Scripts\python.exe -u updown_book_capture.py` — expect book lines for
   btc/eth/sol 15m; note which families resolve (xrp? 1h? 5m?). Fix slug families
   that 404 (the `1h` prefix is speculative — check what polymarket.com/crypto/hourly
   uses; adjust `WINDOWS` accordingly, small commit per protocol).
3. **Ask the user**, then create + start the scheduled task:
   `schtasks /create /tn UpdownCapture /tr "C:\Users\matti\Desktop\prediction-market-analysis\watch_updown_capture.bat" /sc onstart /ru SYSTEM` → `schtasks /run /tn UpdownCapture`.
   Do NOT touch any other task. Verify `output/updown_capture/updown_YYYYMMDD.jsonl` grows.
4. Run `analysis\updown_rebate_probe.py` once; save output to
   `output/updown_capture/probe_YYYYMMDD.txt`. It answers: feesEnabled + exact fee
   params per family, per-day taker notional, rebate-pool $/day, small-maker projection.
5. **Phase 0 gate (pre-registered — evaluate mechanically):** proceed to Phase 1
   only if pools sum ≥ **$500/day** across families AND ≥3 families show median
   touch-depth < **$2,000**. Else write the numbers into the audit doc and STOP the lane.

**Phase 0b — CDL capture check (5 min, event runs Jul 16–19):** confirm new
`-cdl-` markets are entering `cowork_snapshot/esports/clob_esports_markets.parquet`
and the ±48h capture window (index showed only Jul 24–25 CDL slugs on 2026-07-15).
If the index refresher isn't picking up Champs markets, day-one books are lost
forever — investigate the refresher task, report to user. **Observe-only per
v1.64 — no CDL trading logic of any kind.**

**Phase 1 — maker fill simulator (dev PC; after ≥3 days of capture):**
Build `analysis/updown_maker_sim.py` against `output/updown_capture/*.jsonl`
(line types: `spot` {px per symbol}, `book` {slug,cid,win,w0,bid,ask,depths,touch},
`trades` {trades:[{ts,px,sz,side,out,tx}]; dedupe by tx}).
- Quote model: two-sided at `fair ± k`, fair = GBM P(up) from Binance spot path
  (reuse the RS-era math in `signal_5m.py`), k ∈ {2,3,4,5¢}; clip $5–$20;
  re-quote when fair moves > 1¢; cancel-on-move if spot jumps > threshold since
  quote; flatten at T−90s; no quoting in first 30s of a window.
- **Prints-only fill rule (conservative):** a resting quote fills only when a
  logged taker print crosses at-or-through its price, capped by print size, and
  only counts AFTER assuming the entire logged touch depth at that price fills
  first (worst-case queue).
- PnL per fill = spread capture ± mark move at +10s/+60s/expiry (adverse
  selection), + rebate = `0.20 × feeRate × p(1−p) × shares` (use Phase-0-verified
  params), + resolution PnL on any un-flattened inventory.
- Report net edge by (asset, window, hour-band) cell with cluster-bootstrap by
  window; **select cells on the first half of capture days, confirm on the
  second half** — no cell-shopping on the pooled set.
- **Phase 1 gate (pre-registered):** GO to Phase 2 only if a split-half-confirmed
  cell shows net > 0 with P(≤0) < 0.05 over ≥300 simulated fills across ≥5 days
  AND projected ≥ $3/day. **KILL otherwise.**

**Phase 2 — micro-live (only after Phase 1 GO + explicit user approval; separate
session):** new `updown_maker_bot.py`, maker-only orders, one asset one window
family, $100 inventory cap, $5 clips. KILL: cumulative net < **−$25**, OR adverse
selection > spread+rebate 3 consecutive days, OR no rebate payout within 48h of
qualifying fills. SCALE to $300 at n≥200 fills AND net ROI > 0 (cluster-t ≥ 2)
AND live-within-30%-of-sim. Triggers are frozen now; changing them = new
pre-registration, clock restarts.

## 5. Clocks and hygiene you must not disturb

- **R1 paper gate:** 12/150 gated bets, GO/KILL spec in
  `COWORK_GRID_REFIT_RESULTS_2026-07-05.md` §6. Don't evaluate early.
- **In-play contrarian:** gate = contrarian n≥100 AND p<0.02 via
  `analysis/_inplay_sig.py`. 207 rows logged. **No interim significance runs.**
- **Wallet-dryness second window:** re-run `analysis/wallet_scores.py` on
  refreshed tape ~**Jul 21** (expected: confirms dry).
- **NBA fade:** +14% on old paper, season resumes ~late Oct — needs fresh
  tape-check + new pre-registration then. Do nothing now.
- Sports paper stream keeps running (MLB +5.8%/WTA +5.5% last 30d on paper are
  NOT signals — MLB tape t=0.45; the WTA lesson stands).
- Any code change: bump `src/bot/version.py`, entry in `PATCH_HISTORY.md` +
  `STRATEGY_HISTORY.md`, descriptive commit, push, pull on laptop, **ask before
  any restart** (capture task excepted once user approves its creation).

## 6. Hard constraints

1. **No live orders in Phases 0–1. Nothing in this mission risks a dollar.**
2. Never stop/restart existing scheduled tasks; never `Start-Process` over SSH;
   use `schtasks` per `CLAUDE.md`.
3. Respect pre-registered gates verbatim — evaluate mechanically, never re-derive
   after seeing results.
4. Don't "fix" the two-python-per-task pattern; don't touch `paused.flag` /
   `paused.live.flag`.
5. Polygon/API keys and `.env` stay on the laptop; never commit secrets.
6. If a gate KILLs the lane, write the verdict into
   `COWORK_EDGE_AUDIT_2026-07-15.md` (append a dated section) and stop — a clean
   kill is a valid deliverable in this project.

## 7. Pre-flight checklist (print and confirm before acting)

- [ ] Read `CLAUDE.md`, this file, `COWORK_EDGE_AUDIT_2026-07-15.md` §5 gates
- [ ] Confirmed which machine I'm on (dev vs laptop) and that LIVE is paused
- [ ] Confirmed I will not stop/restart/peek at anything in §5
- [ ] User has approved (or I will ask before) creating `UpdownCapture`
- [ ] I know the Phase 0 / Phase 1 gates are frozen and mechanical

*Compiled by Cowork (Fable 5) 2026-07-15 from: `analysis/_edge_audit_2026-07-15.py`
runs on `cowork_snapshot/` (2.69M book snapshots, 1.8M-fill tape, 127k-market
index, 109k resolutions), repo verdict docs, and help.polymarket.com primary
sources. Full audit narrative: `COWORK_EDGE_AUDIT_2026-07-15.md`.*
