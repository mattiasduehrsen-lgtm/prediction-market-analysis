# Brain Research — Architecture & Design

**Created:** 2026-05-10 (alongside v1.32 advisory deploy)
**Status:** Design review. No production code in this document.
**Author audience:** future-me, picking up the brain promotion sequence.

---

## TL;DR

- **Recommended decision shape: Option A "regime classifier" (the v1.32 design) extended with a small per-trade `size_scalar` field, NOT Option B "per-trade enter/skip".** The ML null result (AUC = 0.496 across 17 entry-time features) means there is no per-trade signal to extract from the features Claude has visibility into. A per-trade ENTER/SKIP advisor is structurally the same task that ML failed at; expecting Claude to succeed where a gradient-boosted model trained on labelled history could not is wishful thinking. The previous binary advisor (`claude_advisor.py`) failed for exactly this reason, plus a discretionary-trader prompt drift.
- **Where Claude actually adds value: the regime / cross-window dimension that ML cannot exploit because of regime non-stationarity** (fold AUC straddles 0.41–0.54). Claude reading "last 10 trades + recent BTC trajectory" can adapt to a regime shift faster than ML can re-train, and it integrates qualitative context (loss-cluster shape, streak, time-of-day) that doesn't fit cleanly in a static feature.
- **Promote on outcome correlation, not on activity.** v1.33 should only flip the modifier from observation to live-arithmetic if the brain's regime classification has a measurable correlation with realised EV at n ≥ 80 brain-evaluated trades. Otherwise the brain stays in advisory mode forever or is removed.
- **The biggest risk is not "the brain blocks 96% of trades" — it's "the brain looks helpful at n=30 and bankrupts us at n=300".** v1.32→v1.34 phasing is therefore designed around minimum sample sizes per promotion gate, not around feature richness.
- **Hard-cap brain influence to ±0.05 edge_modifier (already done) and add a circuit breaker on call rate** (≤ 2× per window per asset). The cost is a rounding error; the reputational damage of "brain pinned itself open in a glitch and burned $200" is not.

---

## Q1. What decision should the brain make

### Option A — Regime classifier (v1.32 deployed)
- Output: `regime + mr_edge + edge_modifier ∈ [-0.05, +0.05] + reasoning`
- Bot uses modifier to tighten/loosen entry threshold.
- **Pros:** clamp-bounded blast radius; the bot's deterministic logic still drives entry, brain is a +/- nudge; cheap to keep on indefinitely; aligned with what's actually exploitable (regime, not per-trade direction).
- **Cons:** small ceiling on uplift. If brain is genuinely smart, it can shift edge by maybe 1–2¢ per trade — meaningful at scale, not transformative.

### Option B — Per-trade ENTER/SKIP + TP/SL/size suggestions
- **Pros (claimed):** richer reasoning, "thinks on every trade" matches user phrasing.
- **Cons (real):**
  1. **It's the same task ML failed at.** ML on 17 entry-time features got AUC 0.496 with confidence-monotonically-worse EV. A per-trade Claude advisor consumes a *subset* of those features (we cannot fit 700 trades worth of microstructure into a prompt). If a labelled supervised model can't separate winners from losers on full data, an LLM reading a smaller summary of the same data will not — at best it mimics the heuristics already in `signal_5m.py`, at worst it overweights narratively-compelling features ("the move hasn't finished") that ML showed have no predictive value.
  2. **The 2026-04 `claude_advisor.py` failure was not a tuning bug.** It blocked 96% of in-range windows. Re-reading its prompt: it asked the model to predict reversal direction ("should the bot enter this trade — bet asset reverses — or skip?"). That framing leaks into discretionary-trader thinking ("momentum not finished, skip"). Even with a better prompt, the *output shape* (binary gate) creates a 1-bit decision where the model's prior toward caution dominates whatever signal is in the context.
  3. **TP/SL/size suggestions** create a multi-dimensional optimisation surface where the brain can be "right on direction but wrong on TP", masking whether it's adding value at all. We cannot validate four outputs at n=50.
  4. **No mental model anchor survives high call volume.** Few-shot examples decay in influence as new context arrives. At trade #200 the model has long forgotten what we told it about "systematic mean-reversion thinking."

