"""
Trade analysis script — sends trade history to Claude API for strategy insights.

Usage:
  .venv\Scripts\python.exe analyze_trades.py

Requires ANTHROPIC_API_KEY in .env
"""
from __future__ import annotations

import csv
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

TRADES_FILE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("output/5m_trading/trades.csv")
MODEL = "claude-haiku-4-5-20251001"   # cheapest capable model — ~$0.05 per analysis


# ── Load trades ────────────────────────────────────────────────────────────────

def load_trades() -> list[dict]:
    if not TRADES_FILE.exists():
        print(f"ERROR: {TRADES_FILE} not found")
        sys.exit(1)
    with open(TRADES_FILE, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    trades = []
    for row in rows:
        try:
            t = {k: v for k, v in row.items()}
            # Convert numeric fields
            for field in [
                "entry_price", "exit_price", "pnl_usd", "return_pct", "hold_seconds",
                "size_usd", "shares", "secs_remaining_at_entry", "liquidity",
                "btc_pct_change_at_entry", "price_velocity",
                "price_60s_before_entry", "price_30s_before_entry",
                "up_price_at_window_start", "price_60s_after_entry",
            ]:
                try:
                    t[field] = float(t.get(field) or 0)
                except (ValueError, TypeError):
                    t[field] = 0.0
            trades.append(t)
        except Exception:
            pass
    return trades


# ── Compute statistics ─────────────────────────────────────────────────────────

def compute_stats(trades: list[dict]) -> dict:
    wins   = [t for t in trades if t["pnl_usd"] > 0]
    losses = [t for t in trades if t["pnl_usd"] <= 0]

    # By exit reason
    by_reason: dict[str, list] = defaultdict(list)
    for t in trades:
        by_reason[t["exit_reason"]].append(t)

    reason_stats = {}
    for reason, group in sorted(by_reason.items(), key=lambda x: x[0] or ""):
        g_wins = [t for t in group if t["pnl_usd"] > 0]
        total_pnl = sum(t["pnl_usd"] for t in group)
        reason_stats[reason] = {
            "count": len(group),
            "wins": len(g_wins),
            "win_rate_pct": round(len(g_wins) / len(group) * 100, 1),
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(total_pnl / len(group), 2),
            "avg_exit_price": round(sum(t["exit_price"] for t in group) / len(group), 3),
        }

    # By entry price bucket
    def bucket(price):
        if price < 0.20: return "<0.20"
        if price < 0.25: return "0.20-0.25"
        if price < 0.30: return "0.25-0.30"
        if price < 0.35: return "0.30-0.35"
        if price < 0.40: return "0.35-0.40"
        return ">=0.40"

    by_entry: dict[str, list] = defaultdict(list)
    for t in trades:
        by_entry[bucket(t["entry_price"])].append(t)

    entry_stats = {}
    for b in ["<0.20", "0.20-0.25", "0.25-0.30", "0.30-0.35", "0.35-0.40", ">=0.40"]:
        group = by_entry.get(b, [])
        if not group:
            continue
        g_wins = [t for t in group if t["pnl_usd"] > 0]
        total_pnl = sum(t["pnl_usd"] for t in group)
        entry_stats[b] = {
            "count": len(group),
            "win_rate_pct": round(len(g_wins) / len(group) * 100, 1),
            "avg_pnl": round(total_pnl / len(group), 2),
            "total_pnl": round(total_pnl, 2),
        }

    # By side
    by_side: dict[str, list] = defaultdict(list)
    for t in trades:
        by_side[t["side"]].append(t)
    side_stats = {}
    for side, group in by_side.items():
        g_wins = [t for t in group if t["pnl_usd"] > 0]
        side_stats[side] = {
            "count": len(group),
            "win_rate_pct": round(len(g_wins) / len(group) * 100, 1),
            "avg_pnl": round(sum(t["pnl_usd"] for t in group) / len(group), 2),
        }

    # BTC momentum at entry buckets
    def btc_bucket(pct):
        if pct < -0.05: return "strong_down (<-0.05%)"
        if pct < -0.02: return "mild_down (-0.05 to -0.02%)"
        if pct < 0.02:  return "flat (-0.02 to +0.02%)"
        if pct < 0.05:  return "mild_up (+0.02 to +0.05%)"
        return "strong_up (>+0.05%)"

    btc_trades = [t for t in trades if t["btc_pct_change_at_entry"] != 0]
    by_btc: dict[str, list] = defaultdict(list)
    for t in btc_trades:
        by_btc[btc_bucket(t["btc_pct_change_at_entry"])].append(t)

    btc_stats = {}
    for b, group in sorted(by_btc.items()):
        g_wins = [t for t in group if t["pnl_usd"] > 0]
        btc_stats[b] = {
            "count": len(group),
            "win_rate_pct": round(len(g_wins) / len(group) * 100, 1) if group else 0,
            "avg_pnl": round(sum(t["pnl_usd"] for t in group) / len(group), 2) if group else 0,
        }

    # Time remaining at entry
    def time_bucket(secs):
        if secs >= 250: return "250-300s (first 50s)"
        if secs >= 200: return "200-250s"
        if secs >= 150: return "150-200s"
        return "<150s"

    by_time: dict[str, list] = defaultdict(list)
    for t in trades:
        if t["secs_remaining_at_entry"] > 0:
            by_time[time_bucket(t["secs_remaining_at_entry"])].append(t)

    time_stats = {}
    for b in ["250-300s (first 50s)", "200-250s", "150-200s", "<150s"]:
        group = by_time.get(b, [])
        if not group:
            continue
        g_wins = [t for t in group if t["pnl_usd"] > 0]
        time_stats[b] = {
            "count": len(group),
            "win_rate_pct": round(len(g_wins) / len(group) * 100, 1),
            "avg_pnl": round(sum(t["pnl_usd"] for t in group) / len(group), 2),
        }

    # Resolution analysis (trades where resolution_side is filled)
    resolved = [t for t in trades if t.get("resolution_side") in ("UP", "DOWN")]
    resolution_stats = None
    if resolved:
        won = [t for t in resolved if t.get("our_side_won") == "True"]
        lost = [t for t in resolved if t.get("our_side_won") == "False"]

        # For trades where we exited early (not take_profit/force_exit_price) but our side won:
        # what was price_60s_after_entry? Could we have held?
        early_exits = [t for t in resolved if t["exit_reason"] in
                       ("trailing_stop_z2", "trailing_stop_z3", "force_exit_time", "window_expired")]
        early_won = [t for t in early_exits if t.get("our_side_won") == "True"]
        early_lost = [t for t in early_exits if t.get("our_side_won") == "False"]

        resolution_stats = {
            "total_resolved": len(resolved),
            "our_side_won": len(won),
            "our_side_lost": len(lost),
            "our_side_win_rate_pct": round(len(won) / len(resolved) * 100, 1) if resolved else 0,
            "early_exits_total": len(early_exits),
            "early_exits_our_side_won": len(early_won),
            "early_exits_avg_pnl_when_side_won": round(
                sum(t["pnl_usd"] for t in early_won) / len(early_won), 2
            ) if early_won else None,
            "note": "early_exits_our_side_won = trades we stopped out of but our chosen side ultimately paid $1.00"
        }

    # Price velocity analysis (for trades where it was captured)
    vel_trades = [t for t in trades if t["price_velocity"] != 0]
    velocity_stats = None
    if vel_trades:
        def vel_bucket(v):
            if v < -0.001: return "strong_reverting (<-0.001 c/s)"
            if v < 0:      return "mild_reverting"
            if v < 0.001:  return "flat"
            return "chasing (>+0.001 c/s)"
        by_vel: dict[str, list] = defaultdict(list)
        for t in vel_trades:
            by_vel[vel_bucket(t["price_velocity"])].append(t)
        velocity_stats = {}
        for b, group in sorted(by_vel.items()):
            g_wins = [t for t in group if t["pnl_usd"] > 0]
            velocity_stats[b] = {
                "count": len(group),
                "win_rate_pct": round(len(g_wins) / len(group) * 100, 1),
                "avg_pnl": round(sum(t["pnl_usd"] for t in group) / len(group), 2),
            }

    # Worst individual trades
    worst = sorted(trades, key=lambda t: t["pnl_usd"])[:5]
    worst_trades = [
        {
            "exit_reason": t["exit_reason"],
            "side": t["side"],
            "entry_price": t["entry_price"],
            "exit_price": t["exit_price"],
            "pnl_usd": t["pnl_usd"],
            "hold_seconds": t["hold_seconds"],
            "secs_remaining_at_entry": t["secs_remaining_at_entry"],
        }
        for t in worst
    ]

    # Best individual trades
    best = sorted(trades, key=lambda t: t["pnl_usd"], reverse=True)[:5]
    best_trades = [
        {
            "exit_reason": t["exit_reason"],
            "side": t["side"],
            "entry_price": t["entry_price"],
            "exit_price": t["exit_price"],
            "pnl_usd": t["pnl_usd"],
            "hold_seconds": t["hold_seconds"],
            "secs_remaining_at_entry": t["secs_remaining_at_entry"],
        }
        for t in best
    ]

    total_pnl = sum(t["pnl_usd"] for t in trades)

    # Recent trades (last 30) = closest to current strategy (ENTRY_MIN=0.30, no stops)
    recent = trades[-30:]
    recent_wins   = [t for t in recent if t["pnl_usd"] > 0]
    recent_losses = [t for t in recent if t["pnl_usd"] <= 0]
    recent_pnl    = sum(t["pnl_usd"] for t in recent)
    recent_by_reason: dict[str, list] = defaultdict(list)
    for t in recent:
        recent_by_reason[t["exit_reason"]].append(t)
    recent_reason_stats = {}
    for reason, group in sorted(recent_by_reason.items(), key=lambda x: x[0] or ""):
        g_wins = [t for t in group if t["pnl_usd"] > 0]
        recent_reason_stats[reason] = {
            "count": len(group),
            "wins": len(g_wins),
            "win_rate_pct": round(len(g_wins) / len(group) * 100, 1),
            "total_pnl": round(sum(t["pnl_usd"] for t in group), 2),
            "avg_pnl": round(sum(t["pnl_usd"] for t in group) / len(group), 2),
            "avg_exit_price": round(sum(t["exit_price"] for t in group) / len(group), 3),
        }

    # Recent entry price buckets
    recent_by_entry: dict[str, list] = defaultdict(list)
    for t in recent:
        recent_by_entry[bucket(t["entry_price"])].append(t)
    recent_entry_stats = {}
    for b in ["<0.20", "0.20-0.25", "0.25-0.30", "0.30-0.35", "0.35-0.40", ">=0.40"]:
        group = recent_by_entry.get(b, [])
        if not group:
            continue
        g_wins = [t for t in group if t["pnl_usd"] > 0]
        recent_entry_stats[b] = {
            "count": len(group),
            "win_rate_pct": round(len(g_wins) / len(group) * 100, 1),
            "avg_pnl": round(sum(t["pnl_usd"] for t in group) / len(group), 2),
            "total_pnl": round(sum(t["pnl_usd"] for t in group), 2),
        }

    return {
        "overview": {
            "total_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_pct": round(len(wins) / len(trades) * 100, 1) if trades else 0,
            "total_pnl_usd": round(total_pnl, 2),
            "avg_win_usd": round(sum(t["pnl_usd"] for t in wins) / len(wins), 2) if wins else 0,
            "avg_loss_usd": round(sum(t["pnl_usd"] for t in losses) / len(losses), 2) if losses else 0,
            "position_size_usd": 20.0,
            "entry_range": "0.30-0.39 current (was 0.15-0.40 in early trades)",
            "take_profit": "0.50",
            "hard_floor_stop": "0.08 (exit if our side drops below 8c — added today)",
            "trailing_stops": "NONE — z1/z2/z3 all removed (0% WR, cut mid-reversion)",
        },
        "recent_60_trades_CURRENT_STRATEGY": {
            "count": len(recent),
            "wins": len(recent_wins),
            "losses": len(recent_losses),
            "win_rate_pct": round(len(recent_wins) / len(recent) * 100, 1) if recent else 0,
            "total_pnl_usd": round(recent_pnl, 2),
            "avg_win_usd": round(sum(t["pnl_usd"] for t in recent_wins) / len(recent_wins), 2) if recent_wins else 0,
            "avg_loss_usd": round(sum(t["pnl_usd"] for t in recent_losses) / len(recent_losses), 2) if recent_losses else 0,
            "by_exit_reason": recent_reason_stats,
            "by_entry_price_bucket": recent_entry_stats,
        },
        "by_exit_reason": reason_stats,
        "by_entry_price_bucket": entry_stats,
        "by_side": side_stats,
        "by_btc_momentum_at_entry": btc_stats if btc_stats else "no BTC data captured yet",
        "by_time_remaining_at_entry": time_stats if time_stats else "no time data yet",
        "price_velocity_analysis": velocity_stats or "insufficient velocity data",
        "resolution_analysis": resolution_stats or "resolution tracking not yet active (recently added)",
        "worst_5_trades": worst_trades,
        "best_5_trades": best_trades,
    }


# ── Build prompt ───────────────────────────────────────────────────────────────

PROMPT_TEMPLATE = """\
You are analyzing paper trading data for a Polymarket 5-minute BTC Up/Down market bot.

CURRENT STRATEGY (what is running RIGHT NOW as of today):
- Each 5-minute window: BTC either goes UP or DOWN vs the window open price
- Bot enters the CHEAPER side (UP or DOWN) when price is between 30c and 39c (ENTRY_MIN=0.30, ENTRY_MAX=0.39)
- Entry window: first 45 seconds only (>=255s must remain)
- Take profit: 50c (mean reversion to neutral)
- Hard floor stop: exit if our side drops below 8c (token near-worthless, mean reversion from 0.08->0.50 ~0% observed)
- BTC flatness filter: skip entry if Chainlink pct_change > +/-0.02% at window open (BTC already moving)
- BTC momentum filter: skip if BTC moving >$20/min against our side
- NO trailing stops (z1, z2, z3 all removed — they had 0% win rate, cut mid-reversion)
- Force exit time: exit at 5s remaining
- Position size: $20 per trade, 0% maker fee (limit orders)
- One trade per window max (traded_windows set prevents re-entry)
- All values are probability prices: 50c = 50% chance this side wins

STRATEGY HISTORY — what has changed and when:
- MOST trades in the dataset are from OLDER strategy versions, not the current one.
- The last ~20-30 trades best reflect the current strategy.
- z1 stop (exit if 5c below entry when <120s left): removed after ~trade 50. 0% WR.
- z2 stop (exit if below entry_price when <60s left): removed after ~trade 158. 0% WR.
- z3 stop (exit if below 42.5c when <30s left): removed after ~trade 158. 0% WR.
- ENTRY_MIN raised 0.15->0.30 after trade 158 analysis (entries <25c had 2.9% WR).
- ENTRY_MAX lowered 0.40->0.39 after trade 158 analysis.
- Entry window tightened 90s->45s after trade 158 analysis.
- force_exit_time lowered 10s->5s today.
- Hard floor stop at 0.08 added today (force_exits were riding to 0.005 = ~100% loss).
- BTC flatness filter added today.

TRADE STATISTICS (all trades, plus recent-only breakdown):
{stats_json}

QUESTIONS TO ANSWER:
1. Looking at the RECENT trades (last 30): what is the actual WR and EV? Is there a profitable edge at 30-39c entries?
2. The force_exit_time trades are nearly total losses (~95-99% loss each). How many are there recently?
   At 57% WR overall, the break-even WR required is ~68% (avg win $9, avg loss $19). Are we trending toward that?
3. Is the mean-reversion thesis supported? When we enter at 30-39c, does price reach 50c in most cases?
4. What does the btc_pct_change_at_entry data show? Does a flat BTC at window start predict better outcomes?
5. Give 3 specific, data-driven recommendations for the CURRENT strategy (30-39c entries, 45s window, no stops).
   Focus on: entry filter improvements, position sizing, or exit timing. Reference specific numbers.
6. Should we raise ENTRY_MIN further (e.g., to 33c or 35c)? What do the recent entry price buckets show?

Be direct and data-driven. Reference specific numbers from the stats. Actionable recommendations only.
"""


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set in .env")
        print("Add: ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    print("Loading trades...")
    trades = load_trades()
    print(f"Loaded {len(trades)} trades")

    print("Computing statistics...")
    stats = compute_stats(trades)

    stats_json = json.dumps(stats, indent=2)
    prompt = PROMPT_TEMPLATE.format(stats_json=stats_json)

    # Estimate token count (rough: 1 token ≈ 4 chars)
    est_tokens = len(prompt) / 4
    print(f"Prompt size: ~{est_tokens:.0f} tokens (~${est_tokens / 1_000_000 * 0.25:.4f} for Haiku input)")

    print(f"\nSending to {MODEL}...\n")
    print("=" * 70)

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    message = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    response = message.content[0].text
    safe_response = response.encode("ascii", errors="replace").decode("ascii")
    print(safe_response)
    print("=" * 70)

    usage = message.usage
    input_cost  = usage.input_tokens  / 1_000_000 * 0.25
    output_cost = usage.output_tokens / 1_000_000 * 1.25
    total_cost  = input_cost + output_cost
    print(f"\nTokens: {usage.input_tokens} in / {usage.output_tokens} out | Cost: ${total_cost:.4f}")

    # Save output
    out_file = Path("output/5m_trading/analysis.txt")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(f"Analysis run on {len(trades)} trades\n")
        f.write("=" * 70 + "\n")
        f.write(response)
        f.write("\n" + "=" * 70 + "\n")
        f.write(f"Tokens: {usage.input_tokens} in / {usage.output_tokens} out | Cost: ${total_cost:.4f}\n")
    print(f"Saved to {out_file}")


if __name__ == "__main__":
    main()
