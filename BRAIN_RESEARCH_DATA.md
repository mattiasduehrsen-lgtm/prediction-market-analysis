# Brain Research — Data Analysis

**Date:** 2026-05-10
**Data:** `cowork_snapshot/5m_trading/trades_v1_29_postdeploy.csv`, MR-15m subset, n=721 PAPER trades after v1.28 corrections.
**Baseline:** Overall EV = -$0.998/trade, WR 47.7%.

---

## TL;DR

- **The old `claude_advisor.py` was structurally doomed.** It asked Claude to predict which side wins on a single 5-minute window using only momentum text, with no decision frame for cost of skipping vs cost of entering. A reasonable LLM reading "bet that X reverses" with bearish-sounding context will say SKIP almost every time. The 96% block rate is the prompt working as written, not the model failing.
- **17-feature ML found AUC 0.496. Yet a single rolling feature the ML didn't get — prior 8-trade WR within asset — shows a clean monotone gradient: prior WR <25% → next EV -$1.20; prior WR >75% → next EV +$1.71.** This is the strongest signal in the dataset, and it is exactly the kind of "story" feature a Claude reasoner with trade history can read.
- **Chronological 80-trade chunk EV autocorrelation is -0.03 (noise).** Chunks of strategy outcomes do *not* persist period-over-period. So a regime detector that says "the last 80 trades were bad, the next 80 will also be bad" has no signal. But a *short-window* (8-trade) recency signal does — regimes that matter for prediction are short, not long.
- **Best vs worst 50-trade windows are clearly distinguishable in features:** TP rate 76% vs 32%, |cross_window| 0.026 vs 0.048, side mix UP-skewed in best vs DOWN-skewed in worst. These features could be recognized by a reasoner watching incoming trades.
- **Upper-bound test:** an oracle that perfectly identified low-|btc_pct_change| trades (bottom quartile) would lift EV from -$1.00 to **+$0.45** — a $1.92/trade gap vs the trending tail. That is the realistic ceiling on what regime classification can do; meaningful but not transformative.

**Verdict: (b) brain has marginal-but-real signal. Recommend small experiment with a recency-aware advisory prompt; do not expect transformation.**

---

## Q1. Why claude_advisor.py failed

### What the prompt actually said

```
PROPOSED TRADE: Buy {side} side at {entry_price:.3f}
This bets that {asset} will REVERSE from its current move by window end.

{asset} CONTEXT RIGHT NOW:
- This window: {asset} moved {btc_dir} by {abs(cl_pct_change):.3f}%
- Current {asset} rate: {btc_rate_per_min:+.1f} $/min
- Momentum trend: {decel_desc} (10s/30s rate ratio: {btc_momentum_decel:.2f})
- Previous window: {asset} moved in {cross_desc}
- Cheap side price still falling: "YES — momentum not finished"

DECISION: Should the bot enter this trade (bet {asset} reverses) or skip?
```

### Five structural problems

1. **It invited a discretionary-trader mental model, not a systematic one.** The prompt frames every entry as "bet against current motion." A discretionary trader reading "BTC moved DOWN by 0.4%, momentum slightly decelerating, cheap side still falling" will say SKIP — that's basic technical analysis hygiene ("don't catch falling knives"). But this is not a discretionary trade: it's the **96th call** of a systematic mean-reversion strategy whose edge is already encoded in the price gate that *got us here*. The prompt threw away that edge and asked for a fresh trader-judgement override.

2. **There is no EV asymmetry in the prompt.** The prompt says wins pay $1 and losses pay $0 but never says the entry is at 0.30-0.39, so the implied break-even win rate (~33%) is buried. Without that, "BTC is moving against me" reads as a strict negative. With it, the question becomes "is the chance of reversal still ≥34%?" — which is far less binary.