### Option C — Reflective / critic mode (post-decision review)
- **Pros:** cheap, doesn't add filter intelligence (the ML null says we don't *need* filter intelligence — we need regime intelligence).
- **Cons:** firing post-decision means the brain reads the same state the bot already used, and is structurally late. Either it duplicates the bot's logic (no value) or it adds a second opinion that the bot must already have implemented to act on (architecturally messy). Also, "tag risky trades for size reduction" is a feature in search of a problem — we have no evidence that size reduction on a flagged subset improves EV.

### Recommendation: **Option A, extended**

Keep v1.32's regime classifier shape. After v1.32 demonstrates correlation between brain calls and outcomes (gate at n=80), add **one** small per-trade output: `size_scalar ∈ [0.5, 1.0]` letting the brain damp position size when its confidence is low. Do **not** let the brain SKIP. Do **not** let the brain set TP/SL.

Rationale for this hybrid:
- The user's reframe ("thinks on every trade") is satisfied: the brain *is* called per trade and produces per-trade output (regime + reasoning + size scalar).
- The ML null is honoured: we don't ask the brain to do per-trade direction prediction.
- Blast radius is clamped: even with `size_scalar=0.5` on every trade, the worst case is "the bot sizes 50% smaller than baseline" — that's a P&L drag, not a portfolio risk. The 96% block-rate failure of the old advisor is structurally impossible.
- It anchors Claude's role to what it's plausibly good at vs what ML proved it can't be: regime/context, not direction.

The user's original framing — "thinks on every trade" — does NOT require Option B. Per-trade *thinking* is satisfied by per-trade *contextual reasoning*; it does not require per-trade *binary authority*. This distinction is the load-bearing argument.

---

## Q2. Prompt structure

### System prompt (cached, ~5 min TTL)

```
You are a regime classifier for a Polymarket 15-minute / 4-hour mean-reversion
prediction-market bot trading BTC, ETH, and SOL Up/Down markets.

## What the bot does
Each window, Polymarket creates a binary "Will [ASSET] be UP or DOWN at window
close?" market. Tokens trade in [0, 1]; the winning side resolves to $1.00. The
bot waits for the cheap side (~0.32–0.40 on 15m, ~0.28–0.45 on 4h) to fall into
its entry band, then BUYS that cheap side, betting the price will revert toward
0.50 before window close. It exits at take-profit (~0.60–0.65), stop-loss
(~10% drawdown), or window force-close.

## What you are doing
You assess whether mean-reversion *as a regime* is currently working for this
asset. You return a continuous `edge_modifier` in [-0.05, +0.05] that the bot
adds to its entry-edge gate, and a `size_scalar` in [0.5, 1.0] applied to
position size.

You are NOT predicting which side wins. You are NOT a discretionary trader. You
are NOT trying to time the bottom of the move. The bot does not need a market
forecaster — it needs a regime sanity check.

## Mental model anchor — read every call
Mean-reversion makes money when prices oscillate around fair value. It loses
money when prices trend in one direction for the whole window (the cheap side
keeps getting cheaper).

The single question you are answering is:
  "Given the last N trades on this asset, are we in a ranging or trending regime?"

## Reasoning patterns

GOOD reasoning (favoured):
- "Last 8 trades: 5 wins via TP, 3 stop-losses with median 50% through window.
   Looks like normal choppy regime. modifier=0.00, size_scalar=1.0."
- "Streak of 3 stop-losses, all UP side, all on the same asset on a >1% BTC
   move day. Trending regime — degraded MR. modifier=+0.03, size_scalar=0.7."
- "WR 70% over last 10, TP exits clustered. Strong ranging regime.
   modifier=-0.01, size_scalar=1.0." [NOTE: keep the looser-gate response small.]

BAD reasoning (do not produce):
- "BTC just moved hard, the bounce hasn't started yet, skip." ← This is
  discretionary direction-prediction. You don't predict direction.
- "I think the cheap side could go lower." ← Same.
- "Volume is unusually high; entering is risky." ← You're not a microstructure
  scalper. You only have access to recent CLOSED-trade history; do not invent
  features you do not see.
- "Edge is small, skip." ← The bot already gates on edge. Your job is the
  modifier on top of that gate, NOT a duplicate of it.

## What "context" you have, and what you don't
You SEE: last N closed trades (side, entry price, edge, exit reason, pnl, won),
recent WR, streak shape, the current candidate's static fields (price, edge,
realized vol, cross-window %, secs remaining).

You DO NOT SEE: order book depth, intra-window price path, BTC chart, news. Do
not pretend to. If your reasoning would require any of these, return modifier
0.00 with reasoning "insufficient_context".

## Output
Reply with EXACTLY this JSON object and nothing else. No markdown, no prose
before or after. Schema is fixed (see output schema in user prompt).
```

