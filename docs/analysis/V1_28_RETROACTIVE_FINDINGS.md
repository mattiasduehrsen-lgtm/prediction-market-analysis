# v1.28 Retroactive Analysis — The Strategy Was Never Positive-EV

**Created:** 2026-05-07
**Method:** Apply v1.28 corrections (TP exit at exact `take_profit`, share count × 0.955) to all 693 historical MR-15m PAPER trades and recompute EV.
**Script:** `analyze_v1_28_retro.py`

---

## The headline

| Population | Old EV | v1.28 Corrected EV | Total |
|---|---|---|---|
| MR-15m all (n=693) | +$0.12/trade | **-$0.98/trade** | -$677 |
| ETH all (n=268) | +$0.75/trade | **-$0.46/trade** | -$123 |
| ETH UP (n=145) | +$0.87/trade | **-$0.43/trade** | -$63 |
| ETH DOWN (n=123) | +$0.61/trade | **-$0.49/trade** | -$60 |
| **SOL UP (n=74)** | +$1.72/trade | **+$0.53/trade** | +$39 |
| BTC UP (n=194) | +$0.05/trade | -$1.05/trade | -$204 |
| BTC DOWN (n=135) | -$1.23/trade | -$2.16/trade | -$291 |
| SOL DOWN (n=22) | -$3.88/trade | -$4.45/trade | -$98 |

**ETH t-stat vs zero (v1.28 corrected): t=-0.71, p≈0.48.** Statistically indistinguishable from zero, but the point estimate is firmly negative.

**The "+$0.12 EV" baseline from the original Cowork May 5 review (and the Opus reanalysis) was entirely the PAPER over-statement artifact.** With honest accounting, the current strategy has no positive-EV configuration except the n=74 SOL UP sub-segment.

---

## TP-win detail (the dominant correction)

329 take_profit wins across MR-15m:
- Avg recorded `exit_price`: **0.668**
- Avg `take_profit` setting: **0.644**
- Avg gap: **+0.024** (PAPER recorded TP exits 2.4¢ above the actual TP fill)
- Avg PAPER over-statement per winning trade: **-$2.07**

Soft_exit_stalled exits (n=294) and hard_stop_floor (n=67) are essentially unaffected by the TP fix; they're only touched by the share discount, contributing -$0.13 to -$0.24/trade.

So the LIVE-vs-PAPER drag was almost entirely from PAPER over-stating winners by ~$2/win.

---

## What this means for next steps

### Re-evaluate the "wait for new data" plan

The plan after v1.28 was:
1. Wait for ~50-100 new PAPER trades on the corrected accounting
2. If PAPER ETH still positive, consider sizing LIVE up to $15-20
3. If not, pivot strategy

The retroactive analysis short-circuits step 1. PAPER ETH was never positive-EV under honest accounting — there's no reason to expect new PAPER ETH trades to behave differently than the n=268 historical baseline. Waiting confirms what the data already says.

### Honest LIVE-resume calculus

| Asset | Side | n | v1.28 EV | LIVE recommendation |
|---|---|---|---|---|
| BTC | UP | 194 | -$1.05 | Off (already off v1.27) |
| BTC | DOWN | 135 | -$2.16 | Off (already off v1.21) |
| ETH | UP | 145 | -$0.43 | **Recommend off (this commit, v1.29)** |
| ETH | DOWN | 123 | -$0.49 | **Recommend off (this commit, v1.29)** |
| SOL | UP | 74 | +$0.53 | Keep eligible — only +EV segment |
| SOL | DOWN | 22 | -$4.45 | Off (already off v1.21) |

After v1.29, LIVE will run **SOL UP only**. With +$0.53 PAPER EV and an estimated ~$0.10 residual drag (post-v1.28 fixes), expected LIVE EV ≈ +$0.43/trade at $5 size. Marginal but positive.

### Bigger picture: is the strategy salvageable?

n=74 SOL UP is small. The 95% CI on its EV is roughly [-$2, +$3]/trade — wide enough that "+$0.53" could easily be noise. The honest answer is:

- **No part of the bot has a confirmed positive edge** at the n needed for $5 LIVE to be material
- ETH had appeared to be the "real thesis" — that was wrong
- SOL UP looks promising but n=74 is too small to commit capital
- The strategy as currently designed is closer to a coin flip than to alpha

**The next session should consider whether to:**
1. Continue PAPER data collection on all three assets to grow SOL UP's n
2. Pivot to a different alpha hypothesis (different markets, different time horizons, ML on existing features)
3. Pause development and accept the bot as a learning exercise

The honest framing matters: we now know what we have. We don't have a profitable bot. We have a data-collection apparatus and a clean baseline.

---

## Caveats

- The 0.955 share discount is empirically validated against multiple LIVE BTC trades but may not be exactly right for all assets/sizes. If actual is 0.95 or 0.96, the retroactive EV shifts by ~$0.05/trade.
- For DOWN trades, the recorded `exit_price` field may already reflect the DOWN side (1 - cur_up). The retroactive analysis used the recorded `exit_price` directly, which should be correct regardless of side.
- The TP correction only fires when `exit_reason == "take_profit"`. soft_exit_stalled / hard_stop_floor / force_exit_time exits use the recorded `exit_price` (which for PAPER was `cur_up`, matching the cheap-side observed price — same approximation as LIVE's FOK fill). So those exits are correctly handled.
- The corrected EV is a point estimate. For ETH (t=-0.71), we cannot statistically reject EV=0. The recommendation to disable ETH on LIVE rests on point-estimate-driven risk management, not on statistical significance — same logic as the v1.27 BTC UP disable.