3. **The bullish/bearish framing is rigged.** Look at the language hand-fed to Claude:
   - `"clearly decelerating"`, `"slightly decelerating"`, `"reversing"`, `"steady"`, `"accelerating"` — only one of five values is unambiguously good for our trade.
   - `"YES — momentum not finished"` vs `"NO — stabilizing"` — the prompt itself characterizes "still falling" as "momentum not finished," which screams SKIP.
   - `cross_desc` reports same-direction prev window with no commentary on whether that's good or bad.
   The model is being told what to think before being asked what to think.

4. **The decision being delegated is the wrong one.** The bot already passed cheap-side, edge, and liquidity gates before calling the advisor. The advisor was effectively asked: *"Reproduce a risk veto on top of our existing risk filters."* When you ask an LLM to be a final-stage skeptic on a setup that already has gates, it will skeptically veto — that's the role you assigned. The advisor wasn't predicting trade outcomes; it was performing the role of "second-guesser."

5. **No history, no context across calls.** Each call was stateless. Whether the bot just took 3 wins in a row or 3 stops in a row, the prompt looked identical. So the model couldn't say "the regime is currently working — take this." It only saw a single scary-looking momentum snapshot per call. The new `window_brain.py` fixes exactly this with `sync_from_csv` + recent-trade history block.

### Lesson for window_brain.py

The new brain (`window_brain.py:166-241`) avoids all five problems:
- It does NOT ask for a direction prediction (line 9-10: *"NOT a direction predictor"*).
- It returns a continuous `edge_modifier` ∈ [-0.05, +0.05], not binary ENTER/SKIP (line 11-12).
- It frames the question as "is mean-reversion working *for this asset right now*?" — a regime question, not a trade question.
- It includes 10 prior resolved trades + WR + streak summary, so the model has cross-window context.

**Risk for the new brain:** the system prompt's "Key failure modes" section (lines 55-58) lists what a *bad* regime looks like in vivid language, while "Key success signals" (lines 60-63) is shorter and weaker. This could re-create the bearish-bias problem in subtler form. Worth A/B testing the prompt with the success/failure paragraphs swapped to check for asymmetric framing bias.

---

## Q2. Context that ML missed

The ML test (`ML_FEATURE_EXPLORATION.md`) ran 17 entry-time numeric features through a gradient-boosted classifier. AUC 0.496. **What ML didn't have access to:**

### a) Sequential / story-shaped patterns ✅ has signal

ML had `recent_wr` if computed, but as a *number*, not a sequence. A reasoner sees:
> Last 8 ETH trades: WIN, WIN, WIN, LOSS, LOSS, LOSS, LOSS, LOSS — 3 wins then a stops cluster.

That last-3-trade run-length is qualitatively different from `prior8_wr=0.375`.

**Empirical test:** Per-asset rolling 8-trade prior WR vs next-trade EV:

| Prior 8-trade WR | n   | Next EV    | Next WR |
|-----------------:|----:|-----------:|--------:|
| <25%             | 184 | -$1.20     | 37.5%   |
| 25–50%           | 255 | -$1.60     | 47.5%   |
| 50–75%           | 220 | -$0.84     | 54.1%   |
| **>75%**         |  38 | **+$1.71** | 68.4%   |

Per-asset, ETH is even cleaner: prior WR >75% (n=28) → next EV **+$2.40**.

Correlation `prior8_wr → next_won` = +0.158. Small but real. ML *could* have used this if explicitly fed; the current ML run did not include `prior8_wr_within_asset` as a feature, only static features. **A reasoner that sees the trade history list directly will pick this up without us telling it to.**

### b) Cross-feature interactions ✅ has signal but redundant with single features

ML's gradient-boosted trees handle interactions natively, so anything decomposable would already show up. But interactions framed as *narrative* ("BTC consolidating + ETH following + low cross-window") are the kind a reasoner can compress into one regime label.

