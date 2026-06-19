"""Summarize LoL observe-only data to answer the two open questions:
  (1) LIQUIDITY — are LoL book depths fillable, or a mirage (the CS2 killer)?
  (2) EDGE      — does the LoL model disagree with the market enough to matter?
Run on the laptop once output/esports_fade/lol_observations.csv has rows."""
import csv, statistics as st
from pathlib import Path

ROOT = Path(r"C:\Users\matti\Desktop\prediction-market-analysis")
p = ROOT / "output" / "esports_fade" / "lol_observations.csv"
if not p.exists():
    print("no lol_observations.csv yet — no LoL target activity observed."); raise SystemExit

rows = list(csv.DictReader(p.open(encoding="utf-8")))
print(f"LoL observations: {len(rows)}")
matched = [r for r in rows if r.get("model_reason") == "ok"]
print(f"model-matched: {len(matched)}/{len(rows)} "
      f"({len(matched)/len(rows)*100:.0f}%)  [unmatched/low_games can't be priced]")

def fnums(rs, key):
    out = []
    for r in rs:
        v = r.get(key, "")
        if v not in ("", None):
            try: out.append(float(v))
            except ValueError: pass
    return out

depths = fnums(rows, "book_depth_usd")
if depths:
    depths.sort()
    fill10 = sum(1 for d in depths if d >= 10)
    fill50 = sum(1 for d in depths if d >= 50)
    print(f"\nLIQUIDITY (book depth within 2c of best ask):")
    print(f"  median=${st.median(depths):.0f}  p25=${depths[len(depths)//4]:.0f}  "
          f"p75=${depths[3*len(depths)//4]:.0f}  max=${max(depths):.0f}")
    print(f"  >=$10 (our bet): {fill10}/{len(depths)} ({fill10/len(depths)*100:.0f}%)")
    print(f"  >=$50 fillable : {fill50}/{len(depths)} ({fill50/len(depths)*100:.0f}%)")

edges = fnums(matched, "model_edge")
if edges:
    edges.sort()
    pos = sum(1 for e in edges if e > 0.07)
    print(f"\nEDGE (model_p - market price, matched only):")
    print(f"  median={st.median(edges):+.3f}  min={min(edges):+.3f}  max={max(edges):+.3f}")
    print(f"  edge>0.07 (would-fade threshold): {pos}/{len(edges)}")

wf = sum(1 for r in rows if r.get("would_fade") == "1")
print(f"\nWOULD-FADE (edge>0.07 AND fillable): {wf}/{len(rows)}  "
      f"<- these are the trades we'd place if LoL were live")
print("\nverdict hint: need would_fade>0 AND median depth >= bet for LoL LIVE to be worth it.")
