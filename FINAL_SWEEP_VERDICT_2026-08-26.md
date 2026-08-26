# Final all-data strategy sweep — 2026-08-26

User directive: "look at all the data and give it one last chance at there
being a strategy." Every open question was run to a measured verdict. This
document closes the research program.

## Data inventoried

57 days of book capture (2.8 GB), 38 days of news capture, 46 days of bo3
odds (841 MB), 42 days of updown books (8 GB), GRID-era tape (445k fills),
R1 paper ledger (111 bets / 50.5 days), TI 2026 captured end-to-end.

## Verdict 1 — News-lag harvester: KILL (measured today)

The original create-our-own-edge idea: trade roster news before the market
reprices. First clean measurement (v3 — after removing two artifacts that
briefly made it look spectacular: the reaction window ran into the live
match, and duplicate news rows pseudo-replicated one market 400+ times):

- 46 event x market pairs across 40 distinct markets, placebo-controlled
- **Trigger rate 17% vs placebo 19%** — pre-match books drift at the same
  rate whether or not roster news just broke
- Median "trigger" move 12.7c, indistinguishable from background

There is no repricing lag to harvest. The market either absorbs roster news
faster than a 60s book cadence can see, or (more likely at these depths)
roster news simply does not move pre-match series prices. KILL.

## Verdict 2 — Young-surface thesis (TI 2026): INVERTED

The standing hope since June: "new listings are soft before MMs arrive."
TI was the first big new surface captured from birth (v1.68 fixed the
dota2- index hole 16 days before the event). Result:

| | TI Dota (n=49-66) | CS2 same window (n=457-502) |
|---|---|---|
| median spread @T-1h | **1.0c** | 2.0c |
| median ask-depth @T-1h | **$18,952** | $473 |

TI launched **40x deeper and 2x tighter than the incumbent surface.**
Multi-million-dollar markets attract professional liquidity from listing
day. The soft-young-market window does not exist at exactly the events
liquid enough to matter. Residue: TI favorites at T-30min showed +10.3c
(n=24, t=1.58) — post-hoc subgroup, insignificant, no forward surface
until the next major, and the identical pattern class (tournament-local
calibration quirks) failed every out-of-sample test this summer (LoL July,
R1 backfill, in-play). Not a strategy.

bo3 book comparison: unavailable — 1,183 bo3 winner keys in the window
contain zero Dota (bo3.gg is CS2-only). Noted, not assumed.

## Verdict 3 — Far-lead books (48h-120h): KILL

New data class since v1.69 (2026-08-03). n=274 resolved with far-lead
quotes:

- Buy side A at far ask: **EV −11.5c/share (t=−4.08)**; side B: −5.0c.
  Both sides negative = the far spread+vig eats everything.
- Far books ARE less informed than near books (0.45-0.65 bucket: far ask
  0.539 → 43.3% win rate, vs near 0.546 → 55.3%) — but the miscalibration
  is smaller than the cost of trading against it. The inefficiency is real
  and unharvestable at taker. (Maker seat on $10-50-depth far books =
  the same dead-end scale as every maker lane this summer.)

## Verdict 4 — R1 paper gate: fizzle, retire

108 resolved over 50.5 days, ROI +1.8%, rate fallen to 2.2/day. To hit its
GO-LIVE bar (n≥150 & ROI>+10%) the next 42 trades would need ≈+31% ROI.
The gate cannot realistically GO; it never came near KILL either. This is
the pre-registered equivalent of a null result. Recommend: stop the clock,
record as expired-null.

## Side notes

- 100T roster ticket (never placed): YES now 0.065 with 5 days left, no
  roster change made — heading to the ~74% NO outcome our own base rate
  predicted. The $5-10 test stake was never risked.
- Liquipedia 429 block resolved itself in August (backoff + compliant UA);
  news capture ran clean through TI.
- POLY airdrop side-lane remains designed-but-unexecuted; it is a
  zero-cost lottery ticket, not a strategy, and stays user-optional.

## The complete graveyard (15 lanes, all measured)

crypto updown taker · crypto updown maker · esports wallet-fade (2 windows)
· WTA/ATP/MLB/NHL fades · follow-the-bookmaker (0-6) · props taker · props
maker · in-play contrarian · settlement-lag · ladder arb · calibration
bands · steam · perps carry · roster-change homework · news-lag harvester
· young-surface (TI) · far-lead taker · R1 recalibration (null)

## Bottom line

Every hypothesis this infrastructure was built to test now has a measured
answer, and every answer is no. Total tuition across 4.5 months: ~$200
realized. The residual inefficiencies that exist (far-lead miscalibration,
tournament-local favorite bias) are each smaller than the fee+spread wall
that guards them at this bankroll. There is no strategy in this data.

Recommendation: decommission the capture fleet (keep the archives), leave
the wallet's ~$313 for the user's stated skins plan, and close the program
with the methodology as the asset: pre-registration, fill-true pricing,
placebo controls, and required-base-rate inversion transfer to any future
market where the user's capital is large enough to matter.
