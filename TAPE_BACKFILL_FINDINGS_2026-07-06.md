# Tape backfill + evidence-hardening session — findings (2026-07-06)

**Purpose:** while the pre-registered R1 paper validation accrues (~early Aug),
harden the evidence base with data that can be backfilled. **Nothing here touches
the R1 or in-play triggers** — they stay exactly as pre-registered in
`COWORK_GRID_REFIT_RESULTS_2026-07-05.md` §6. This session changes *expectations*,
not rules.

**Headline: the extra evidence tilts NEGATIVE for both open validations.**

---

## 1. GRID-era trade-tape backfill (`analysis/tape_backfill.py`)

Backfilled the full Polymarket fill tape for **315 GRID-era series markets**
(Jun 23 → Jul 6; 271 resolved — vs the 188 signal-conditioned rows the re-fit
had). Marks at T−15/T−5/T−1 from actual fills; costs below = last pre-start
fill +1¢ (an ask *proxy* — weaker than captured asks, noted throughout).
v2 probs: live-logged where available (clean, n=168 sides); local predictor
otherwise (flagged `leak_prone` — its state postdates the matches).

| population | n sides | Brier market | v2 | p_r1 |
|---|--:|--:|--:|--:|
| clean (live-logged v2) | 168 | **.2376** | .2488 | .2503 |
| ALL | 316 | **.2271** | .2473 | .2529 |

- The market wins everywhere; the frozen R1 curve does **not** beat it on the
  enlarged population.
- R1 gate sim @ tape cost: clean +5.5% ROI but price-matched excess ≈ 0
  (P(≤0)=.52). **The tier rule is harmful here** (tiered subset −50%, n=16) —
  consistent with §2 of the re-fit (tier ≠ edge source).
- **June/July split (the key read):** June 23–30 (inside the curve's own fit
  window!) = **−19.1%** @ tape cost; July 1+ = **+32.7%** (excess +0.04u,
  P=.45). The re-fit's July promise is *time-local*, not stable across even two
  GRID-era weeks, and never clears the noise test.
- Curve instability: isotonic refit on the enlarged population deviates from
  the frozen table by up to **0.33** (frozen 0.20→0.03 vs refit 0.20→0.36).
  The frozen curve is a low-n artifact of June's signal population.

**Implication:** expect the R1 paper validation to land nearer its KILL trigger
(n≥60, ROI<−10%) than its GO-LIVE. Let the clock decide — that is what it's for.

## 2. Model-state coverage (`analysis/model_coverage_report.py`)

- GRID-era series coverage: **CS2 228/275 (83%), LoL 39/40 (98%)**.
- The 23 unresolved CS2 teams are **streamer/showmatch teams and brand-new
  rosters genuinely absent from PandaScore** (Team Recrent, Team Aunkere,
  Team hooch, …). Verified the highest-value candidate: **"Team shoke" is NOT
  CYBERSHOKE** (bo3 shows disjoint fixtures on the same dates) — aliasing it
  would have poisoned R1 with confident wrong-team probs. **No aliases added;
  all candidates failed verification.** These markets are unpriceable in
  principle and the gate correctly skips them.
- Refresh cadence verified healthy on the laptop: `EsportsModelState` daily
  07:00 (state fresh same-day), tier index daily 06:00.
- **Real fix shipped (v1.60):** `maybe_reload_shadow()` in the fade bot —
  hot-reloads the v2 Predictors when the daily state build writes fresh
  artifacts. Previously fresh state only reached the bot on restart.

## 3. Bookmaker odds (`odds_capture.py`, task `OddsCapture`)

- bo3.gg's matches API carries a bookmaker's odds inline (`bet_updates`):
  match-winner coefficients **plus totals/handicap props**.
- **Closing lines are NOT retroactively recoverable** — finished matches
  collapse to coeff 1.001/inactive. So we archive them ourselves, forward:
  new logger polls upcoming/live CS2 matches every 5 min (~1 API call/cycle),
  writes `output/odds_capture/odds_YYYYMMDD.jsonl`.
- Gotcha for the joiner: `aggrement_score` is NOT the implied probability
  (mismatches 1/coeff) — compute implied probs from the coefficients.
- In ~a week: join book closes vs Polymarket marks vs results → "is the
  GRID-era market just tracking the books" diagnostic, plus book lines on the
  prop surface.

## 4. GRID-era in-play read (`analysis/inplay_tape_join.py`) — **NEGATIVE**

bo3 per-map results (map-1 winner, map-2 begin) joined against the backfilled
tape; contrarian side priced at the last fill in [map2_begin−10min, −30s]:

| bucket | n | implied wins | actual | z | ROI |
|---|--:|--:|--:|--:|--:|
| ALL | 106 | 28.8 | 22 | **−1.58** | −26.3% |
| entry ≤0.30 | 64 | 10.6 | 10 | −0.19 | −20.6% |
| entry ≤0.15 | 27 | 2.5 | 2 | −0.36 | −45.1% |

On the GRID-era population — **double the live paper sample (106 vs 51)** —
buying the map-1 loser between maps *underperforms its price* in every bucket.
Consistent with the 2026-06-21 warning: GRID's low-latency official feed behind
Polymarket kills the in-play informational edge. The pre-registered live-stream
test (n≥100, no peeking) remains the formal adjudicator; expectations = fail.

## 5. Price capture widened (v1.60)

`price_capture.py` now captures **all esports titles** (dota/valorant/EWC/CDL/
apex — the parquet was already all-esports; only the slug filter was narrow).
Any future GRID-listed title starts with a fill-true referee from day one.
Sports stays out (different universe file + volume profile; revisit if the
sports lane revives).

---

## Re-run instructions (laptop or dev)

```powershell
.venv\Scripts\python.exe -u analysis\_grid_refit_2026-07-05.py signals   # refresh signal table
.venv\Scripts\python.exe -u analysis\tape_backfill.py                    # fetch (resumable) + marks + report
.venv\Scripts\python.exe -u analysis\inplay_tape_join.py                 # bo3 fetch (cached) + join
.venv\Scripts\python.exe -u analysis\model_coverage_report.py
```

*Session artifacts: analysis/{tape_backfill,inplay_tape_join,model_coverage_report}.py,
odds_capture.py + watch_odds_capture.bat (new task), price_capture widening,
maybe_reload_shadow in esports_fade_bot.py. LIVE stays paused; triggers untouched.*
