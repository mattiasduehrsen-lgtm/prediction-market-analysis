# WTA fade — live-arming plan (pre-registered 2026-07-09, BEFORE final tape score)

> ## ⚰️ KILLED 2026-07-13 16:26 UTC — trigger fired, reverted to paper.
>
> **Final: 60 resolved fills, 29–31, ROI −20.8%, net −$62.44 realized** (+6 open
> positions, cost $30.0, valued $38.5 at kill time — final tally moves with them).
> The KILL condition (ROI < −15% at n ≥ 50) was met together with a daily-cap hit
> on 2026-07-13 (−$66.70 realized that day on 26 resolutions — one catastrophic
> post-Wimbledon Monday did the killing; the book was ~+$4 before it).
> Action taken per pre-registration: `LIVE_SPORTS` removed from laptop `.env`,
> `PolyBotSports` restarted; verified signals route to paper (Gjorcheska fade
> logged to paper_trades.csv post-restart, no live orders after the kill ts).
> Open positions remain tracked and resolve on their own.
>
> **Cost of the experiment ≈ −$54 to −$62** — inside the underwritten worst case
> (−$100–150). Live WR 48% (29/60) vs the ≥57% the entry prices needed; the tape
> check was honest about *execution* (fills matched claims) but 3.5 days of live
> sample landed on the wrong side of a thin (t=1.61) edge. Whether the edge was
> real-but-unlucky or never real is not distinguishable at n=60 — and per the
> plan we do not re-derive or re-enter without a NEW pre-registration.
>
> **Process note for next time:** live-eligible signals skip the paper write, so
> the "paper stream = control" clause was structurally empty for WTA during the
> live window (fade_events retains the signals if a reconstruction is ever
> wanted). Any future live plan should keep a shadow-paper write for the live
> sport. Wallet after kill: ~$313 pUSD.

**Context:** user is time-constrained; esports R1/in-play clocks run to ~August and
tape evidence says they likely end in kills. The sports paper stream (running since
May on the frozen 2026-05-23 target list) shows WTA fade +10.2% on 1,072 trades /
271 markets since Jun 18 (per-trade t=4.08, but per-market clustered t=1.79; weekly
ROI noisy). ATP (−11%), MLB (~0), NHL (−6%) are dead; NBA (+14%) is out of season.

**Fill-true check (analysis/sports_tape_check.py):** every signal re-priced at the
first real tape fill within 10 min (+1¢). Interim (579/742 markets): WTA tape ROI
= claimed ROI (+6.6% vs +6.5%), slip ≈ 0, fill rate 93% → sports paper accounting
is honest (unlike esports). May's MLB live −18.5% (n=119, t≈−1.9) reads as variance
+ possibly timing, not proven mirage — but it is the cautionary precedent.

## Arming bar (pre-registered before the final score)

Recommend flipping WTA live ONLY if, on the full scored set (since Jun 18):
1. WTA tape ROI ≥ +5%, AND
2. per-market clustered t ≥ 1.5, AND
3. tape ROI positive in ≥ 2 of the last 3 full weeks.

If the bar fails → do NOT arm; WTA stays paper and we report honestly that no
deployable edge was found today.

### VERDICT (final score, 742/742 markets, 2026-07-09): **BAR PASSES — ARMED.**

| | WTA | MLB (control) |
|---|---|---|
| n scored / markets | 1,053 / 270 | 1,424 / 443 |
| claimed (entry) ROI | +9.9% | +3.4% |
| **tape ROI** | **+9.4%** | +2.5% |
| avg slip | −0.000 | −0.001 |
| clustered t | **1.61** | 0.45 |
| weekly tape ROI W25/26/27/28 | +18.0 / +5.1 / −1.1 / +21.2% | +11.6 / +14.6 / −7.7 / −9.1% |

Conditions: (1) +9.4% ≥ +5% ✓  (2) t=1.61 ≥ 1.5 ✓  (3) full weeks W25/W26 positive,
W27 −1.1% → 2 of 3 ✓. Fill rate 93%, slip ≈ 0 → sports paper accounting is honest.
MLB control correctly fails (t=0.45, sign-flipping) — the method discriminates.

Honest posture: t=1.61 ≈ p 0.054 one-sided. This is a THIN edge armed with a fast
KILL, not a proven one — the live triggers below do the real risk work.

## Deployment config (v1.63, shipped dark)

- `LIVE_SPORTS_PREFIXES` is now env-driven (`LIVE_SPORTS` in laptop `.env`,
  comma-separated). Default empty = all paper. **Arming = add `LIVE_SPORTS=wta-`
  + `SPORTS_DAILY_LOSS_CAP=50` to laptop .env and restart `PolyBotSports` — after
  explicit user confirmation. No code deploy at arming time.**
- Bet size $5 flat (unchanged). Entry floor 0.40 (pre-existing rule, unchanged).
- Consensus filter N≥2 (unchanged — it is part of the validated signal).
- `SKIP_MARKET_KEYWORDS` extended with `-set-`, `-total` (tennis prop leak guard;
  4 leaked trades in the paper stream, ROI estimate unaffected).
- **Target list stays FROZEN on the 2026-05-23 build** — the validated signal was
  earned on this list; refreshing it before go-live would deploy an unvalidated
  variant. Schedule a refresh only at the first scale checkpoint.
- Daily loss cap $50 (env). Risk backstop and per-market caps unchanged.

## Live triggers (pre-registered; do not re-derive after seeing live results)

- **KILL (revert to paper):** running live ROI < −15% at n ≥ 50 resolved fills,
  OR two consecutive daily-loss-cap hits. Reverting = remove `LIVE_SPORTS` from
  .env + restart (positions resolve on their own).
- **SCALE to $10:** n ≥ 100 resolved live fills AND live ROI > +5%. At that
  checkpoint also refresh the target list (new pre-registration for the new list).
- **Health metric:** weekly compare live fills ROI vs same-period paper stream
  (paper keeps running on all sports — it is the control). Live lagging paper by
  >10pp over ≥50 fills = execution problem, investigate before continuing.
- Expected volume: WTA recent rate ≈ 22 consensus fades/day → first KILL read in
  ~3 days, scale read in ~1 week. **This fits the user's clock; that is the point.**

## Why WTA is plausible (mechanism, not just numbers)

Women's tennis is a lower-liquidity, lower-attention market with high day-to-day
variance; casual money chases favorites and recent form. The fade population (155
independent wallets, top wallet only 18% of recent profit, edge survives without
it) is broad — the opposite of the esports failure mode (one MM wallet = all loss).
ATP being −11% while WTA is positive is consistent with ATP being the sharper,
higher-attention side of tennis.

## Known risks

- Multiple-comparisons: WTA was the best cell in a sport×window scan. The tape
  check and the KILL trigger are the mitigations, not a guarantee.
- Weekly sign-flips: the edge, if real, is small and noisy; $5×22/day ≈ $110/day
  at risk, cap $50/day realized loss.
- May precedent: MLB went paper +7% → live −18.5% (n=119). Slip isn't the
  explanation per the tape check, so if WTA live lags paper the same way, the
  health metric catches it and the KILL fires.