Empirically, the best-50 vs worst-50 windows differ on:
- TP rate: 76% vs 32%
- |cross_window|: 0.026 vs 0.048
- side mix: best is balanced (27 UP / 23 DOWN); worst is DOWN-heavy (29 / 21)

So the worst window correlates with "downside-skewed entries during high cross-window churn." A reasoner reading "we're seeing mostly DOWN entries and the cross-window movement is double the recent average" can label this as a trending-down regime. ML does this implicitly but loses interpretability and doesn't carry the label across windows.

### c) Asymmetric / EV-aware reasoning ⚠️ unclear if usable

LLMs can in principle reason "this setup is bad but the entry price is so cheap the EV is still acceptable." The bot's edge gate (price < Binance-implied) already encodes a version of this. The marginal value of asking the brain to do additional EV reasoning is low *unless* the brain has access to current realized vol or current liquidity that changes implied probability. The new brain does pass `rv_std`, `edge`, `entry_price` — that's enough to ask the right question.

### d) Counterfactual / regime-break reasoning ✅ has signal at chunk-boundary moments

The data shows clear regime breaks (May 1 crash, v1.28 deploy). A reasoner with date awareness ("this window is during the post-crash high-vol period") could in principle adjust. **But this requires the bot to feed regime-context metadata** the brain can't otherwise know. The current brain prompt does not include any week-of-data or recent-vol context — only the 10-trade window. That should be added.

---

## Q3. Regime persistence test

### Chronological 80-trade chunks (MR-15m, n=721)

| Chunk | n  | WR    | EV     | Total    | TP rate | Stop rate | |btc_pct_change| | |cross_window| |
|------:|---:|------:|-------:|---------:|--------:|----------:|------------------:|----------------:|
| 0     | 80 | 30.0% | -$0.42 | -$33.91  | 30.0%   | 70.0%     | 0.070             | 0.093           |
| 1     | 80 | 25.0% | -$2.24 | -$179.09 | 23.7%   | 75.0%     | 0.085             | 0.080           |
| 2     | 80 | 60.0% | +$0.25 | +$19.59  | 60.0%   | 40.0%     | 0.040             | 0.023           |
| 3     | 80 | 58.8% | +$0.05 | +$4.27   | 58.8%   | 41.2%     | 0.043             | 0.053           |
| 4     | 80 | 57.5% | -$0.35 | -$27.71  | 57.5%   | 42.5%     | 0.039             | 0.049           |
| 5     | 80 | 46.3% | -$2.84 | -$226.92 | 46.3%   | 53.7%     | 0.040             | 0.046           |
| 6     | 80 | 42.5% | -$2.37 | -$189.54 | 42.5%   | 56.2%     | 0.042             | 0.059           |
| 7     | 80 | 57.5% | -$0.06 | -$4.85   | 57.5%   | 42.5%     | 0.026             | 0.043           |
| 8     | 80 | 52.5% | -$0.91 | -$72.90  | 52.5%   | 46.3%     | 0.025             | 0.055           |

- **Lag-1 chunk EV autocorrelation: -0.028** (essentially zero).
- **Sign flips: 2 across 9 chunks** — only because most chunks are negative; the early-data chunks 0–1 are visibly different from chunks 2–4 (high-vol regime → quiet regime), then chunks 5–6 are another bad cluster.

### Verdict on chunk-level persistence

**Chunk-to-chunk EV does not persist** at the 80-trade horizon. A regime detector trained to say "last 80 trades were good, next 80 will be good" has no signal at this horizon.

**But shorter-horizon recency does persist** (Q3b in script). The prior 8-trade WR predicts next-trade WR with correlation +0.158, and the EV gradient across prior-WR buckets is monotone. So:
- ❌ "We've had a bad week, next week will be bad" — false at this data scale.
- ✅ "We've had a bad streak in the last 8 trades, the next trade is also slightly worse-than-average" — supported.

This matches the design choice in `window_brain.py` (BRAIN_HISTORY_LEN default 10). 10 is in the right ballpark; 50–80 would be too long.