### User prompt (per call, ~150 tokens)

```
Asset: {asset} | Window: {window} | Strategy: mean_reversion

Last {n} resolved trades (oldest → newest):
{history_block}

Summary: {wins}/{n} wins ({wr}% WR), ${cum_pnl:+.2f} cumulative, streak: {streak}

Time-of-day buckets in last 20 trades: {hour_dist}      ← NEW (helps with regime)
Avg entry-to-exit duration in last 10: {avg_duration_s}s    ← NEW (regime cue)

Current candidate:
  Side: {side}    Entry: {entry_price:.3f}    Edge: {edge:+.4f}
  Realized vol: {rv_std:.4f} (>0.0029 = high-vol regime)
  Cross-window: {cw_pct:+.3f}%    Secs remaining: {secs:.0f}s

Return JSON:
{
  "regime": "ranging|trending|volatile|unclear",
  "mr_edge": "strong|normal|degraded",
  "edge_modifier": <float in [-0.05, +0.05]>,
  "size_scalar": <float in [0.5, 1.0]>,        ← NEW in v1.34
  "confidence": <"low"|"medium"|"high">,       ← NEW in v1.33
  "reasoning": "<one sentence, ≤25 words, no direction prediction>"
}
```

### How this prompt prevents discretionary drift

Three structural choices, in order of importance:

1. **The output channel is regime, not direction.** A model with no fielded "direction" output cannot leak direction prediction into the decision. It can leak it into `reasoning`, but reasoning is logged-only and doesn't affect trade execution.
2. **The system prompt enumerates GOOD vs BAD reasoning and explicitly forbids three concrete bad patterns** ("the move hasn't finished" being the one that killed `claude_advisor.py`). Few-shot negative examples are more durable than positive ones because they create a sharp gradient.
3. **Mental model anchor is restated at the top of every call** (cached, so cost is constant). LLMs drift toward whatever framing the user prompt suggests; if the user prompt always describes "the regime," the model stays in regime mode.

### Time-series context: how to keep it compact

Don't paste price arrays. Do:
- One-line per recent trade (`[7] DOWN @0.36 edge=+0.012 → WIN (take_profit) pnl=+$2.10`) — already in v1.32.
- Aggregate features: `avg_duration_s`, `hour_dist`, `streak`. These are what the brain actually uses.
- For the candidate: only static fields plus realized vol. We tested 17 features in ML and got nothing — there is no per-trade context worth pasting.

The total prompt fits in ~400 tokens (cached system) + ~250 tokens (per-call user). At Haiku rates with cache, ~$0.0005 per call, ~$0.005/day at current call rate.

---

## Q3. Output schema

### Schema (v1.33 target — adds confidence; v1.34 adds size_scalar)

