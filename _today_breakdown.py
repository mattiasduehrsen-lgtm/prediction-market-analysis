"""One-off: show today's resolved trades + new orders + bankroll math."""
import csv, json, datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output" / "esports_fade"
today = dt.datetime.now(dt.timezone.utc).date()
print(f"Today (UTC): {today}\n")

print("=== Trades RESOLVED today ===")
total_resolved_pnl = 0.0
total_resolved_cost = 0.0
n_win = n_loss = 0
with open(OUT / "live_results.csv", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        try: ts = float(r.get("ts") or 0)
        except: continue
        if not ts: continue
        d = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).date()
        if d != today: continue
        if r.get("status") not in ("WIN","LOSS","TP_SOLD","TP_LOSS"): continue
        if str(r.get("side","BUY")).upper() == "SELL": continue
        cost = float(r.get("cost_usd") or 0)
        pnl  = float(r.get("realized_pnl") or 0)
        total_resolved_pnl  += pnl
        total_resolved_cost += cost
        if r["status"] in ("WIN","TP_SOLD"): n_win += 1
        else: n_loss += 1
        print(f"  {r['status']:<6} {r.get('our_outcome','')[:18]:>18}  "
              f"cost=${cost:>5.2f}  pnl=${pnl:>+6.2f}  "
              f"slug={r.get('fade_slug','')[:42]}")
print(f"\n  -> {n_win}W / {n_loss}L  cost=${total_resolved_cost:.2f}  "
      f"realized PnL=${total_resolved_pnl:+.2f}")

print("\n=== NEW orders placed today ===")
total_new_cost = 0.0
n_orders = 0
with open(OUT / "live_orders.jsonl", encoding="utf-8") as f:
    for line in f:
        try: o = json.loads(line)
        except: continue
        ts = float(o.get("ts") or 0)
        if not ts: continue
        d = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).date()
        if d != today: continue
        if str(o.get("side","BUY")).upper() != "BUY": continue
        cost = float(o.get("cost_usd") or 0)
        status = str(o.get("status") or "").lower()
        if status == "matched":
            total_new_cost += cost
            n_orders += 1
        print(f"  {status:<10} cost=${cost:>5.2f}  outcome={o.get('our_outcome','')[:18]:>18}  "
              f"slug={o.get('fade_slug','')[:42]}")
print(f"\n  -> {n_orders} filled, ${total_new_cost:.2f} spent on NEW positions today")

print("\n=== Bankroll math for today ===")
print(f"  Cash spent on NEW positions  : -${total_new_cost:.2f}")
print(f"  Cash returned on RESOLVED    : ${total_resolved_pnl + total_resolved_cost:+.2f}  "
      f"(cost ${total_resolved_cost:.2f} returned + pnl ${total_resolved_pnl:+.2f})")
print(f"  Net cash change today        : "
      f"${(total_resolved_pnl + total_resolved_cost) - total_new_cost:+.2f}")
print(f"  Today's REALIZED pnl (calendar shows this): ${total_resolved_pnl:+.2f}")
print(f"  Open positions placed today  : ${total_new_cost:.2f} worth")
