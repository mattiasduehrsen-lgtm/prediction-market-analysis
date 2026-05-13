# Brain Research — Synthesized Findings

**Date:** 2026-05-10
**Status:** Research complete. No code changes proposed in this document.
**Source reports:**
- `BRAIN_RESEARCH_DATA.md` — empirical analysis on 721 MR-15m PAPER trades
- `BRAIN_RESEARCH_LITERATURE.md` — review of academic + industry LLM-in-trading work
- `BRAIN_RESEARCH_ARCHITECTURE.md` — design review and phasing plan

---

## Headline

**The current v1.32 brain architecture (Option A: regime classifier with continuous edge_modifier, advisory-only) is what the evidence supports.** All three research lines converge on the same conclusion. The architecture review reached it by reasoning about failure modes; the data analysis reached it by measuring the empirical signal ceiling; the literature review reached it by surveying published work.

The honest realistic ceiling for any per-trade Claude reasoner on this strategy is approximately **+$1.50 to +$2.00 EV per trade improvement on confidence segments** — meaningful but not strategy-saving. The strategy's structural loss/win asymmetry (~-$1.99 loss vs +$2.50 win, needs ~44% WR to break even) cannot be overcome by smarter trade selection alone.

The brain is worth deploying because:
1. The signal it can exploit (8-trade recency, regime context) is real, empirical, and not captured by ML.
2. The cost is rounding-error ($0.005/day).
3. It is a low-risk experiment with clear promotion/kill gates.

The brain is NOT a silver bullet because:
1. The signal ceiling is modest, not transformative.
2. The dominant profit strategies on Polymarket (market making, news arb, HFT) are not what we're running.
3. 15m crypto Up/Down markets are described in the literature as bot-vs-bot latency games — not a domain where LLM reasoning has a documented edge.

---

## What we learned (the four most important findings)

### Finding 1: Why the previous `claude_advisor.py` failed (96% skip rate)

It was not a tuning bug. The prompt invited a discretionary-trader mental model on a systematic-strategy decision. Five compounding problems:

1. **Wrong mental model invitation.** Asking "should the bot enter this trade — bet asset reverses — or skip?" reads as a discretionary call. A reasonable discretionary trader looking at "BTC moved DOWN 0.4%, momentum decelerating, cheap side still falling" says *skip* — that's textbook technical analysis ("don't catch a falling knife"). But this isn't discretionary trading; it's the 96th call of a systematic strategy whose edge has already been gated.

2. **No EV asymmetry in the prompt.** Wins pay $1, losses pay $0, entry is 0.30–0.39. Break-even win rate is ~33%, but the prompt buried this. Without the asymmetry stated, "BTC is moving against me" reads as a strict negative.

3. **Rigged language.** Five momentum labels, only one unambiguously bullish for our trade. "YES — momentum not finished" framed our setup as anti-edge. The model was told what to think before being asked what to think.

4. **Wrong delegation.** The advisor was a *second* veto on top of cheap-side + edge + liquidity gates that had already filtered for the edge. Ask an LLM to be a final-stage skeptic on a pre-gated setup and it will skeptically veto. That's the role assigned.

5. **No history across calls.** Every call was stateless. The model couldn't say "this regime is working — take this." It only saw a momentum snapshot.

**v1.32 fixes all five.** Window_brain (a) classifies regime not direction, (b) returns continuous modifier not binary gate, (c) includes 10-trade history with WR + streak, (d) anchors the model to "is mean-reversion working" not "should we enter."

But the **system prompt has a subtler version of problem #3** — the "Key failure modes" section is more vivid than "Key success signals." Worth A/B testing the prompt with sections rebalanced after observation gate passes.

### Finding 2: The signal Claude can plausibly exploit (and ML cannot)

ML's gradient-boosted classifier on 17 static features got AUC 0.496 — chance. **But ML did not have access to the strongest signal in the data**: per-asset rolling 8-trade win rate.

