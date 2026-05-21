"""Read fade_events.jsonl and report on the latency breakdown of LIVE orders.

Tells you whether our 41% cancel rate is being driven by lag (we're slow getting
the signal / submitting the order) or by book-depth (we're on time but the
price has already moved). Used to decide between (1) WebSocket subscription
and (4) VPS co-location.

Run: python analysis/latency_report.py
"""
from __future__ import annotations
import json
import statistics as stats
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "output" / "esports_fade" / "fade_events.jsonl"


def pct(xs, q):
    if not xs:
        return None
    return round(stats.quantiles(xs, n=100)[q - 1], 3) if len(xs) >= 100 else round(sorted(xs)[int(len(xs) * q / 100)], 3)


def main() -> None:
    if not EVENTS.exists():
        print(f"No events file at {EVENTS}")
        return

    placed: dict[str, dict] = {}   # order_id -> last live_order_placed event
    finals: list[dict] = []
    skipped_no_timing = 0

    with EVENTS.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            t = e.get("type")
            if t == "live_order_placed":
                oid = e.get("order_id") or ""
                if oid:
                    placed[oid] = e
            elif t == "live_order_final":
                if e.get("their_fill_ts") is None:
                    skipped_no_timing += 1
                    continue
                finals.append(e)

    print(f"Loaded {len(finals)} finalized orders with timing data.")
    if skipped_no_timing:
        print(f"  (Skipped {skipped_no_timing} pre-instrumentation orders.)")
    if not finals:
        print("No instrumented orders yet. Let the bot run a few hours and re-run this.")
        return

    by_status: dict[str, list[dict]] = defaultdict(list)
    for f in finals:
        by_status[(f.get("status") or "unknown").lower()].append(f)

    print()
    print(f"{'status':>12}  {'n':>4}  "
          f"{'their_fill->submit':>20}  "
          f"{'signal->submit':>18}  "
          f"{'submit->final':>16}  "
          f"{'total':>10}")
    print(f"{'':>12}  {'':>4}  "
          f"{'p50 / p90 / p99':>20}  "
          f"{'p50 / p90 / p99':>18}  "
          f"{'p50 / p90 / p99':>16}  "
          f"{'p50 / p99':>10}")
    print("-" * 92)

    def summarize(items, key):
        xs = [it.get(key) for it in items if isinstance(it.get(key), (int, float))]
        if not xs:
            return "-"
        return f"{pct(xs,50)}/{pct(xs,90)}/{pct(xs,99)}"

    for status, items in sorted(by_status.items(), key=lambda x: -len(x[1])):
        n = len(items)
        a = summarize(items, "lag_their_fill_to_submit_s") if any(
            it.get("lag_their_fill_to_submit_s") is not None for it in items
        ) else summarize(items, "lag_total_s")  # fallback
        # For backward compat we compute lag_their_fill_to_submit from final event:
        for it in items:
            if it.get("lag_their_fill_to_submit_s") is None and it.get("their_fill_ts") and it.get("submit_at"):
                it["lag_their_fill_to_submit_s"] = round(it["submit_at"] - it["their_fill_ts"], 3)
            if it.get("lag_signal_to_submit_s") is None and it.get("signal_seen_at") and it.get("submit_at"):
                it["lag_signal_to_submit_s"] = round(it["submit_at"] - it["signal_seen_at"], 3)
        tfs = summarize(items, "lag_their_fill_to_submit_s")
        sss = summarize(items, "lag_signal_to_submit_s")
        sfs = summarize(items, "lag_submit_to_final_s")
        totals = [it.get("lag_total_s") for it in items if isinstance(it.get("lag_total_s"), (int, float))]
        tot = f"{pct(totals,50)}/{pct(totals,99)}" if totals else "-"
        print(f"{status:>12}  {n:>4}  {tfs:>20}  {sss:>18}  {sfs:>16}  {tot:>10}")

    # Bottom line: what fraction of cancels happened because we were slow?
    cancelled = by_status.get("cancelled", [])
    matched   = by_status.get("matched", [])
    if cancelled and matched:
        print()
        print("Slowness vs. cancels:")
        slow_cancels = [c for c in cancelled if isinstance(c.get("lag_their_fill_to_submit_s"), (int, float)) and c["lag_their_fill_to_submit_s"] > 2.0]
        fast_cancels = [c for c in cancelled if isinstance(c.get("lag_their_fill_to_submit_s"), (int, float)) and c["lag_their_fill_to_submit_s"] <= 2.0]
        print(f"  Cancelled orders where we were SLOW (>2s lag from their fill): {len(slow_cancels)} / {len(cancelled)}")
        print(f"  Cancelled orders where we were FAST (<=2s lag): {len(fast_cancels)} / {len(cancelled)}")
        if len(cancelled) > 0:
            slow_pct = 100 * len(slow_cancels) / len(cancelled)
            if slow_pct > 50:
                print(f"  -> WebSocket would help: {slow_pct:.0f}% of cancels were latency-driven")
            else:
                print(f"  -> Latency is NOT the main cancel driver ({slow_pct:.0f}% latency-driven).")
                print(f"     {100-slow_pct:.0f}% of cancels happened despite quick submission — book depth or price moved.")


if __name__ == "__main__":
    main()