```json
{
  "regime":         "ranging" | "trending" | "volatile" | "unclear",
  "mr_edge":        "strong"  | "normal"   | "degraded",
  "edge_modifier":  <float, [-0.05, +0.05]>,
  "size_scalar":    <float, [0.5, 1.0]>,           // v1.34 only
  "confidence":     "low" | "medium" | "high",     // v1.33+
  "reasoning":      <string, max 25 words>
}
```

### Validation rules — bot behaviour on bad output

| Failure mode | Bot response |
|---|---|
| API timeout (> `BRAIN_TIMEOUT`, default 6s) | Use NEUTRAL advice (modifier=0, scalar=1.0). Log `[BRAIN] timeout — neutral`. |
| API error (rate limit, 5xx, exception) | Same as timeout. Increment `_brain_error_count`; circuit-break after 5 errors in 60s — disable brain for 5min. |
| Response is not valid JSON | NEUTRAL. Log raw response (truncated to 200 chars) for postmortem. |
| Field missing | Default that field (regime="unclear", mr_edge="normal", modifier=0.0, scalar=1.0, confidence="low", reasoning=""). |
| `edge_modifier` out of range | **Clamp** to [-0.05, +0.05]. (Already implemented in v1.32.) Do not reject — clamping is the safer fail-mode. |
| `size_scalar` out of range | Clamp to [0.5, 1.0]. |
| `regime` is unknown enum value | Treat as "unclear", but accept the modifier (the categorical is for logging; the modifier is what affects behaviour). |
| `reasoning` over 25 words | Truncate, log warning, accept rest. Don't reject for cosmetic reasons. |
| `confidence` not in enum | Default to "low" (low confidence triggers conservative branch). |

### Why clamp-and-accept rather than reject-and-skip

If we reject malformed output and skip the trade, a single Anthropic-side prompt change or a cosmic-ray JSON corruption could halt all trading. Clamping fails open in the safer direction: a bad response degrades to neutral, not to "no trades for an hour." The blast radius of a single broken response is at most one trade's worth of suboptimal sizing, which is acceptable.

---

## Q4. Calling frequency

### Pattern recommendation: **once per entry candidate, after price-band passes, with a 30-second TTL within the same window**.

### Cost estimates

Assumed: 18 windows/day per asset on 15m + 6 on 4h = ~24 trade-eligible windows/day/asset × 3 assets = ~72 candidate evaluations/day. Not every window produces an entry candidate (many fail the price band) — call this 30 actual brain calls/day across the bot.

| Pattern | Calls/day | Haiku cost/day (with caching) | Latency exposure |
|---|---|---|---|
| Every poll (1–2s) | ~50,000 | ~$3.50 | very high — pollutes hot path |
| Once per window per asset | ~96 | ~$0.05 | low |
| Once per entry candidate (current v1.32) | ~30 | ~$0.015 | ≤1 call per trade decision |
| Multiple per window (entry + mid-window if drawdown + near close) | ~120 | ~$0.06 | adds latency on drawdown handling |

The 4× cost difference between "once per candidate" and "multi per window" is a rounding error. The reason to NOT do multi-per-window is not cost; it's that **mid-window calls would have to make exit decisions** (hold vs cut), which puts us back in Option B territory — the model now predicts direction. We rejected that.

