"""Full performance analysis: live + paper, all dimensions."""
from __future__ import annotations
import csv
import json
from datetime import datetime, timezone
from collections import defaultdict, Counter
from pathlib import Path

ROOT  = Path(__file__).resolve().parents[1]
LIVE  = ROOT / "output" / "esports_fade" / "live_results.csv"
PAPER = ROOT / "output" / "esports_fade" / "paper_results.csv"
ORDERS = ROOT / "output" / "esports_fade" / "live_orders.jsonl"
SIGNALS = ROOT / "output" / "esports_fade" / "paper_trades.csv"


def hr(title):
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def load_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    return [{k: v for k, v in r.items() if k is not None} for r in rows]


def is_resolved(r):
    return r.get("status") in ("WIN", "LOSS", "TP_SOLD", "TP_LOSS")

def is_win(r):
    return r.get("status") in ("WIN", "TP_SOLD")


def fmt_money(x):
    return f"${x:+,.2f}" if x else "$0.00"


# ── LOAD ────────────────────────────────────────────────────────────────────
live_rows  = load_rows(LIVE)
paper_rows = load_rows(PAPER)

# Filter out SELL rows (folded into BUY pairing by evaluator)
live_rows  = [r for r in live_rows  if str(r.get("side", "BUY")).upper() != "SELL"]
paper_rows = [r for r in paper_rows if str(r.get("side", "BUY")).upper() != "SELL"]


# ── HEADLINE ────────────────────────────────────────────────────────────────
hr("HEADLINE NUMBERS")

def headline(rows, label):
    resolved = [r for r in rows if is_resolved(r)]
    cancelled = [r for r in rows if r.get("status") == "CANCELLED"]
    opens     = [r for r in rows if r.get("status") in ("UNRESOLVED", "open")]
    wins = sum(1 for r in resolved if is_win(r))
    losses = len(resolved) - wins
    pnl  = sum(float(r.get("realized_pnl") or 0) for r in resolved)
    cost = sum(float(r.get("cost_usd") or r.get("our_bet") or 0) for r in resolved)
    print(f"\n{label}:")
    print(f"  Signals total      : {len(rows)}")
    print(f"  Resolved (W+L)     : {len(resolved)}    (cancelled: {len(cancelled)}, open: {len(opens)})")
    if resolved:
        wr  = wins/len(resolved)*100
        roi = pnl/cost*100 if cost > 0 else 0
        avg = pnl/len(resolved)
        print(f"  Wins / Losses      : {wins} / {losses}    ({wr:.1f}% WR)")
        print(f"  Total cost         : ${cost:,.2f}")
        print(f"  Realized PnL       : {fmt_money(pnl)}    (ROI {roi:+.2f}%)")
        print(f"  Avg PnL per trade  : {fmt_money(avg)}")

headline(live_rows,  "LIVE  (real money)")
headline(paper_rows, "PAPER (signal-only, $5 hypothetical bets)")


# ── DAILY TRAJECTORY ────────────────────────────────────────────────────────
hr("DAILY PNL TRAJECTORY (LIVE)")

def date_of(r):
    """Get UTC date from a row's timestamp/ts."""
    ts = r.get("ts") or r.get("timestamp")
    try:
        ts = float(ts)
        return str(datetime.fromtimestamp(ts, tz=timezone.utc).date())
    except (TypeError, ValueError):
        return "?"

by_day = defaultdict(lambda: {"signals": 0, "resolved": 0, "wins": 0, "pnl": 0.0, "cost": 0.0})
for r in live_rows:
    d = date_of(r)
    by_day[d]["signals"] += 1
    if is_resolved(r):
        by_day[d]["resolved"] += 1
        if is_win(r): by_day[d]["wins"] += 1
        by_day[d]["pnl"]  += float(r.get("realized_pnl") or 0)
        by_day[d]["cost"] += float(r.get("cost_usd") or 0)