| Prior 8-trade WR | n | Next-trade EV | Next-trade WR |
|---:|---:|---:|---:|
| <25% | 184 | -$1.20 | 37.5% |
| 25–50% | 255 | -$1.60 | 47.5% |
| 50–75% | 220 | -$0.84 | 54.1% |
| **>75%** | **38** | **+$1.71** | **68.4%** |

Monotone gradient. ETH-specific is sharper: ETH UP with prior WR >75% gives **EV +$2.40 on n=28**.

Claude reading the 10-trade history block sees this for free — it doesn't need us to pre-compute the WR. But the data analysis specifically recommends adding **`recent_wr` and `recent_ev` as pre-computed summary lines in the user prompt** because models use pre-computed signals more reliably than ones they have to derive.

**Why ML missed this and Claude won't:** ML treated each trade as IID with 17 fixed features. The recency signal requires looking at sequence, which is what an LLM consuming a history list does natively.

### Finding 3: Regime persistence is short, not long

- **80-trade chunk EV autocorrelation: -0.03** (zero). Long regimes do NOT persist.
- **8-trade recency autocorrelation: +0.158** (small but real). Short regimes DO persist.

This validates the brain's BRAIN_HISTORY_LEN=10 default. If we'd set it to 80 we'd be looking at noise. If we'd set it to 3 we'd lose signal. The 10-trade window is correctly tuned.

**Implication for promotion**: the brain's regime call should be valid for ≤6 hours of fresh entries. Don't try to extrapolate brain advice across regime breaks. Don't try to predict tomorrow's regime from today's history.

### Finding 4: Upper bound is meaningful but modest

A *perfect* oracle that knew `|btc_pct_change_at_entry|` was in the bottom quartile would lift EV from **-$1.00 to +$0.45 per trade** — a gap of $1.92.

