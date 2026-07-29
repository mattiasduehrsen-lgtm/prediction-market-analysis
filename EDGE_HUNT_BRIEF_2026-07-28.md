# Edge-hunt brief — 2026-07-28

18-agent adversarial workflow (5 finders → dedup → per-candidate refuters with
live CLOB/Gamma probes → synthesis). 19 candidates; 10 refuted with receipts;
**2 survivors**. Bankroll $313; everything shared-data-based already measured
dead. Shortlist is two entries, not five, because padding with refuted material
would be dishonest.

---

## SURVIVOR #1 — Liquipedia-resolved roster-change markets (esports, PRIMARY)

Polymarket launched an esports event category ~Jun 23, 2026: **"Will 〈org〉 make
a roster change before September?"** — ~20 live markets across CS2/LoL/Valorant
(T1, Astralis, NaVi, Vitality, Spirit, MongolZ, BLG, C9, Sentinels, Paper Rex,
100T, GamerLegion, MOUZ-before-Cologne…). Verified resolution text: resolves YES
on any change to the org's **Liquipedia "Active" roster table** — benching
counts; coaches and single-event stand-ins don't; 48h-persistence clause;
credible-reporting fallback. Fee-enabled (10% × min(p,1−p)).

**Why it can pay:** fan NO-money that hasn't read the fine print or priced
offseason churn base rates; slow NO-holders after announcements (GamerLegion sat
0.75–0.90 for ~18h post-move). **Why it persists:** books hold $2.50–$490 —
invisible to anyone with a real bankroll, exactly our size; day-scale horizon
neutralizes the 1s-latency constraint; resolution source is the feed NewsCapture
already polls every 5 minutes.

**Audit corrections (kept honest):** the "C9 50¢→99.9¢ capturable" story is
FALSE — it was a multi-day insider ratchet; a wiki-watcher gets only the last
mile. Quoted mids are phantom on near-empty books (T1 "35¢" = 0.06/0.63) — all
edges must be restated at executable ask/bid minus fee. And our 2.7M held
snapshots contained ZERO roster books (no `game_start` → filtered out of
capture) — fixed in v1.67 (evergreen capture lane + index pattern).

**Pre-registered validation (frozen now, before any book work):**
- (a) Per live market: scrape the org's Liquipedia roster/transfer history
  2021–2025 under the exact resolution definition; compute base rate of ≥1
  qualifying change in an Aug-equivalent window; **hazard-correct** for no
  change since Jun 29 (naive 2-month rates bias YES; churny teams already
  resolved — the survivor set skews stable).
- (b) **GO iff ≥5 markets** where hazard-corrected P(YES) − best_ask −
  0.10×min(ask,1−ask) ≥ **+0.10** with **≥$20 depth** within 2¢ of touch (or
  the NO-side mirror). **Else KILL.** One number, $0 risk.
- (c) Trigger leg (trade the Liquipedia edit within minutes) stays **OFF**
  until forward capture shows ≥3 qualifying edits with ≥10-min repricing lag at
  executable depth.
- (d) On GO: 3-week fill-true paper run, fees included; KILL if paper ROI < 0.

Effort ~4 days. Honest EV: **$10–30 per transfer window**, lumpy, seasonal;
category may become standing product (MOUZ-before-Cologne variant suggests so).

## SURVIVOR #2 — POLY airdrop eligibility at zero net cost (side lane, non-esports)

Token + airdrop officially confirmed (CMO, post-US-relaunch); eligibility meta
rewards consistent multi-month genuine activity — which our 2-year wallet has,
except recent activity is ~zero since the fade pause (a real cliff risk).
Vehicle: **$50–100 both-sides holding-rewards bundle in GEOPOLITICS-category
markets only** (sole fee-free category; the curated list's politics/crypto
entries are fee-bearing traps). Both legs accrue 3.25% APY per Polymarket's own
docs; pair redeems at exactly $1 → zero directional risk. **Explicitly
excluded:** maker quoting as "activity" (that lane died 0/28 on 2026-07-21).
Payout unfalsifiable → the gate sits on measurable COST:
- Step 1 ($0): pair premium = YES ask + NO ask − $1 on curated geopolitics
  entries; proceed only if < ~0.8¢ (APY repays inside 90 days).
- Step 2 ($5, recoverable): test bundle; verify 72h both-legs accrual.
- Step 3: size $50–100; monthly ledger from own records; **KEEP while net cost
  ≤ $0/month, KILL any month costing > $2.**

Effort 0.5 days. EV: one-time tail option $100–1,000, centered ~$300.

---

## Refuted (10) — one line each; full reasons in the workflow output

liquidity-rewards farming ×2 (incumbents already in-band; quadratic Q-score +
$1 payout floor); negRisk dutching ×3 variants (commoditized adapter-arb;
coherent MM; no held books); weather nowcasting (541-star free repo, sharps
arrived); market-age map (evidence misattributed; R1-in-disguise);
elimination-futures lag (own retro test: repriced in 1–2 min, empty books
elsewhere); bookmaker line-move lead-lag (PM never converges; own KILL branch);
TI-2026 "virgin surface" (false premise — BLAST Slam did $2.4–5.5M/match).

**The refutation pattern, for all future pitches:** every kill came from
fetching the actual object — live books falsified every "nobody's home" premise;
killed lanes returned in costume; $0 tests weren't runnable on held data. Before
any pitch earns a day: restate EV at executable prices minus fees, and confirm
its first test actually runs.

---

*Full workflow output (19 candidates, complete refutation texts): session task
file + journal. Infra shipped with this brief: v1.67 (roster markets into index
via `make-a-roster-change` pattern + price_capture evergreen lane).*