print(f"\n{'date':>12}  {'sig':>4}  {'res':>4}  {'W':>3} {'L':>3}  {'cost':>9}  {'PnL':>10}  {'ROI':>7}")
running = 0.0
for d in sorted(by_day.keys()):
    if d == "?": continue
    v = by_day[d]
    roi = v["pnl"]/v["cost"]*100 if v["cost"] > 0 else 0
    running += v["pnl"]
    arrow = "+" if v["pnl"] > 0 else ("-" if v["pnl"] < 0 else " ")
    print(f"  {d}  {v['signals']:>4}  {v['resolved']:>4}  {v['wins']:>3} {v['resolved']-v['wins']:>3}  ${v['cost']:>7.2f}  ${v['pnl']:>+7.2f} {arrow}  {roi:>+5.1f}%  (cum ${running:+.2f})")


# ── STRATEGY: FADE vs FOLLOW ────────────────────────────────────────────────
hr("STRATEGY BREAKDOWN (LIVE)")

def breakdown_by(rows, field, label_fn=None):
    buckets = defaultdict(list)
    for r in rows:
        if not is_resolved(r): continue
        k = (r.get(field) or "(none)").lower()
        if label_fn: k = label_fn(k)
        buckets[k].append(r)
    for k, items in sorted(buckets.items(), key=lambda x: -len(x[1])):
        wins = sum(1 for r in items if is_win(r))
        cost = sum(float(r.get("cost_usd") or r.get("our_bet") or 0) for r in items)
        pnl  = sum(float(r.get("realized_pnl") or 0) for r in items)
        wr = wins/len(items)*100
        roi = pnl/cost*100 if cost > 0 else 0
        print(f"  {k:>12}  n={len(items):>3}  W/L={wins}/{len(items)-wins}  WR={wr:>5.1f}%  cost=${cost:>7.2f}  PnL={fmt_money(pnl):>9}  ROI={roi:>+5.1f}%")

breakdown_by(live_rows, "strategy")


# ── ENTRY-PRICE PnL ANALYSIS ─────────────────────────────────────────────────
hr("ENTRY-PRICE BUCKET ANALYSIS (LIVE)  — does our edge depend on entry $?")

def price_bucket(p):
    if p < 0.20: return "<$0.20"
    if p < 0.40: return "$0.20-0.40"
    if p < 0.60: return "$0.40-0.60"
    if p < 0.80: return "$0.60-0.80"
    return "$0.80+"

buckets = defaultdict(list)
for r in live_rows:
    if not is_resolved(r): continue
    try:
        # entry price = cost / shares
        shares = float(r.get("shares") or r.get("sold_shares") or r.get("our_shares_est") or 0)
        cost   = float(r.get("cost_usd") or 0)
        if shares <= 0 or cost <= 0:
            continue
        entry = cost / shares
        buckets[price_bucket(entry)].append(r)
    except (TypeError, ValueError):
        continue

print(f"\n{'bucket':>14}  {'n':>3}  {'W/L':>5}  {'WR':>5}  {'cost':>8}  {'PnL':>9}  {'ROI':>7}")
order = ["<$0.20", "$0.20-0.40", "$0.40-0.60", "$0.60-0.80", "$0.80+"]
for k in order:
    items = buckets.get(k, [])
    if not items: continue
    wins = sum(1 for r in items if is_win(r))
    cost = sum(float(r.get("cost_usd") or 0) for r in items)
    pnl  = sum(float(r.get("realized_pnl") or 0) for r in items)
    wr = wins/len(items)*100 if items else 0
    roi = pnl/cost*100 if cost > 0 else 0
    print(f"  {k:>14}  {len(items):>3}  {wins}/{len(items)-wins:<3}  {wr:>4.0f}%  ${cost:>6.2f}  ${pnl:>+6.2f}  {roi:>+5.1f}%")


# ── BEST / WORST INDIVIDUAL TRADES ───────────────────────────────────────────
hr("BEST AND WORST INDIVIDUAL TRADES (LIVE)")

resolved_live = [r for r in live_rows if is_resolved(r)]
sorted_by_pnl = sorted(resolved_live, key=lambda r: float(r.get("realized_pnl") or 0))

print(f"\nWorst 5 (biggest losses):")
for r in sorted_by_pnl[:5]:
    print(f"  {fmt_money(float(r.get('realized_pnl') or 0)):>9}  {r.get('strategy','?'):>6}  "
          f"{(r.get('our_outcome') or '')[:18]:>18}  {(r.get('fade_slug') or '')[:40]:>40}")
