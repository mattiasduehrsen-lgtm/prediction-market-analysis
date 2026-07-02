# In-play CS2 strategy: validation + production plan (2026-06-06)

**Decision in one line:** The edge is real, the repricing window is wide enough to capture with a free polling feed, and the validated edge survives a bigger sample, OOS, friction, *and* a liquidity filter — **but it is NOT ready for live money yet**, for one concrete reason: the paper bot has logged **zero** in-play bets, so live latency, live fill rate, and live ROI are all unmeasured. The math says go; the live proof doesn't exist yet. Get the paper bot logging, clear the five gates in §E, then ramp. Also be honest about the prize: even fully working, this is a **$10–100/month** strategy at current coverage. It's a proof-of-edge and an R&D vehicle, not income — unless you fix team-matching coverage to raise frequency.

All numbers reproduced from local data (679,714 deduped CS2 trades; 152 priced in-play states rebuilt from the bo3 timelines; dollar math in numpy float64 per the data-integrity warning). Where this corrects my prior memo, I say so.

---

## A. The edge window — the make-or-break. **It passes.**

I reconstructed the team-A series price trajectory around each map-1 completion (anchored at map-2 `begin_at`) and asked two things: how fast does the price settle, and how much ROI survives if we act late.

**Repricing is gradual — minutes, not seconds.** Fraction of the pre-map-1 → settled price move already complete, relative to map-2 begin:

| time vs map-2 begin | median % of move done |
|---|---|
| at map-2 begin (t1) | 59% |
| +2 min | 60% |
| +5 min | 64% |
| +15 min | 79% |
| +30 min | 89% |

About 40% of the move is still on the table when map 2 begins, and it bleeds out slowly over the next 15–30 minutes. There is no sub-second snap to lose to faster bots.

**ROI vs. entry delay** (decision made at map-2 begin, *fill* at t1+Δ, thr 0.05, 2¢ friction) — the cleanest answer to "at what latency does the edge die":

| enter at | ROI |
|---|---|
| t1 + 0 s | +23.3% |
| t1 + 1 min | +27.3% |
| t1 + 2 min | +26.9% |
| t1 + 5 min | +35.7% |
| t1 + 10 min | +23.8% |
| t1 + 15 min | +11.7% |
| t1 + 30 min | +4.7% |

**The actionable window is roughly 0–10 minutes**, with no penalty (even a slight gain) out to ~5 minutes. The edge halves around 12–15 minutes and is gone by 30. The bot's free bo3 polling feed (60-second interval) is comfortably inside this window. **This single answer — the one that gates everything — is positive: this is not a speed race you'd lose.**

**The one unverified piece:** the *live* bo3 detection lag (`bo3_detect_lag_s`) has zero recorded samples because the paper bot hasn't logged a single bet. Reconstruction says anything under ~5 minutes is fine, but you must confirm bo3 actually flips a map to "finished"/the next map to "started" within a few minutes of the real map ending. That's gate #1 in §E.

---

## B. Validated parameters (rebuilt larger sample: 152 states vs the old 122)

Re-running on the bigger sample held up — and tightened the recommendations.

**Headline edge holds and is OOS-stable:**

| threshold | n | ROI (2¢) |
|---|---|---|
| 0.00 | 152 | +12.5% |
| 0.05 | 109 | +22.3% |
| 0.10 | 83 | +20.9% |

Walk-forward OOS at thr 0.05: **TRAIN +22.6%, TEST +21.7%** — essentially identical across the split. No decay, no overfit.

**Liquidity filter *improves* it** (the opposite of the dead pre-match model): fill ≥$25 → +28.0%, ≥$50 → +32.8%, ≥$100 → +33.1%.

**State coverage — bet post-map-1 only.** Post-map-1 states are the entire edge; the 1-1 decider state is weak:

| state | n | ROI |
|---|---|---|
| post-map-1 (1-0 / 0-1) | 72 | **+28.6%** |
| post-map-2 decider (1-1) | 37 | +5.3% |

Skip deciders. (This also makes sense: the constant-per-map-p model is least reliable deep in a series — see §D.) Bo5 is negligible in the data (123 of ~22k matches) — ignore for now.