---

## Q4. Signature of profitable vs unprofitable periods

### Best 50-trade rolling window (EV +$3.26, WR 76.0%)

- **TP rate: 76.0%** | stop/stalled: 24.0%
- Asset mix: BTC 30, ETH 19, SOL 1
- Side mix: UP 27, DOWN 23 (balanced)
- |btc_pct_change| at entry: **mean 0.043**, std 0.052
- |cross_window|: **mean 0.026**, std 0.023
- Top exits: take_profit ×38, hard_stop_floor ×6, soft_exit_stalled ×6
- Liquidity: ~33,700
- Entry price: 0.386

### Worst 50-trade rolling window (EV -$5.15, WR 32.0%)

- **TP rate: 32.0%** | stop/stalled: 68.0%
- Asset mix: BTC 29, ETH 16, SOL 5
- Side mix: **DOWN 29, UP 21 (downside-heavy)**
- |btc_pct_change|: mean 0.032, std 0.042
- |cross_window|: **mean 0.048 (~2× best window)**, std 0.062
- Top exits: soft_exit_stalled ×19, take_profit ×16, hard_stop_floor ×15
- Liquidity: ~31,000
- Entry price: 0.388

### Distinctive features

1. **TP rate is the headline difference.** 76% vs 32%. When mean-reversion works, prices snap back to the TP threshold. When the regime breaks, prices stall mid-window or punch through to stop.
2. **|cross_window| nearly doubles in the worst period (0.048 vs 0.026).** Persistent multi-window directional motion is the killer. This is the single feature with the largest best-vs-worst ratio.
3. **Side mix flips:** the worst window had 58% DOWN entries vs 46% UP in the best. This may be a market-microstructure artifact (DOWN trades are systematically worse: see V1_28_RETROACTIVE_FINDINGS, all DOWN segments are negative-EV).
4. **Stalled exits dominate the worst period (19/50 = 38%)** vs only 12% in the best. This isn't trending — it's "price moved partway to TP and got stuck," consistent with thin order book / low cross-asset volatility regime where the contrarian flow that produces TP fills doesn't appear.

A reasoner who sees the recent trade list will pick up "stops/stalls outnumber TPs 3:2 in the last 10 trades, and most are DOWN" — that maps cleanly onto the worst-period signature.

---

## Q5. Upper bound of regime classification value

### Empirical test of simple ranging/trending labels

| Proxy definition | Ranging EV | Trending EV | Gap |
|---|---:|---:|---:|
| `|btc_pct_change|<0.0015 & |cross_window|<0.0005` | +$1.51 (n=3) | -$1.01 (n=718) | +$2.51 |
| `|btc_pct_change|<median` | -$0.25 (n=360) | -$1.75 (n=361) | **+$1.50** |
| `|cross_window|<median` | -$0.98 (n=360) | -$1.02 (n=361) | +$0.05 |
| **`|btc_pct_change|<25th-pct`** | **+$0.45 (n=179)** | -$1.48 (n=542) | **+$1.92** |
| Both below median (truly quiet) | -$0.52 (n=201) | -$1.18 (n=520) | +$0.66 |

### Quartile EV scan

- `btc_pct_change_at_entry` quartile: Q0=+$0.52, Q1=-$0.97, Q2=-$1.07, Q3=-$2.47 — **monotone decreasing**, the only feature with this property.
- `cross_window_pct` quartile: Q0=-$1.77, Q1=-$0.12, Q2=-$1.08, Q3=-$1.00 — non-monotone, weak.
- `liquidity` quartile: -$1.67 / -$0.43 / -$1.09 / -$0.80 — non-monotone, no clear signal.

### Upper-bound interpretation