**Stick with once-per-candidate.** Add a 30-second within-window TTL so multiple candidates inside the same 15m/4h window reuse the same advice (the regime doesn't change within a window). This is a small change to v1.32 (which currently calls fresh on every candidate) and saves ~50% of calls without reducing fidelity.

---

## Q5. Validation methodology

### v1.32 phase: shadow mode (current)

Log brain advice to bot.log on every call. Fields written to a parallel CSV
(`output/5m_trading/brain_log.csv`):
```
timestamp, asset, window, side, entry_price, edge, regime, mr_edge,
edge_modifier, confidence, reasoning, trade_outcome, trade_pnl
```
`trade_outcome` and `trade_pnl` are filled by a post-trade hook that joins on
the trade_id from `trades.csv`.

**Decision question:** does brain's regime classification correlate with realised pnl?

**Minimum n for v1.33 promotion gate:** 80 brain-evaluated, resolved trades, segmented by regime. Why 80?
- We need at least 30 trades in the largest single regime category to estimate
  EV with $1.50 SE (assuming $10 per-trade std). Smallest expected category
  ("strong") will be maybe 30% of calls → need ~100 total to hit n=30 strong.
- Round down to 80 because we accept some imprecision on the smallest
  category if the largest two have a clear EV separation.

**Promotion test:** segment realised pnl by `(regime, mr_edge)`:
- Pass: trades labelled `mr_edge="strong"` have mean pnl ≥ +$0.50 above
  trades labelled `mr_edge="degraded"`, with the difference > 1 standard error.
- Fail: no separation, OR direction is reversed (degraded > strong — meaning
  brain is anti-predictive).

### v1.33 phase: A/B in-sandbox

Once promotion gate passes, run a true A/B for n ≥ 200 trades:
- Half of entry candidates apply the modifier; half ignore it.
- Coin flip per candidate (deterministic on hash of `(window_start, asset)` so
  the assignment is reproducible).
- Compare mean pnl after 200 trades. Promote to "always on" if A (apply
  modifier) > B (ignore) by ≥ $0.30/trade. (Why $0.30: matches the magnitude of
  TP-overstatement in v1.28 — anything smaller is below-noise on n=200.)

**Why not pure observational comparison?** Because regime is endogenous to
recent trades. Trades classified "degraded" are more likely *because* a loss
streak just occurred — and loss streaks are autocorrelated by regime, which
biases pure observational comparison toward making the brain look smart even
if it's just identifying autocorrelation.

### Backtest replay

Tractable subset: **regime classification only**, on closed trade history. Replay
the brain on every historical entry where we have the full trades.csv row.
- Generate brain advice using only fields that were present at decision time
  (no leakage of subsequent trades).
- Compare brain's regime call to realised outcome.
- This validates the *prompt's* informational efficiency, not the live system.
- Cost: ~$3 to replay on 700 historical trades.

**Caveat:** historical context lacks live order book, intra-window price path. Brain replay only tests "given a trade summary plus recent history, can the model classify regime?" It does NOT test "does the brain help in real time." Use for sanity-checking the prompt; do not promote based on backtest alone.

### Confidence calibration

After v1.33's `confidence` field exists, bin trades by stated confidence:
- "high" confidence trades should have lower variance in pnl OR higher mean pnl.
- Plot Brier score / calibration curve at n ≥ 100.
- If "high" confidence does not separate from "low," the field is noise and
  should be removed.

### Decision threshold for v1.34 promotion (size scalar to active)

Same logic as v1.33: A/B for n ≥ 150 trades, requiring `size_scalar`-applied
trades to have ≥ $0.20/trade better EV-adjusted pnl than full-size trades. If
the brain damps size on its losing trades and not its winning trades, that's
the bullseye outcome.

---

## Q6. Failure modes specific to OUR setup

| Mode | Mitigation |
|---|---|
| **Anthropic API outage during a 4h window** | Fail open: bot trades using NEUTRAL advice. PAPER and LIVE both continue with their pre-brain heuristics. Logged but no alert — outages are short. |
| **Latency spike (5+s) when window has 30s left** | Hard timeout already at 6s. If timeout fires within 30s of window close, the bot still has time to enter on neutral advice. If timeout fires within 10s of window close, the bot skips the candidate (already its existing behaviour). |
| **Brain regime call disagrees with bot heuristic** | Heuristic wins on hard rules (asset disabled, BTC crash, liquidity floor, price band, edge gate). Brain's modifier is *additive* on the edge gate only. There is no rule the brain can override; the brain can only narrow or widen the gate slightly. This is by design. |
| **Cost runaway (e.g. 1000× brain calls in a glitch)** | Add per-process counter `_brain_calls_this_hour`. Hard cap at 200/hour (vs expected ~3/hour). Above cap → return NEUTRAL without calling API and log warning. Even 200/hr × 24 = 4800/day = ~$2.50 — well below "panic" but well above any legitimate rate. |
| **Adversarial / predictability** | The brain is reading our own private trade history and Binance public price. There is no path for an adversary to influence the brain's input *without* moving the public price (in which case they're losing money to do it). Predictability of brain output is irrelevant because the brain only modulates the gate, not the trade; even if an adversary knew our exact gate they cannot front-run a Polymarket binary entry meaningfully. |
| **The brain learns wrong lesson from biased history** | History is `last 10 closed trades` — short window. If the bot just ran 3 stop-losses during a black-swan move, the brain will say "degraded" — which is correct local behaviour even if it's a one-off event. The 10-trade window means stale lessons get flushed within ~6 hours of entries. Acceptable. |
| **Prompt cache invalidation cascades cost** | Anthropic's cache TTL is ~5 minutes. If we trigger cache miss on every call (e.g. by unique IDs in system prompt), cost goes 4×. Audit: system prompt is fully static in the spec above; user prompt is variable. Cache hit rate should be ~95%. Monitor `cache_read_input_tokens` in `resp.usage` — if it drops below 80%, investigate. |
| **JSON malformation drift (model retrained, output format changes)** | Validation rules (Q3) clamp+default rather than reject. We will see degraded brain output as `regime=unclear, modifier=0.0` for whatever fields drifted, not as "bot crashed." Monitor `BrainAdvice.is_neutral` rate; if it spikes from baseline (~5%) to >40%, investigate. |
| **Brain conflicts with PAPER/LIVE asymmetry** | PAPER and LIVE have different bands (v1.30: SOL ceiling 0.40 vs 0.35). Brain doesn't know about this, but it doesn't need to — it returns the same modifier and the bot applies its own asymmetric gates. |

