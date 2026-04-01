"""Claude-powered trade advisor.

Reads closed_trades.csv + performance_breakdown.json, sends a structured analysis
request to claude-opus-4-6 with adaptive thinking, and prints actionable .env
parameter suggestions with rationale.

Usage:
    .venv/Scripts/python.exe -u main.py advise
    .venv/Scripts/python.exe -u main.py advise --dry-run   # print prompt only
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


OUTPUT_DIR = Path("output/paper_trading/polymarket")


def _load_closed_trades() -> list[dict]:
    path = OUTPUT_DIR / "closed_trades.csv"
    if not path.exists():
        return []
    import csv
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_performance_breakdown() -> dict:
    path = OUTPUT_DIR / "performance_breakdown.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_summary() -> dict:
    path = OUTPUT_DIR / "summary.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _build_prompt(trades: list[dict], breakdown: dict, summary: dict) -> str:
    trade_count = len(trades)

    # Aggregate by exit reason
    by_exit: dict[str, dict] = {}
    for t in trades:
        reason = t.get("exit_reason", "unknown")
        if reason not in by_exit:
            by_exit[reason] = {"count": 0, "pnl": 0.0, "returns": []}
        by_exit[reason]["count"] += 1
        by_exit[reason]["pnl"] += float(t.get("realized_pnl", 0) or 0)
        ret = t.get("return_pct")
        if ret is not None:
            try:
                by_exit[reason]["returns"].append(float(ret))
            except (ValueError, TypeError):
                pass

    exit_summary_lines = []
    for reason, stats in sorted(by_exit.items()):
        rets = stats["returns"]
        avg_ret = sum(rets) / len(rets) if rets else 0.0
        exit_summary_lines.append(
            f"  {reason}: {stats['count']} trades, total_pnl=${stats['pnl']:.2f}, avg_return={avg_ret:.1%}"
        )

    # Aggregate by edge tier
    edge_tiers: dict[str, dict] = {}
    for t in trades:
        try:
            edge = float(t.get("edge") or t.get("edge_ratio") or 0)
        except (ValueError, TypeError):
            edge = 0.0
        # Extract edge from entry_reason string if available
        entry_reason = t.get("entry_reason", "")
        if "edge=" in entry_reason:
            try:
                edge_str = entry_reason.split("edge=")[1].split(",")[0]
                edge = float(edge_str)
            except (IndexError, ValueError):
                pass

        if edge >= 0.015:
            tier = "high (>=1.5%)"
        elif edge >= 0.010:
            tier = "medium (1.0-1.5%)"
        elif edge >= 0.005:
            tier = "low (0.5-1.0%)"
        else:
            tier = "minimal (<0.5%)"

        if tier not in edge_tiers:
            edge_tiers[tier] = {"count": 0, "pnl": 0.0, "wins": 0}
        edge_tiers[tier]["count"] += 1
        pnl = float(t.get("realized_pnl", 0) or 0)
        edge_tiers[tier]["pnl"] += pnl
        if pnl > 0:
            edge_tiers[tier]["wins"] += 1

    edge_lines = []
    for tier, stats in sorted(edge_tiers.items()):
        win_rate = stats["wins"] / stats["count"] if stats["count"] else 0.0
        edge_lines.append(
            f"  {tier}: {stats['count']} trades, total_pnl=${stats['pnl']:.2f}, win_rate={win_rate:.1%}"
        )

    # Current .env values
    env_vars = [
        "PAPER_EDGE_THRESHOLD", "PAPER_EDGE_RATIO_THRESHOLD", "PAPER_MIN_RECENT_TRADES",
        "PAPER_MIN_RECENT_NOTIONAL", "PAPER_MIN_BUY_SHARE", "PAPER_MIN_LIQUIDITY",
        "PAPER_MAX_HOURS_TO_EXPIRY", "PAPER_MAX_POSITIONS", "PAPER_MAX_CANDIDATES",
        "PAPER_LOOKBACK_SECONDS", "PAPER_LOOP_SLEEP_SECONDS", "PAPER_MAX_SECONDS_SINCE_LAST_TRADE",
        "PAPER_TAKE_PROFIT_PCT", "PAPER_STOP_LOSS_PCT", "PAPER_MAX_HOLDING_SECONDS",
        "PAPER_MAX_FALLBACK_SECONDS",
    ]
    env_lines = []
    for var in env_vars:
        val = os.getenv(var)
        if val is not None:
            env_lines.append(f"  {var}={val}")

    breakdown_str = json.dumps(breakdown, indent=2)

    prompt = f"""You are a quantitative trading strategist analyzing paper-trading results for a Polymarket ↔ Kalshi cross-market arbitrage bot.

## Bot overview
- Scans Polymarket and Kalshi for matching markets where prices diverge
- Buys on Polymarket when Polymarket price < Kalshi price (minus threshold)
- Paper-trading only — no real money involved
- Runs every 3 minutes; checks stop-loss/take-profit every 1 second

## Current .env parameters
{chr(10).join(env_lines) if env_lines else "  (not loaded)"}