That is the realistic ceiling on what regime classification can deliver. **A brain achieving 70% of perfect-oracle performance** (generous; it's working from prose, not numeric thresholds) would claw back **~$1.30/trade**.

At PAPER scale (100 trades/week): ~$130/week of EV improvement.
At LIVE size $5 on SOL-UP only: ~$10/week.

This is **meaningful but does not save the strategy.** A perfect brain still cannot overcome the TP/SL asymmetry baked into the underlying trade. The strategy needs +$0.99/trade improvement to break even from its corrected -$0.99 baseline; brain ceiling is in that neighborhood but the realized improvement will be less.

---

## What the literature says (the three sharpest claims)

1. **"LLMs optimize for instruction-following, not profit"** (arXiv:2504.10789). They execute prompted strategies faithfully but do not generate alpha on their own. Strategy quality is upstream of LLM quality. Implication: the brain cannot rescue a structurally edgeless strategy.

2. **Polymarket's documented profitable strategies are not ours.** Market making, news arbitrage, correlation arbitrage, and HFT momentum are what works. 5/15m crypto Up/Down markets are described as "bot-vs-bot latency games" against Chainlink oracle ticks. ~$40M was extracted Apr 2024–Apr 2025 by sub-100ms execution bots. We are not in that game.

3. **Conservatism bias is the dominant LLM trading failure mode** (arXiv:2505.07078). LLM strategies systematically under-trade in bull markets and suffer in bear markets. This is exactly the pattern that killed `claude_advisor.py`. The new brain mitigates by using continuous output, but the bias risk persists in the prompt's framing.

The closest published architecture to ours (PolySwarm, arXiv:2604.03888) uses 50-persona LLM swarm + Bayesian aggregation + quarter-Kelly. It reports calibration gains but **no realized PnL** and explicitly lists hallucination + correlated agent errors + frontier-model cost as failure modes.

**Recommendation from literature:** numeric filter + LLM critic on borderline candidates (Hybrid pattern). The brain in v1.32 is essentially this pattern.

---

## Phasing plan (consolidated from architecture review)

| Version | Status | What it does | Promotion gate to next |
|---|---|---|---|
| **v1.32** | Deployed 2026-05-10 | Brain in pure observation. Logs advice; bot ignores. | **≥80 brain-evaluated resolved trades; `mr_edge="strong"` mean pnl ≥ `mr_edge="degraded"` mean pnl + 1 SE.** |
| **v1.33** | Proposed (conditional) | Activate `edge_modifier`. Add `confidence` field. Run 50/50 A/B (deterministic on `hash(window_start, asset) % 2`). Add 200/hr call rate limiter. | ≥200 A/B trades; A-arm mean pnl ≥ B-arm + $0.30/trade; A-arm WR ≥ B-arm WR. |
| **v1.34** | Proposed (conditional) | Add `size_scalar ∈ [0.5, 1.0]`. Remove A/B; brain is authoritative on modifier. | ≥150 trades with size_scalar; size-weighted EV ≥ flat-size EV + $0.20/trade; brain stable 30 days. |
| **v1.35** | Speculative | Brain orchestrates 4h entries only (where call volume is low, per-trade reasoning has highest payoff). Possibly richer schema with TP/SL hints (clamped). | Depends on 4h experiment outcome. |

### Critical operational rules

- **Brain never blocks entries.** Modifier is additive on edge gate only. `size_scalar` is multiplicative on position size, floor at 0.5. No `SKIP` field. No `TP_override`. Ever.
- **Clamp-and-accept on bad output.** Malformed JSON → NEUTRAL. Out-of-range field → clamp. Missing field → default. Reject-and-skip would let a single Anthropic-side change halt all trading.
- **Hard timeout 6s.** Hard rate limit 200 calls/hour. Circuit-break on 5 errors in 60s.
- **Prompt versioning.** Every call logged with `(prompt_hash, model_id, anthropic_version)`. Daily replay against current model — alert if decision delta >X%. Provider model drift is documented and will silently move PnL otherwise.
- **Rewrite prompt at most twice.** If three different prompts all fail the v1.32 gate, kill the brain. This codebase has a documented pattern of layering complexity on dead strategies; resist it.

---

## Sharpened decisions for v1.32 observation phase

Without making code changes now, these are the things to monitor while v1.32 runs:

### Metrics to log (already in v1.32)

- `regime` distribution (target: roughly balanced across ranging/trending/volatile/unclear; if 80% "trending" the prompt has bearish bias)
- `mr_edge` distribution (target: similar — if 80% "degraded" the prompt has bearish bias)
- `edge_modifier` mean (target: near 0; if substantially > 0 the prompt is biased toward "stricter")
- `is_neutral` rate (cache invalidations + errors; baseline ~5%, alert >40%)
- Cache hit rate (`resp.usage.cache_read_input_tokens`; target ≥80%)

### Three specific things to look for during observation

1. **Bearish asymmetry in the modifier.** If after 30 calls the mean modifier is significantly positive (stricter gate), the prompt is recapitulating the `claude_advisor` bias. Fix is to rebalance the GOOD/BAD reasoning section in the system prompt — currently failure modes are more vivid than success signals.

2. **Recency signal use.** Manually inspect 10 brain reasoning strings. Does the model reference the trade history? Does it use phrases like "recent WR" or "streak" in its reasoning? If not, add `recent_wr_8` and `recent_ev_8` as pre-computed summary lines in the user prompt.

3. **Per-asset variance.** Brain advice should differ by asset (SOL's regime ≠ BTC's regime). If brain advice converges across assets, it's not actually conditioning on the asset-specific history — investigate sync_from_csv.

### What we won't decide until observation gate

- Whether to promote to v1.33 (need n=80)
- Whether to enable size_scalar (v1.34 territory)
- Whether to fork brain instances per (asset, window) — currently shared by window only

### What we should NOT do during observation

- Add brain to LIVE entry path (LIVE still paused; v1.32 is PAPER-only by virtue of the pause flag plus LIVE config being SOL-15m-only)
- Modify the brain prompt iteratively. Let one prompt run for the full observation window. We learn nothing from a moving target.
- Add brain to exit decisions. That's Option B territory which we rejected.

---

## What "thinks on every trade" actually means

The user's strategic reframe: *"I think it requires a strategy that is able to think on every trade instead of just placing based on different markets hitting or missing."*

The architecture review's load-bearing argument: **per-trade *thinking* is satisfied by per-trade *contextual reasoning*; it does not require per-trade *binary authority*.**

v1.32 satisfies the spirit:
- Brain IS called per trade
- Brain DOES reason about the specific setup using fresh context
- Brain DOES produce per-trade output (regime + modifier + reasoning)

What v1.32 does NOT do:
- Make the entry decision (that's still the bot's heuristics)
- Predict direction (that's Option B; the ML null says this is impossible)
- Hard-block trades (that's the failure mode of the old advisor)

If after v1.33 the user still feels the brain "doesn't think enough," that's the moment to revisit Option B — not before. Until then, treat the user's phrase as motivation, not specification.

---

## Honest assessment

### What we know with high confidence
- Previous binary advisor failure is structural and well-understood.
- Regime classifier shape is the right architecture.
- Cost is solved.
- The brain CAN match the perfect-oracle regime classifier ceiling.

### What we know with medium confidence
- Brain will produce **some** EV uplift (recency signal is real, +$1.50 magnitude is plausible).
- ETH-with-high-recent-WR (currently disabled on LIVE) might become re-enableable conditionally.

### What we know with low confidence
- Whether the v1.32 prompt as written has bearish asymmetry. Will know in ~14 days.
- Whether the brain's regime calls will be reliable at n=80. The architecture review says yes; the data says signal exists; reality may differ.

### What we don't know
- Whether Claude on Polymarket data has a meaningful edge that survives prompt drift over weeks.
- Whether 4h markets behave like 15m markets w.r.t. regime structure.

### What this research changes about plans
- Validates v1.32 deployment (the architecture is right).
- Sharpens v1.33 promotion criteria (n=80, mr_edge separation ≥ 1 SE).
- Adds operational hardening that wasn't in v1.32 (rate limiter, replay log, prompt version tracking).
- Surfaces ETH-recency segment as a high-value future re-enablement candidate.
- Codifies the anti-pattern: rewrite prompt at most twice, then kill.

### What this research does NOT change
- Strategy fundamentals: still -EV overall under honest accounting.
- LIVE remains paused.
- 4h experiment (v1.31) still running in parallel.
- SOL-only LIVE config (v1.29) still right.

---

## Recommended next move

**No code changes for ~14 days.** Let v1.32 collect 80+ brain-evaluated trades on PAPER. While it runs:

1. **Operational hardening (low-risk, anytime):** Add rate limiter + prompt version logging. ~30 LoC. Defensive only; doesn't alter brain behavior.

2. **Observation analysis (~ day 7 and day 14):** Pull `brain_log.csv`, check the three things to look for. Decide if prompt needs rebalancing.

3. **v1.33 design freeze (day 12):** Write the v1.33 spec — A/B harness, confidence field, exact promotion criteria. Don't deploy until gate passes.

4. **Strategy review parallel (day 7):** Check 4h experiment (v1.31) data. If 4h shows signal or null, that affects v1.33 prompt scope. If 4h is null, brain becomes 15m-only.

The biggest risk in this plan is **moving too fast**. v1.33 deployed before n=80 is the same mistake as v1.0 claude_advisor — declaring victory on insufficient evidence. The architecture review's emphasis on sample sizes per gate is the most important operational rule to follow.

---

## Documents to reference

- `BRAIN_RESEARCH_DATA.md` (data analysis, signal ceiling, prior advisor postmortem)
- `BRAIN_RESEARCH_LITERATURE.md` (academic + industry survey, citations, cost benchmarks)
- `BRAIN_RESEARCH_ARCHITECTURE.md` (Q1-Q7 design review, concrete prompt + schema)
- `src/bot/window_brain.py` (current implementation, v1.32)
- `PATCH_HISTORY.md` v1.32 entry (what's deployed)
