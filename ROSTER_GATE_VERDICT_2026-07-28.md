# Roster-change homework gate — VERDICT: KILL (2026-07-28)

Pre-registered gate (frozen in `EDGE_HUNT_BRIEF_2026-07-28.md` before any book
was priced): **GO iff ≥5 live markets show hazard-corrected P(YES) − executable
ask − fee ≥ +10¢ at ≥$20 depth within 2¢ of touch (or the NO-side mirror).**

**Result: at most 4 markets can clear. The gate is unreachable. KILL.**

## What killed it: depth, not probability

23 live roster-change markets. **Only 8 have ≥$20 executable depth on either
side** — the other 15 are books of $2–$19, unfillable at any size that matters.
Of those 8, most require probabilities no base rate can produce:

| market | side | cost | depth | needs P(YES) | needs base rate | verdict |
|---|---|--:|--:|--:|--:|---|
| bilibili-gaming | YES | 0.964 | $478 | >1.00 | — | impossible |
| bilibili-gaming | NO | 0.071 | $355 | ≤0.822 | 5.7 of 5 yrs | impossible |
| furia | NO | 0.880 | $23 | ≤0.008 | negative | impossible |
| astralis | NO | 0.860 | $179 | ≤0.026 | negative | impossible |
| betboom | NO | 0.760 | $62 | ≤0.116 | ~0 of 3 yrs | **fails** (see below) |
| team-liquid | YES | 0.390 | $79 | ≥0.529 | 4.2 of 5 yrs | **fails** (researched 3/5) |
| astralis | YES | 0.330 | $57 | ≥0.463 | 4.0 of 5 yrs | open, unlikely |
| nrg | YES | 0.300 | $60 | ≥0.430 | 3.4 of 5 yrs | open |
| 9z | YES | 0.400 | $200 | ≥0.540 | 4.6 of 5 yrs | open |
| **100-thieves** | **YES** | **0.100** | **$35** | **≥0.210** | **1.4 of 5 yrs** | **CLEARS** (2/5 → edge **+14.7¢**) |

1 confirmed clear + 3 still open = **maximum 4 < 5 required.** No further
research can change the outcome, so the remaining three were not completed.

**BetBoom detail** (the market that sealed it): founded summer 2023, so 3
fielded years, and demonstrably churny — s1ren and zorte joined **2023-07-31**
(inside the window) and summer 2025 saw zorte benched plus an ArtFr0st loan.
The NO side needed ~0 of 3 years with a summer change. It is not close.

## The real lesson: the spread eats the edge

These markets are wide *because* they are tiny, and the same thinness that keeps
professionals out also makes the quotes unplayable. A 0.14/0.33 book on Astralis
means you pay 33¢ for YES or 86¢ for NO — the fair value would have to sit
outside that whole range plus 10¢ plus fees. **The edge-hunt's premise (thin
books = pro-free zone = our size) was half right: the pros are absent, but so is
any price you'd want to trade.** Only 100 Thieves, quoted at a genuine 10¢ with
$35 behind it, produced a real edge.

## What was banked (this was not wasted)

1. **Base-rate table** for 6 orgs under the exact resolution definitions —
   NaVi 2/5, Team Liquid 3/5, Sentinels 1/5, Falcons 2/5, Paper Rex 1/5,
   100 Thieves 2/5 (`output/roster_gate/research_rows.json`). Reusable for the
   next transfer window, when new markets list at fresh prices.
2. **The required-base-rate inversion method** — invert the gate to ask "what
   would this market have to believe?" *before* researching. It killed 6 of 10
   sides on arithmetic alone, at zero research cost. Use this first from now on.
3. **A resolution-source correction**: CS2 markets resolve on the **HLTV**
   Starter table, LoL/Valorant on the **Liquipedia** Active table. The brief
   assumed Liquipedia throughout.
4. **The ambiguity trap, now documented**: NaVi's jL (benched 2025, released
   2026-07-01) and Team Liquid's inactive pair generate "player leaves org"
   headlines that do NOT qualify — but the fine print's "consensus of credible
   reporting" fallback gives a resolver a path to YES anyway. Any future entry
   in this category must discount markets where the bench/starter distinction
   is load-bearing.
5. **Infrastructure (v1.67)**: 53 roster markets are now in the index and the
   price-capture evergreen lane archives their books — the category is no longer
   invisible to us, and the next window starts with price history.

## If revisited

Do not re-run this gate on the current markets — prices would have to move a
lot. Re-run at the **next transfer window** (Nov–Dec offseason or next June),
when new markets list, using the banked base rates and the inversion method
first. A single qualifying market (100 Thieves at +14.7¢) is not a lane; it is
one bet, and the pre-registration deliberately refuses to trade on one.