**Direction — bet the divergence either way. (This corrects my prior memo.)** My first pass said the edge was contrarian-only (back the map-1 loser). On the cleaner, larger sample, *both* directions are positive:

| direction | n | ROI | win rate |
|---|---|---|---|
| contrarian (back map-1 **loser**) | 36 | +31.0% | 22% |
| front-run (back map-1 **winner**) | 36 | +27.9% | 78% |

So bet whichever side the model says is mispriced. They differ only in *variance*: front-running is low-variance (you're backing favorites who just went up 1-0), contrarian is high-variance longshot value (27% the team that lost map 1 still wins the series). The underdog cut shows the same: backing the underdog side is +55% (WR 32%, high variance) vs the favorite side +16% (WR 79%). All positive.

**Segmentation — one yellow flag.** By bo3 tier (small n, suggestive only): the edge concentrates in tier-b (+49.6%, n=9) and unclassified (+46.6%, n=37) matches, while the **top tier-s is −5.7% (n=13)** and tier-c is flat. That is exactly the efficiency pattern — the biggest, most-watched events are priced sharpest. Don't hard-filter on tier yet (n too small), but **watch tier in paper**; if tier-s stays negative, exclude it.

**Recommended bet definition: post-map-1, |edge| ≥ 0.05, fillable ≥ $25.**
- n = 56, ROI **+31.9%**, win rate 50%
- bootstrap 90% CI **[+9.2%, +56.2%]**, P(ROI > 0) = **99%**
- not a lucky-longshot artifact: dropping the top 5 winners still leaves **+12.4%**

**Honest caveat:** n=56 is still small and the CI is wide. Treat **+9% (the CI floor)**, not +32%, as your planning number.

---

## C. Capacity and sizing — the sobering part

**Frequency is low and is the binding constraint.** Over the 115-day matched window: ~6.5 matched post-map-1 states/week → ~4.4 bettable (edge ≥0.05) → **~3.4 bettable-and-fillable per week.**

The bottleneck is team-matching coverage: only **106 of 1,151** feasibility series markets (9%) matched a bo3 timeline with a price — and feasibility is itself only ~6% of all 20,546 CS2 series markets. So you're betting on ~0.5% of the universe. Fixing the bo3 ↔ Polymarket ↔ Elo alias matching for top teams is the highest-leverage way to raise frequency (and thus dollars).

**Fillable size per bet** (dollars on our side within 3¢ of entry, 20-min window): median **$133**, 25th pct $39, 90th pct $1,660. Realistic deployable is **$25–50/bet**, occasionally $100+. (Confirm against the bot's *live* `book_depth_usd`, which is the better measure.)

**Realistic dollar P&L:**

| size/bet | ROI +9% (CI floor) | ROI +32% (point) |
|---|---|---|
| $5 | $7/mo | $23/mo |
| $25 | $34/mo | $117/mo |

**Is it worth the operational complexity? Honestly: not for the money.** $10–100/month against the work of running a live bo3 listener, order logic, and risk controls is marginal. It *is* worth doing as (a) the project's first genuinely real, fillable edge — proof the thesis works — and (b) a live R&D base you can scale *if* you raise coverage/frequency. Go in with that framing, not income expectations.

**Sizing — fractional Kelly.** Measured inputs on the recommended bets: WR 0.50, avg entry price 0.38, net odds b≈1.64 → **full Kelly ≈ 0.195 of bankroll** (huge, because the measured edge is large and uncertain — do **not** bet full Kelly). Per-bet return std is **2.98** (high, underdog-driven). Recommendation:

- **10–25% Kelly = ~2–5% of bankroll per bet.**
- At $25/bet that implies a **~$500–1,000 bankroll**.
- Hard cap per bet at **min($50, 50% of book depth within +2¢)** so you don't move the price you're trying to capture.
- Because WR on the contrarian/underdog side is ~22–32%, **expect losing streaks of 8–10**; size so that's survivable (it is, at 2–5% of bankroll).

---

## D. Execution & risk design

**Entry mechanics — take, don't rest.** The edge decays over minutes and the fade experience showed 46% of *passive* limit orders never fill (and you keep only the bad fills). So use a **marketable limit**: price = current best-ask + a 1–2¢ buffer, **capped at `model_live` minus a 2¢ margin** (never pay above model fair value). Leave it ≤ 2–3 minutes. If unfilled, re-quote **once** at the new best-ask if edge is still ≥0.05; otherwise abandon — the window is closing. Do not chase past `model_live`.

**Size:** start at the bot's current $10, raise to $25 only after gates clear; cap as in §C.

**Risk controls:**
- **Daily loss cap:** ~4× bet size (e.g., $100); on breach, set the pause flag and stop new entries for the day.
- **Max concurrent exposure:** ≤ 3 open series ($75–150).
- **Drawdown circuit-breaker:** auto-pause after −20% of bankroll *or* 10 consecutive losses; resume only manually after review (the high-variance side will trip a naive breaker, so make it explicit and survivable, not a panic-stop).
- **Stale-data / outage behavior:** if the bo3 feed is stale (live map `begin_at` older than ~10 min with no update), or the CLOB order book is missing/empty, or detection lag > 5 min → **skip the bet**. Never act on stale state. Reuse the existing `paused.live.flag` mechanism; honor Polymarket maintenance windows.

**Model-input robustness.** The live probability inverts the pre-match series Elo to a single-map `p` via `p²(3−2p)` and re-expands by current score. Calibration of the underlying Elo was good, so the input is adequate **for post-map-1**. Its weaknesses: it assumes a constant per-map `p` (ignores the specific map, veto, and in-series momentum) — which is likely why the **decider state underperforms (+5%)**, reinforcing the post-map-1-only rule. The bigger practical gap is **coverage**: 91% of series markets don't match a bo3 timeline + Elo. Build a manual alias map for the top ~50 active teams (the "3DMAX unmatched / Falcons → 7-game team" class of misses) before expecting meaningful frequency.

---

## E. Go / No-Go — graduation checklist

**Current status: NOT READY.** Backtest, OOS, friction, liquidity, and the edge-window all pass on historical data, but every *live* gate is unproven because the paper bot has logged 0 bets. First action is operational, not analytical: **find out why `output/cs2_inplay/paper_bets.csv` is empty** (team-matching failing? the status/`done`+`live_g` gating too strict? simply too few live Bo3s during the window?) and get it recording signals.

**Five numeric gates before risking $1:**

1. **Edge window, live:** ≥ 20 logged in-play signals with **median `bo3_detect_lag_s` ≤ 180 s**. *(Currently: 0 logged — blocker.)*
2. **Sample:** ≥ 40 resolved post-map-1 paper bets.
3. **Paper ROI:** ≥ **+10%** after modeled 2¢ friction (the CI floor), with win rate within ~10 pts of backtest in *both* direction buckets.
4. **Liquidity, live:** median recorded `book_depth_usd` ≥ **$50** at entries.
5. **Fill realism:** in a dry run, ≥ **60%** of signals would have filled at ≤ `model_live` within 3 minutes.

**Staged ramp once gates clear:** $5/bet for 2 weeks → $10 if ROI > 0 over ≥ 20 live bets → $25 cap. Never exceed 5% of bankroll or 50% of book depth.

**Hard No-Go (revert to paper / stop) if any of:** paper ROI < 0 over 40 bets; median bo3 lag > 5 min; median book depth < $25; live fill rate < 40%; or tier-s stays negative and can't be excluded without gutting frequency.

---

### Summary of what changed vs the prior memo
- The edge is **not contrarian-only** — front-running the map-1 winner is equally profitable (just lower variance). Bet the divergence either way.
- The edge window is now **measured** (0–10 min actionable, half-life ~12–15 min) — it comfortably clears a free polling feed.
- Bigger sample **confirms** +22% (OOS +21.7%), and **post-map-1 only** (skip deciders).
- New constraints surfaced: **9% coverage** caps frequency at ~3–4 bets/week → **$10–100/month**, and **tier-s markets look efficient** (yellow flag).
- The blocker is **operational**: the paper bot must actually start logging before any live decision.