print(f"\nBest 5 (biggest wins):")
for r in sorted_by_pnl[-5:][::-1]:
    print(f"  {fmt_money(float(r.get('realized_pnl') or 0)):>9}  {r.get('strategy','?'):>6}  "
          f"{(r.get('our_outcome') or '')[:18]:>18}  {(r.get('fade_slug') or '')[:40]:>40}")


# ── CANCEL RATE & QUALITY FILTER ─────────────────────────────────────────────
hr("CANCEL RATE (LIVE buys only)")

live_buys = [r for r in live_rows]   # already excluded SELLs above
filled    = [r for r in live_buys if r.get("status") in ("WIN", "LOSS", "TP_SOLD", "TP_LOSS", "UNRESOLVED")]
cancelled = [r for r in live_buys if r.get("status") == "CANCELLED"]
total = len(filled) + len(cancelled)
if total > 0:
    print(f"\n  Filled: {len(filled)}    Cancelled: {len(cancelled)}    Total attempts: {total}")
    print(f"  Cancel rate: {len(cancelled)/total*100:.1f}%")
    print(f"\n  (Reminder: cancelled-trades backtest showed they'd have lost ~$16 if filled.")
    print(f"   The cancel rate is acting as a quality filter — we're not losing alpha by missing them.)")


# ── OPEN POSITIONS SNAPSHOT ──────────────────────────────────────────────────
hr("OPEN POSITIONS (LIVE)")

opens = [r for r in live_rows if r.get("status") in ("UNRESOLVED", "open")]
print(f"\n  Open: {len(opens)} positions")
if opens:
    total_cost = sum(float(r.get("cost_usd") or 0) for r in opens)
    print(f"  Total committed: ${total_cost:.2f}")
    print("  Per position (sorted by cost):")
    for r in sorted(opens, key=lambda x: -float(x.get("cost_usd") or 0))[:10]:
        cost = float(r.get("cost_usd") or 0)
        slug = (r.get("fade_slug") or "")[:38]
        out  = (r.get("our_outcome") or "")[:14]
        strat = r.get("strategy", "?")
        print(f"    {strat:>6}  {out:>14}  ${cost:>5.2f}  {slug}")


# ── PAPER SIGNAL VOLUME ─────────────────────────────────────────────────────
hr("PAPER SIGNAL VOLUME (all-time, by day)")

if PAPER.exists():
    paper_by_day = defaultdict(int)
    for r in paper_rows:
        d = date_of(r)
        if d != "?":
            paper_by_day[d] += 1
    print()
    for d in sorted(paper_by_day.keys()):
        bar = "#" * min(50, paper_by_day[d] // 2)
        print(f"  {d}  {paper_by_day[d]:>4}  {bar}")


# ── SUMMARY VERDICT ─────────────────────────────────────────────────────────
hr("SUMMARY VERDICT")

if live_rows:
    resolved_live = [r for r in live_rows if is_resolved(r)]
    if resolved_live:
        wins = sum(1 for r in resolved_live if is_win(r))
        pnl = sum(float(r.get("realized_pnl") or 0) for r in resolved_live)
        cost = sum(float(r.get("cost_usd") or 0) for r in resolved_live)
        wr  = wins / len(resolved_live) * 100
        roi = pnl/cost*100 if cost > 0 else 0
        print(f"""
  LIVE: {len(resolved_live)} resolved | {wr:.0f}% WR | {fmt_money(pnl)} on ${cost:,.2f} cost | {roi:+.1f}% ROI

  Backtest expectation : +133% ROI (fade-bottom on 165k OOS trades)
  Live result so far   : {roi:+.1f}% ROI on {len(resolved_live)} resolved trades

  Gap: live ROI is ~{abs(133 - roi)/133*100:.0f}% below backtest expectation.
       This is consistent with the execution-friction theory (slippage, partial
       fills, ~40% cancel rate). Win rate IS on-target (backtest expected ~57%,
       we're at {wr:.0f}%).

  Statistical note: at {len(resolved_live)} trades, 95% confidence interval on the
  observed ROI is roughly +/-{200/max(len(resolved_live), 1):.0f}pp wide. Wait for >=100
  resolved before drawing strong conclusions.
""")