---

## Q7. Phasing

### v1.32 — DEPLOYED 2026-05-10
**Pure observation.** Brain wired but `BRAIN_VETO=false`, modifier logged not applied. No trade behaviour change.

**Exit gate to v1.33:**
- ≥ 80 brain-evaluated, resolved trades in `brain_log.csv`.
- `mr_edge="strong"` mean pnl ≥ `mr_edge="degraded"` mean pnl + 1 SE.
- No critical brain failure (no >5% rate of malformed JSON; cache hit rate ≥ 80%).

If gate not met after 14 days: extend observation by 14 days. If still not met: decide whether to remove brain (no signal) or change prompt (current prompt is wrong) — do not promote on weak evidence.

### v1.33 — PROPOSED, conditional on gate above
**Activate edge_modifier; add `confidence` field.**

Specific changes:
1. In `main.py` MR entry path: `effective_gate = EDGE_GATE_MIN + advice.edge_modifier`. Skip if `edge < effective_gate`. (Already coded as a comment in `window_brain.py` docstring.)
2. Add `"confidence"` to the JSON schema and prompt.
3. Add `_brain_calls_this_hour` rate limiter at 200/hour.
4. A/B harness: deterministic 50/50 split on `hash(window_start, asset) % 2`. CSV logs the assignment. Half of entries use `effective_gate`, half use raw `EDGE_GATE_MIN`.

**Exit gate to v1.34:**
- ≥ 200 trades with A/B labels.
- A-arm mean pnl ≥ B-arm mean pnl + $0.30/trade.
- A-arm WR ≥ B-arm WR (sanity check — if A trades less and wins more, fine; if A trades less and wins less, the modifier is making us miss good setups).

### v1.34 — PROPOSED, conditional
**Add `size_scalar`; remove A/B coin flip (brain is now authoritative on the modifier).**

