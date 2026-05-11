# BRAIN_RESEARCH_LITERATURE.md

Research compiled 2026-05-10. Focus: how LLMs (Claude, GPT-4, others) are deployed inside live trading systems, especially Polymarket / Kalshi / short-horizon binary outcome markets. Goal: inform the design of a per-trade Claude reasoner for our 15m / 4h Up/Down mean-reversion bot.

## TL;DR

- **LLMs in trading are almost never the predictor.** Across academic frameworks (TradingAgents, ATLAS, PolySwarm) and production bots, the dominant pattern is LLM-as-information-processor or LLM-as-critic, with a systematic/numeric layer doing actual entry decisions. The paper "Can Large Language Models Trade?" (arXiv:2504.10789) found LLMs **optimize for instruction-following, not profit** — they execute prompted strategies faithfully but do not generate alpha on their own.
- **The two documented failure modes most relevant to our bot are (a) conservatism bias** — LLMs under-trade in bull markets, over-react in bear markets (arXiv:2505.07078) — and (b) **prompt/version drift** where silent provider model updates degrade behavior even with no code change. Both argue for a fast numeric filter plus LLM only on borderline candidates, with versioned prompts and offline replay.
- **For 15m Up/Down Polymarket markets specifically**, public writeups converge on: (1) automated market making and (2) HFT latency arbitrage as the only consistently profitable strategies; mean reversion works "until it doesn't" with catastrophic tail risk during liquidation cascades. LLMs are described as **information-processing acceleration, not predictive engines** — useful for news/regime classification, not for price-direction prediction on 15m horizons.
- **PolySwarm (arXiv:2604.03888)** is the closest published architecture to our use case: 50-persona LLM swarm on Polymarket binaries, Bayesian confidence-weighted aggregation, quarter-Kelly sizing. The paper reports calibration improvements vs. single-model baselines but **no realized PnL number** — and explicitly lists hallucination, correlated agent errors, and frontier-model cost ($1000s/day) as failure modes.
- **Cost is solved.** Claude Haiku 4.5 ($1/M in, $5/M out) plus 5-min ephemeral prompt caching (0.10x input cost on reads, 1.25x on writes) means a cached ~2 KB system prompt + small per-call diff runs at ~$0.001-0.003/decision. Even at 50 candidates/day this is rounding error. The cost case for LLM-in-the-loop has been won; the open question is whether it produces positive EV after the conservatism penalty.

---

## 1. Real-world examples