## Trade summary
Total closed trades: {trade_count}
Equity: ${summary.get("equity", "N/A")}
Realized PnL: ${summary.get("realized_pnl", "N/A")}
Win rate: {summary.get("win_rate", "N/A")}

## Exit reason breakdown
{chr(10).join(exit_summary_lines) if exit_summary_lines else "  (no data)"}

## Edge tier breakdown
{chr(10).join(edge_lines) if edge_lines else "  (no data)"}

## Performance breakdown by dimension
{breakdown_str}

## Raw closed trades (most recent 30)
position_id, entry_price, exit_price, holding_seconds, realized_pnl, return_pct, exit_reason, entry_reason
"""
    for t in trades[-30:]:
        prompt += (
            f"  [{t.get('exit_reason','?')}] "
            f"entry={t.get('entry_price','?')} exit={t.get('exit_price','?')} "
            f"hold={t.get('holding_seconds','?')}s "
            f"pnl=${float(t.get('realized_pnl',0) or 0):.2f} "
            f"return={float(t.get('return_pct',0) or 0):.1%} | "
            f"{str(t.get('entry_reason',''))[:120]}\n"
        )

    prompt += """
## Your task

Analyze this trade data and provide:

1. **Pattern analysis** — What patterns do you see in wins vs losses? What's driving the stop-losses? Are there any entry filter improvements suggested by the data?

2. **Specific .env recommendations** — For each parameter you recommend changing, provide:
   - Current value → Recommended value
   - Data-driven rationale (cite specific numbers from the trade data)
   - Expected impact

3. **Top 1-2 priority changes** — If the user can only change one or two things right now, which changes would have the most impact?

Be specific and data-driven. Avoid generic advice. Every recommendation must be traceable to the numbers above.

---

## Required: machine-readable JSON block

After all analysis, output this JSON block as the VERY LAST thing in your response (no text after it):

```json
{
  "summary": "one sentence summary of the single most important finding",
  "changes": [
    {"param": "PARAM_NAME", "current": "current_value", "recommended": "new_value", "rationale": "one sentence cited to the data"}
  ]
}
```

Only include parameters you are recommending to change. Use an empty array if no changes are needed. The values must be plain numbers or strings matching the .env format (no units, no quotes inside the JSON strings).
"""
    return prompt


def run(dry_run: bool = False) -> None:
    trades = _load_closed_trades()
    breakdown = _load_performance_breakdown()
    summary = _load_summary()

    if not trades:
        print("No closed trades found. Run the bot longer to accumulate data.")
        sys.exit(1)

    print(f"Loaded {len(trades)} closed trades.")
    prompt = _build_prompt(trades, breakdown, summary)

    if dry_run:
        print("\n--- PROMPT (dry-run, not sending to Claude) ---\n")
        print(prompt)
        return

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set in .env")
        sys.exit(1)

    try:
        import anthropic
    except ImportError:
        print("Error: anthropic package not installed. Run: uv add anthropic")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    print("Sending to Claude Opus 4.6 (adaptive thinking)...\n")
    print("=" * 70)

    output_chunks: list[str] = []

    with client.messages.stream(
        model="claude-opus-4-6",
        max_tokens=8192,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for event in stream:
            if event.type == "content_block_start":
                if event.content_block.type == "thinking":
                    print("[Thinking...]\n", flush=True)
            elif event.type == "content_block_delta":
                if event.delta.type == "text_delta":
                    print(event.delta.text, end="", flush=True)
                    output_chunks.append(event.delta.text)

        final = stream.get_final_message()

    print("\n" + "=" * 70)
    usage = final.usage
    footer = (
        f"\nTokens — input: {usage.input_tokens} | output: {usage.output_tokens} | "
        f"cache_read: {getattr(usage, 'cache_read_input_tokens', 0)}"
    )
    print(footer)

    # Save full output to file so it can be retrieved without re-running.
    import re
    from datetime import datetime, timezone
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    out_path = Path("advisor_recommendations.txt")
    full_output = "".join(output_chunks)
    out_path.write_text(
        f"Generated: {timestamp} | Trades analyzed: {len(trades)}\n"
        + "=" * 70 + "\n"
        + full_output
        + "\n" + "=" * 70
        + footer + "\n",
        encoding="utf-8",
    )
    print(f"\nSaved to: {out_path}")

    # Extract machine-readable JSON block and save separately for dashboard.
    parsed_rec: dict = {"summary": "", "changes": []}
    json_match = re.search(r"```json\s*(\{.*?\})\s*```", full_output, re.DOTALL)
    if json_match:
        try:
            parsed_rec = json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    rec_data = {
        "trade_count": len(trades),
        "analyzed_at": timestamp,
        "summary": parsed_rec.get("summary", ""),
        "changes": parsed_rec.get("changes", []),
        "applied": False,
        "dismissed": False,
    }
    json_path = Path("advisor_recommendations.json")
    json_path.write_text(json.dumps(rec_data, indent=2), encoding="utf-8")
    print(f"Saved structured recommendations to: {json_path}")
