"""Significance of the in-play edge: did bets win MORE OFTEN than the market price
implied? (The correct test for a longshot book — immune to the 'top-3 wins are 91%
of PnL' objection, because it tests frequencies, not payoffs.) Laptop."""
import csv, math
from pathlib import Path

ROOT = Path(r"C:\Users\matti\Desktop\prediction-market-analysis")
rows = [r for r in csv.DictReader((ROOT / "output" / "cs2_inplay" / "paper_results.csv").open(encoding="utf-8"))
        if r.get("status") in ("WIN", "LOSS")]

def test(label, items):
    n = len(items)
    if not n:
        print(f"{label:36} n=0"); return
    exp = sum(float(r["entry_price"]) for r in items)       # market-implied expected wins
    obs = sum(1 for r in items if r["status"] == "WIN")
    var = sum(float(r["entry_price"]) * (1 - float(r["entry_price"])) for r in items)
    z = (obs - exp) / math.sqrt(var) if var > 0 else 0.0
    p = 0.5 * math.erfc(z / math.sqrt(2))                    # one-sided
    print(f"{label:36} n={n:3d} implied_wins={exp:5.1f} actual={obs:3d} z={z:+.2f} p(one-sided)={p:.4f}")

B = [r for r in rows if r.get("bet_side") == "B"]
A = [r for r in rows if r.get("bet_side") == "A"]
test("ALL bets", rows)
test("contrarian (B) all", B)
test("contrarian entry<=0.30", [r for r in B if float(r["entry_price"]) <= 0.30])
test("contrarian entry<=0.15", [r for r in B if float(r["entry_price"]) <= 0.15])
test("front-run (A) all", A)