| Project | Type | LLM role | Stack | Source |
|---|---|---|---|---|
| **PolySwarm** (academic) | Binary prediction markets on Polymarket | 50-persona LLM swarm produces probability estimates; Bayesian aggregation with market prior (0.70 p_swarm + 0.30 p_market); quarter-Kelly sizing | Claude / GPT / Ollama, FastAPI, 5s scan cycle | [arXiv:2604.03888](https://arxiv.org/html/2604.03888v1) |
| **Polymarket/agents** (Polymarket official, open source) | General Polymarket trading agent | Underspecified — Langchain + Chroma vector DB + OpenAI; "context-aware reasoning"; LLM role is more research/RAG than decision | OpenAI, Chroma, Gamma+CLOB APIs | [github.com/Polymarket/agents](https://github.com/Polymarket/agents/) |
| **TradingAgents** (Tauric Research, 2024) | Equities multi-agent | Specialized agents (Fundamentals/Sentiment/News/Technical) + Bull/Bear debate + Trader + Risk Manager + Fund Manager critic | Multi-LLM, structured-output + NL-debate hybrid | [arXiv:2412.20138](https://arxiv.org/html/2412.20138v1) |
| **ATLAS** (2025) | Adaptive multi-asset trading | Central trading agent with order-aware action space; Adaptive-OPRO dynamically rewrites the prompt from real-time feedback | Multi-LLM | [arXiv:2510.15949](https://arxiv.org/html/2510.15949v1) |
| **FinGPT** | LLM family | Domain fine-tune of LLaMA/ChatGLM on ~50K finance samples via LoRA. Used as building block, not as bot. | LLaMA/ChatGLM + LoRA | [huggingface.co/FinGPT](https://huggingface.co/FinGPT) |
| **Trading-R1** (2025) | Financial trading | LLM reasoning trained via RL on trading rewards | — | [arXiv:2509.11420](https://arxiv.org/pdf/2509.11420) |
| **CloddsBot** (open source, Claude-based) | Multi-market autonomous agent across Polymarket, Kalshi, Binance, Hyperliquid, Solana DEXs | Full agent: scans, executes, risk-manages. Built on Claude. | Claude, multi-chain | [github.com/alsk1992/CloddsBot](https://github.com/alsk1992/CloddsBot) |
| **aulekator BTC-15m bot** | Polymarket BTC 15m (exact match for our window) | 7-phase architecture, multi-signal, "self-learning"; LLM role not explicit in description | NautilusTrader | [github.com/aulekator/Polymarket-BTC-15-Minute-Trading-Bot](https://github.com/aulekator/Polymarket-BTC-15-Minute-Trading-Bot) |
| **Alphascope** (Bokarev) | Polymarket/Kalshi research assistant | LLM = research/probability estimation tool; CoT exposed to user; no autonomous trading | Multi-LLM | [bokarevs.medium.com](https://bokarevs.medium.com/i-built-an-llm-tool-that-beats-human-intuition-on-polymarket-c60f1667b8af) |
| **"Two-layer AI" Njuguna writeup** | Polymarket + Kalshi | Tier-1 frontier LLM (GPT-4/Claude Opus) = "brain" for research; Tier-2 cheap/local LLM = "hands" for execution | — | [blog.devgenius.io](https://blog.devgenius.io/just-built-a-two-layer-ai-system-that-trades-polymarket-and-kalshi-while-i-sleep-heres-the-aa59ead275f6) |
| **Media-reported "Claude bot $313 -> $414K"** | Polymarket 15m BTC/ETH/SOL Up/Down with 98% win rate | Marketing claims; unverified | — | [medium / weare1010](https://medium.com/@weare1010/claude-ai-trading-bots-are-making-hundreds-of-thousands-on-polymarket-2840efb9f2cd) |

Notes on credibility:

- PolySwarm and TradingAgents are peer-reviewed-style with explicit aggregation methodology but **neither reports realized PnL on out-of-sample live trading** — only calibration / sim metrics.
- The "98% win rate / $313 -> $414K" type writeups are marketing/clickbait and consistent with selection bias from millions of YOLO bots.
- The most credible piece of population-level evidence is that **~37% of AI agents on Polymarket report positive P&L** vs. 7-13% for humans, but **arbitrage bots extracted ~$40M April 2024-April 2025 by speed, not predictive accuracy** (paper "Unravelling the Probabilistic Forest", Aug 2025, via [Finance Magnates](https://www.financemagnates.com/trending/prediction-markets-are-turning-into-a-bot-playground/)).

---

## 2. Architecture patterns

### 2.1 Classifier (fixed label)
LLM is called with structured context and emits a fixed label (e.g. `{regime: "trend"|"reversion"|"chop"}`). Cheap, fast, easy to evaluate.
- Pro: low latency, easy to A/B, easy to cache.
- Con: no reasoning, no graceful fallback when prompt is ambiguous.

### 2.2 Reasoner (CoT + structured decision)
LLM does chain-of-thought, then emits JSON. PolySwarm uses this per-persona. Most "borderline filter" use cases live here.
- Pro: catches obvious failures the numeric system misses (e.g. news shock, weekend regime).
- Con: cost ~2-5x classifier; CoT can be inconsistent run-to-run.

### 2.3 Agent (tools, multi-step)
LLM has tools, plans, executes. CloddsBot, Polymarket/agents.
- Pro: handles unstructured tasks.
- Con: **latency unbounded**, drift-prone, hard to test. Wrong for 15m markets where decision needs to happen in seconds.

### 2.4 Critic (reviews existing decisions)
LLM doesn't decide; it reviews what the numeric system wants to do and can veto / flag. TradingAgents' Fund Manager + Bull/Bear debate is this pattern.
- Pro: numeric system stays in charge; LLM adds disaster-avoidance.
- Con: vetoes may correlate with model bias (e.g. always vetoes LONG in red days = conservatism bias).

### 2.5 Hybrid (fast filter + LLM for borderline)
Numeric edge score filters; LLM only fires on borderline (e.g. edge in mid-tier) or on regime changes.
- Pro: bounds cost and latency; LLM only does the work where it can plausibly help.
- Con: needs explicit "borderline" definition; risk that the gate itself is what's miscalibrated.

### Fit-to-our-case

Our setup: BTC/ETH/SOL 15m Polymarket Up/Down, mean reversion, 5-50 candidates/day. Decisions must fire within seconds. Position size is $5. PAPER is unconstrained, LIVE has a daily-loss cap.

- **Agent (2.3) is wrong.** Latency and unbounded reasoning don't match a 15m window.
- **Pure Reasoner-as-predictor (2.2)** is risky: the paper [arXiv:2504.10789](https://arxiv.org/html/2504.10789v1) shows LLMs follow instructions but do not optimize for profit. We would be paying for what is effectively a stochastic rewrite of our existing systematic rule.
- **Best fit is Hybrid (2.5) using LLM as Critic (2.4) on borderline candidates.** Numeric layer (current `should_enter`) does the cheap filtering. LLM only sees the 10-30% of candidates that sit in the borderline EV band, plus a regime-tag refresh (every 15 min or every N candidates). LLM output is structured JSON: `{decision: "approve"|"skip"|"size_down", reason: "...", confidence: 0..1}`. Logged for offline replay. This pattern is closest to what TradingAgents' Risk Manager + Fund Manager actually do.

---

## 3. Failure modes (with citations)

| Failure mode | Description | Source |
|---|---|---|
| **Conservatism bias** | LLM strategies underperform in bull markets due to excessive conservatism; suffer disproportionate losses in bear markets due to inadequate risk control. | [arXiv:2505.07078](https://arxiv.org/html/2505.07078v2) |
| **Hallucinated facts** | LLMs invent plausible prices, dates, and trends when context is missing. | [arXiv:2311.15548](https://arxiv.org/abs/2311.15548), [BizTech](https://biztechmagazine.com/article/2025/08/llm-hallucinations-what-are-implications-financial-institutions) |
| **Structural investment biases** | Models systematically prefer tech, large-cap, contrarian. Escalates into confirmation bias on follow-up turns. | [arXiv:2507.20957](https://arxiv.org/html/2507.20957v4) |
| **Instruction-following over profit-seeking** | LLMs faithfully execute the prompted strategy whether or not it makes money. Strategy quality is upstream of LLM quality. | [arXiv:2504.10789](https://arxiv.org/html/2504.10789v1) |
| **Behavioral drift in long-running agents** | Decision patterns deviate from spec over time even with no code change. Mitigations: episodic-memory consolidation, drift-aware routing, adaptive behavioral anchoring. | [arXiv:2601.04170](https://arxiv.org/html/2601.04170) |
| **Silent provider model updates** | Anthropic/OpenAI ship updated weights/decoding that move outputs without API version change. | [byaiteam.com](https://byaiteam.com/blog/2025/12/30/llm-model-drift-detect-prevent-and-mitigate-failures/) |
| **Correlated errors across personas** | In multi-agent setups (PolySwarm), agents share training data so "diversity" is partly illusory. | [arXiv:2604.03888](https://arxiv.org/html/2604.03888v1) |
| **Cost/latency blowup** | Frontier-model multi-agent runs reported at $1000s/day. Mitigation: caching + tiered (cheap/expensive) model use. | [arXiv:2604.03888](https://arxiv.org/html/2604.03888v1) |
| **Mean-reversion tail risk** (not LLM-specific but relevant) | Buying dips during liquidation cascades — e.g. $180M March 2024 BTC liquidation — wipes out months of edge. | [Kalena blog](https://blog.kalena.ai/crypto-algo-trading-reddit-the-order-flow-audit-stress-testing-the-7-most-upvoted-algorithmic-strategies-against-real-market-microstructure) |
| **Adversarial dynamics in prediction markets** | Arbitrage windows have collapsed from 12.3s (2024) to 2.7s (2025); 73% of arbitrage profit goes to sub-100ms bots. | [QuantVPS](https://www.quantvps.com/blog/polymarket-hft-traders-use-ai-arbitrage-mispricing) |

**Most relevant to our bot:** conservatism bias and prompt-version drift. The bot currently runs at $5/trade in LIVE — conservatism that suppresses 20% of valid entries is more expensive than the LLM call itself. Drift between Haiku versions is the recurring infrastructure tax.

---

## 4. Prompt engineering best practices for trading

From the structured-output and financial-LLM literature:

1. **Tool calling / structured output > prompt-engineered JSON.** Anthropic and OpenAI both support strict JSON-schema tool calling; this gives ~99% schema adherence vs. ~80-90% for "respond in JSON format" prompts. ([agenta.ai guide](https://agenta.ai/blog/the-guide-to-structured-outputs-and-function-calling-with-llms), [PromptLayer](https://blog.promptlayer.com/how-json-schema-works-for-structured-outputs-and-tool-integration/))
2. **Zero-shot beats few-shot for time-series in most studies.** Adding examples can encourage the model to ape demonstration trends and produces unstable rationales. Zero-shot with strong structural priors in the prompt is the default recommendation. ([ACL 2025 short](https://aclanthology.org/2025.acl-short.71.pdf), [Gruver et al.](https://arxiv.org/pdf/2310.07820))
3. **Role + Context + Task + Constraints structure.** Standard prompting guideline. For trading: explicit risk caps and skip-bias warnings inside the prompt help counter conservatism. ([learnwithparam](https://www.learnwithparam.com/blog/prompt-engineering-structured-json-output))
4. **Encode time-series as compact numeric blocks**, not prose. LLMTIME-style numeric encoding gives better calibration than English sentences. ([Gruver et al.](https://arxiv.org/pdf/2310.07820))
5. **Anchor to the systematic strategy.** Adaptive Behavioral Anchoring (ABA) from the drift literature: few-shot exemplars from a known-good baseline period, replayed with each call, keep the agent from wandering. ([arXiv:2601.04170](https://arxiv.org/html/2601.04170))
6. **Prompt caching with `cache_control: {type: "ephemeral"}`**. Anchor the static system prompt + tool definitions + baseline exemplars in a cached prefix; only the per-call market state is dynamic. 5-minute TTL fits Polymarket 15m markets nicely (next call always within window). ([Anthropic docs](https://platform.claude.com/docs/en/build-with-claude/prompt-caching))
7. **Validate output deterministically before acting.** Pydantic schema, range checks, decision-whitelist. Cited as standard practice in [TradingAgents](https://arxiv.org/html/2412.20138v3) hybrid output design.
8. **Replay infrastructure.** Log every (input, output) pair; replay on new model versions to catch drift before going live. (Generic best practice; called out in ATLAS and the drift survey.)

---

## 5. Polymarket-specific intelligence

From writeups, papers, and aggregator coverage:

- **Strategies actually documented as profitable** (Medium, 2026 retrospective):
  1. Automated market making (78-85% win rate, 1-3%/month)
  2. AI-powered probability arbitrage on news (65-75%, 3-8%/month)
  3. Correlation / logical arbitrage between related markets (70-80%, 2-5%/month)
  4. HFT momentum on news + orderbook (60-70%, 8-15%/month)
  Source: [Beyond Simple Arbitrage](https://medium.com/illumination/beyond-simple-arbitrage-4-polymarket-strategies-bots-actually-profit-from-in-2026-ddacc92c5b4f). Note: **none of these is "15m mean reversion on BTC/ETH/SOL"** — the strategies that are reported to work systematically are market-making, arb, and news-momentum. The 5/15m crypto Up/Down markets are described as **bot-vs-bot latency games against Chainlink oracle ticks**.
- **Arbitrage extraction**: ~$40M extracted April 2024-April 2025 by sub-100ms execution bots. Arb windows are 2.7s avg (2025) vs. 12.3s (2024). ([QuantVPS](https://www.quantvps.com/blog/polymarket-hft-traders-use-ai-arbitrage-mispricing), [Finance Magnates](https://www.financemagnates.com/trending/prediction-markets-are-turning-into-a-bot-playground/))
- **AI agents reportedly outperform humans by population**: 37% of agents have positive PnL vs. 7-13% of humans. ([NYC Servers blog](https://newyorkcityservers.com/blog/ai-agents-prediction-market-trading))
- **Mean reversion warning**: explicitly called out in algo-trading reviews — works in normal conditions, blows up on liquidation cascades. Buying 35-65c tokens with bid-side imbalance + hard 3% stop is the documented recipe. ([Kalena](https://blog.kalena.ai/crypto-algo-trading-reddit-the-order-flow-audit-stress-testing-the-7-most-upvoted-algorithmic-strategies-against-real-market-microstructure))
- **Best entry windows for 15m markets**: US open (9:30 ET), major news, low-liquidity 3-6 AM ET (wider spreads), and immediately after pumps/dumps where reversion is most likely.
- **Liquidity is the binding constraint** at small sizes — minimum order requirements eat flexibility. Relevant since we're at $5/trade.
- **No public LLM bot specifically targeting BTC/ETH/SOL 15m mean reversion** was found beyond marketing claims. The closest is aulekator's NautilusTrader-based 15m BTC bot, which does not appear to use an LLM in the decision path.

---

## 6. Cost / latency benchmarks

Claude Haiku 4.5 (model line that most plausibly serves our use case):

- **Price**: $1/M input, $5/M output. ([Anthropic](https://www.anthropic.com/claude/haiku), [Caylent](https://caylent.com/blog/claude-haiku-4-5-deep-dive-cost-capabilities-and-the-multi-agent-opportunity))
- **Latency (TTFT)**: Anthropic direct ~0.70s; Vertex ~0.59s; Bedrock ~0.98s. End-to-end for a small structured-output response: typically 1-2s. ([Artificial Analysis](https://artificialanalysis.ai/models/claude-4-5-haiku/providers))
- **Speed vs. Sonnet 4.5**: 4-5x faster on like-for-like; SWE-bench 73.3% vs. 77.2%. Strong enough for classifier/critic roles.

Prompt caching:

- **Cache write**: 1.25x input (5-min TTL) or 2.0x (1-hour TTL).
- **Cache read**: 0.10x input — **90% discount**.
- **Realized savings**: 30-50% input-cost reduction on RAG-style workloads; 70-90% on heavily-cached systems. One blog reports $720 -> $72/mo. ([Anthropic docs](https://platform.claude.com/docs/en/build-with-claude/prompt-caching), [Du'An Lightfoot](https://www.duanlightfoot.com/posts/prompt-caching-is-a-must-how-i-went-from-spending-720-to-72-monthly-on-api-costs/))
- **For our bot**: a ~2 KB cached system prompt + ~500 token per-call market state + ~200 token JSON response = ~$0.001-0.003 per decision after caching. At 50 candidates/day = ~$0.05-0.15/day. Negligible vs. $5 position size.

Latency budget for 15m markets: we have 14 minutes to enter. LLM call at 1-2s is fine. The constraint is that LLM call must not block other entries — async fire-and-wait pattern in the existing loop.

---

## 7. Recommendations

Three architectural patterns most likely to work for our case, in priority order:

### Recommendation A — Hybrid: numeric filter + Haiku critic on borderline candidates (PREFERRED)

- Existing numeric `should_enter()` is the gate. Unchanged for clear-edge candidates.
- For candidates in a defined "borderline" EV band (e.g., edge between 1.5% and 4%), call Haiku 4.5 with:
  - Static cached prefix: role, strategy description, baseline exemplars (ABA-style), tool/JSON schema.
  - Dynamic suffix: current candle window, recent price path, current Polymarket bid/ask, edge score, recent trade outcomes (last 5-10).
  - Tool-call output: `{decision: "approve"|"skip"|"size_down_to_2_50", reason_code: <enum>, free_text: <=200 chars, confidence: 0..1}`.
- Log every call to a JSONL file for offline replay.
- Veto-only mode for first ~2 weeks: LLM can `skip` or `size_down`, never invent an entry. Measures whether the LLM adds or subtracts edge before giving it more authority.
- **Why this fits**: bounds cost, latency, and blast radius; preserves the systematic core (which is what arXiv:2504.10789 says LLMs need); makes drift detection straightforward via replay.

### Recommendation B — Regime classifier (cheaper but coarser)

- Call Haiku once every N minutes (e.g. 15) with recent BTC/ETH/SOL state.
- Output: `{regime: "trend_up"|"trend_down"|"reversion"|"chop"|"news_shock", confidence: 0..1, halt_trading: bool}`.
- Numeric layer reads regime tag and adjusts thresholds (mean-reversion strategies suppress under `trend_*` or `news_shock`).
- **Pro**: very cheap (~$0.001/call x 96/day = $0.10/day), simple to validate.
- **Con**: doesn't address per-trade conservatism/edge questions; can be too coarse.

### Recommendation C — News/event guard (narrowest, safest first step)

- Periodic Haiku call with the last N minutes of crypto news headlines (RSS / API).
- Output: `{has_material_event: bool, asset_affected: [...], halt_minutes: int, reason: str}`.
- If `has_material_event`, set a temporary halt on affected assets. This directly addresses the documented mean-reversion failure mode (liquidation cascades, oracle-driven dislocations).
- **Pro**: minimum surface area, easy to attribute PnL impact, addresses the worst tail risk.
- **Con**: doesn't change baseline edge.

### What NOT to do

- **Do not use an LLM as the primary direction predictor on 15m price-action.** No paper or credible writeup supports this on sub-hour horizons. Conservatism bias plus the LLMs-don't-optimize-profit result both argue against it.
- **Do not deploy a full agent loop (tools + multi-step) in the entry path.** Latency unbounded; one stuck tool call burns a trade window.
- **Do not roll your own JSON-from-prose parsing.** Use Anthropic tool calling with a strict schema.
- **Do not skip the replay log.** Provider model drift is documented and will move PnL silently otherwise.

### Operational guardrails (apply to any of A/B/C)

- Version every prompt with a hash; record `(prompt_hash, model_id, anthropic_version)` on every call.
- Daily replay of the previous day's prompts against the current model — alert if decision delta > X%.
- Hard timeout on LLM call (e.g. 4s); on timeout, fall back to numeric-only decision.
- Shadow-mode first: run LLM critic on PAPER with full logging for >=2 weeks before letting it touch LIVE.
- Keep `paper_with_llm` and `paper_without_llm` running in parallel so the lift is measurable, not assumed.

---

## Sources

Key URLs (already linked inline above):

- [PolySwarm (arXiv:2604.03888)](https://arxiv.org/html/2604.03888v1)
- [TradingAgents (arXiv:2412.20138)](https://arxiv.org/html/2412.20138v1)
- [Can LLMs Trade? (arXiv:2504.10789)](https://arxiv.org/html/2504.10789v1)
- [LLM Investing Long Run (arXiv:2505.07078)](https://arxiv.org/html/2505.07078v2)
- [LLM Investment Bias (arXiv:2507.20957)](https://arxiv.org/html/2507.20957v4)
- [LLM Finance Hallucination (arXiv:2311.15548)](https://arxiv.org/abs/2311.15548)
- [Agent Drift (arXiv:2601.04170)](https://arxiv.org/html/2601.04170)
- [ATLAS (arXiv:2510.15949)](https://arxiv.org/html/2510.15949v1)
- [Trading-R1 (arXiv:2509.11420)](https://arxiv.org/pdf/2509.11420)
- [Polymarket/agents GitHub](https://github.com/Polymarket/agents/)
- [CloddsBot GitHub](https://github.com/alsk1992/CloddsBot)
- [aulekator BTC-15m bot](https://github.com/aulekator/Polymarket-BTC-15-Minute-Trading-Bot)
- [Anthropic prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [Claude Haiku 4.5](https://www.anthropic.com/claude/haiku)
- [Artificial Analysis - Haiku 4.5 providers](https://artificialanalysis.ai/models/claude-4-5-haiku/providers)
- [Beyond Simple Arbitrage (Polymarket)](https://medium.com/illumination/beyond-simple-arbitrage-4-polymarket-strategies-bots-actually-profit-from-in-2026-ddacc92c5b4f)
- [QuantVPS - Polymarket HFT](https://www.quantvps.com/blog/polymarket-hft-traders-use-ai-arbitrage-mispricing)
- [Finance Magnates - Bot Playground](https://www.financemagnates.com/trending/prediction-markets-are-turning-into-a-bot-playground/)
- [Kalena - crypto algo strategies stress test](https://blog.kalena.ai/crypto-algo-trading-reddit-the-order-flow-audit-stress-testing-the-7-most-upvoted-algorithmic-strategies-against-real-market-microstructure)
- [Du'An Lightfoot - prompt caching cost case study](https://www.duanlightfoot.com/posts/prompt-caching-is-a-must-how-i-went-from-spending-720-to-72-monthly-on-api-costs/)
- [Alphascope (Bokarev)](https://bokarevs.medium.com/i-built-an-llm-tool-that-beats-human-intuition-on-polymarket-c60f1667b8af)
- [Njuguna two-layer AI](https://blog.devgenius.io/just-built-a-two-layer-ai-system-that-trades-polymarket-and-kalshi-while-i-sleep-heres-the-aa59ead275f6)
- [LLMTIME zero-shot forecasting (arXiv:2310.07820)](https://arxiv.org/pdf/2310.07820)
- [Revisiting LLMs as Zero-Shot Forecasters (ACL 2025)](https://aclanthology.org/2025.acl-short.71.pdf)