- **A perfect "ranging vs trending" classifier using `|btc_pct_change|<25th-percentile` would lift EV from -$1.00 → +$0.45.** That's the realistic ceiling.
- **An oracle keeping only the +EV half of trades** would deliver +$8.63/trade — but that's an unachievable upper bound; nothing the bot can know at entry time predicts trade outcome at that resolution (the ML test confirms this: all the model can extract from full features is AUC 0.496).
- **ETH-specific upper bound is higher:** ETH UP with prior 8-trade WR >75% gives EV +$2.40 on n=28. If the brain can reliably identify just this segment, it lifts the SOL-UP-only-LIVE world to a SOL-UP-+-ETH-UP-when-hot world, which roughly doubles the eligible trade flow at meaningful EV.

### So how much can a brain actually move EV?

If the brain achieves 70% of the perfect-`|btc_pct_change|<25th` classifier (which is generous — it's working from prose, not a numeric threshold), it might claw back ~$1.30/trade of the $1.92 oracle gap. On 100 trades/week that's $130/week of EV improvement at PAPER scale, ~$10/week at $5 LIVE size on the SOL-UP-only configuration.

**This is meaningful but not transformative.** A brain cannot make this strategy great. It can plausibly turn a -$1.00 EV strategy into a -$0.30 to +$0.20 EV strategy on the segments where it's confident — provided the prompt avoids the bearish-bias trap that broke `claude_advisor.py`.

---

## Verdict

**(b) Brain has marginal-but-real signal. Recommend small experiment.**

Specifically:
1. The empirical signal that exists in the data is **short-horizon recency** (prior 8-trade WR within asset) and **`|btc_pct_change|` magnitude**. Both are visible to the new `window_brain.py` (the recency via the history block, the btc magnitude indirectly via `cross_window_pct` and price history).
2. The realistic upper bound for *any* regime classifier on this data is +$1.50–$2.00 EV improvement per trade — meaningful, not strategy-saving.
3. Critically: keep the brain in **advisory mode (modifier ±0.05) NOT veto mode**. The Q1 analysis shows binary delegations create catastrophic asymmetric framing failures. A continuous edge modifier preserves the bot's deterministic logic and only nudges the gate.
4. Test the prompt for **bearish-asymmetry bias** — the current `_SYSTEM` (window_brain.py:44-67) has more vivid failure-mode language than success-signal language. If on first 100 advisory calls the modifier averages substantially > 0, the prompt is unconsciously biased toward "degraded."
5. **Add explicit recent-WR and recent-EV summary lines to the prompt's user message** — the model is more likely to use this signal when it's pre-computed than when it has to count outcomes from the history list.
6. Do not expect the brain to fix the strategy. The retroactive analysis shows the strategy's structural haircut (TP=0.60 net of fees and 0.955 share discount → ~-$1.99/loss vs +$2.50/win) requires ~44% WR to break even, and the current 47.7% is barely above that. A brain can shift trade selection toward the +EV tail; it cannot change the loss/win asymmetry.

If after 200 advisory-mode calls the modifier shows no correlation with subsequent trade outcomes, kill it. If it shows ≥+0.1 correlation between `-modifier` (looser gate calls) and pnl_corrected, escalate to actually using the modifier, then later consider veto.

---

## Files referenced

- Analysis script: `C:\Users\home user\Desktop\prediction-market-analysis\_brain_research_analysis.py`
- Source data: `C:\Users\home user\Desktop\prediction-market-analysis\cowork_snapshot\5m_trading\trades_v1_29_postdeploy.csv`
- Failed advisor: `C:\Users\home user\Desktop\prediction-market-analysis\src\bot\claude_advisor.py`
- New brain: `C:\Users\home user\Desktop\prediction-market-analysis\src\bot\window_brain.py`
- Prior ML result: `C:\Users\home user\Desktop\prediction-market-analysis\ML_FEATURE_EXPLORATION.md`
- v1.28 baseline: `C:\Users\home user\Desktop\prediction-market-analysis\V1_28_RETROACTIVE_FINDINGS.md`
