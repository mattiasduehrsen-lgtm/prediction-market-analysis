# Live operational test — pre-registered 2026-08-03

**Purpose (stated before placing anything): this is an OPERATIONAL READINESS
test, not an edge deployment.** We currently have no validated edge; every
measured lane is dead and the news-lag study is not answerable until ~Aug 17.
The stake is tuition. What we are buying is knowledge of the live path on a
market class we have never traded.

## Why this vehicle

The roster-change gate KILLED the lane (max 4 markets could clear, 5 required)
— but exactly one market passed the frozen bar and still does:

- **`will-100-thieves-make-a-roster-change-before-september`**, YES side
- Live: **ask 0.10, ask-depth-2¢ $34.75**, feesEnabled=true
- Our number: base rate 2 of 5 years (researched under the exact resolution
  definition) → hazard-corrected **P(YES) ≈ 0.257** for the remaining window
- Required to clear: ≥ 0.21. Edge ≈ **+14.7¢** after the 10%×min(p,1−p) fee
- Resolves **2026-08-31** on the Liquipedia *Active* roster table for
  100 Thieves VALORANT (benching counts; coaches/stand-ins do not)

One qualifying market is not a lane — that is why the lane is dead. It is,
however, the right single ticket for a live test: it passed our own homework,
it is cheap, and it resolves on a mechanism (wiki-table resolution) we have
never once traded.

## Size

**$5–10.** At 0.10 that is 50–100 shares; fee ≈ $0.01/share (10%×min(p,1−p)),
so ~$5.50 all-in for 50 shares, paying $50 if YES. Max loss = the stake.

## What this test actually proves (and what it does not)

**Tests:** fee arithmetic vs. our predicted 10%×min(p,1−p); wallet/position
accounting on a non-match market; resolution mechanics on a wiki-resolved
market (does it settle when the table changes? how fast? does the
"credible reporting" fallback get used?); whether our monitoring and eval
pipeline see a position they were never designed for.

**Does NOT test:** the bot's order path (already exercised by 533+ historical
fills and the WTA live run) — this ticket is placed manually because building
roster-market trading logic for one bet is waste.

## Pre-registered success criteria (write down before, judge after)

1. Fill occurs at ≤ 0.11 effective (ask + fee) — else our fee model is wrong.
2. Position appears in wallet/eval tooling within 24h, or we find the gap.
3. At resolution: settles per the Liquipedia Active table, and we can point to
   the specific edit/report that drove it.
4. Verdict is recorded either way. **A loss is not a failed test** — P=0.257
   means we expect to lose this ~74% of the time. The test fails only if the
   *mechanics* surprise us in a way we cannot explain.

## What this test explicitly does NOT authorize

- Arming R1 live. Its pre-registration requires n≥150 and ROI>+10%; it sits at
  +0.4% with ~89 resolved. Going live now would break the discipline that has
  held total losses to ~$200 across the whole project.
- Re-entering any killed lane (wallet-fade, props, in-play, crypto, WTA).
- Scaling this ticket. One market, one stake, no averaging down.

## Optional second test (independent, also tiny)

The airdrop side-lane's own step 2: a **$5 both-sides bundle** in a fee-free
geopolitics holding-rewards market, to verify rewards accrue on BOTH legs at
~value×0.0325/365 and confirm the fee-free category is genuinely fee-free.
Zero directional risk (pair redeems at $1). Independent of the ticket above.