Specific changes:
1. Add `size_scalar` field to schema and prompt.
2. In LIVE entry path: `position_size = LIVE_POSITION_SIZE_USD * advice.size_scalar`.
3. Remove A/B labelling — modifier is fully on. Brain is now load-bearing.
4. Add monitoring: brain neutral-rate, brain timeout-rate, cache hit-rate dashboard.

**Exit gate to v1.35:**
- ≥ 150 trades with `size_scalar` applied.
- Size-scalar-weighted EV ≥ flat-size EV + $0.20/trade.
- Brain is operationally stable for 30 days (no cost spikes, no cascading failures).

### v1.35 — PROPOSED, conditional
**Brain becomes the entry orchestrator for 4h markets only.**

Rationale: 4h markets have 18× fewer windows/day. Each one matters more. The cost ceiling on brain calls becomes negligible (~5 calls/day on 4h).

Possible scope:
- Brain returns a richer object including TP/SL hints (still clamped to safe ranges).
- 15m markets stay on the v1.34 design.
- This is a scoped escalation toward Option B — only on the timescale where Option B's reasoning richness is most likely to pay off.

**This version is speculative — it depends on whether 4h markets show signal at all under v1.31's experiment.** If 4h is null (no edge), v1.35 is cancelled and the brain remains a v1.34-shape regime classifier indefinitely.

### What I'm NOT proposing

- No "brain blocks entries entirely" mode. The previous binary advisor failure is the canonical anti-pattern.
- No giving the brain access to live order book or Binance price arrays. The ML null says these features don't help; LLM consumption of them won't either.
- No multi-call-per-window. Cost is fine; the architectural complexity isn't worth the tiny information gain.
- No "brain fine-tunes its own prompt" or RLHF-on-trade-outcomes loop. Premature and not justified by the data we have.

---

## Open questions

1. **Is Haiku the right model?** Sonnet would catch subtle regime cues better but at 5–10× cost. At v1.34 scale (~30 calls/day) the absolute cost of Sonnet is still trivial (~$0.50/day). Worth A/B'ing Haiku vs Sonnet at v1.33 — but only after Haiku clears the v1.32 promotion gate. If Haiku can't pass the gate, Sonnet probably can't either; the bottleneck is signal in the prompt, not model capability.

2. **Should the brain also fire on EXIT decisions (early stop-loss waiver, hold past TP)?** Strongly tempting and strongly risky. The current data is only on entry; we have no validation methodology for exit-side brain calls. Defer until v1.35+ at earliest.

3. **What if the v1.32 promotion gate fails — brain is uncorrelated with outcome?** Two interpretations: (a) the prompt is bad, rewrite it; (b) the *task* is bad — there's no regime signal in 10-trade history either. Decision rule: rewrite the prompt at most twice. If three different prompts all fail the gate, kill the brain entirely. This codebase has a known pattern of layering complexity on dead strategies (see RS, see `claude_advisor.py`); resist it.

4. **How does the brain interact with the strategy pivot to 4h?** v1.31 is collecting 4h PAPER data with no brain involvement. The brain is currently 15m-only because the history is 15m. By v1.33 we should have ~14 days of 4h data and can decide whether to fork the brain into per-window instances or share history across windows. Pre-decision: separate instances, separate history per (asset, window). Cross-window contamination risks are higher than the benefit of pooled data.

5. **What does "user said 'thinks on every trade'" actually mean?** The user's framing was a strategic critique of static cascades, not a literal architectural requirement. Option A satisfies the spirit. If after v1.33 the user still feels the brain "doesn't think enough," that's the moment to revisit Option B — not before. Until then, treat the user's phrase as motivation, not specification.

6. **Is there a hidden Option D — brain as offline analyst, not live trader?** The `analysis_opus.py` and Cowork analysis flow already does this. If brain online doesn't pay off, redirect Claude budget to better/faster offline analysis cycles (e.g. weekly Cowork passes on accumulated trades). This is the honest fallback if v1.33's promotion gate fails twice.

---

*End of document.*
