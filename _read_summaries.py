"""Read all sport_recon/summary.json files and print combined table."""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sport_dirs = sorted([d for d in (ROOT / "cowork_snapshot").iterdir()
                     if d.is_dir() and d.name.endswith("_recon")])

rows = []
for d in sport_dirs:
    f = d / "summary.json"
    if not f.exists():
        rows.append({"sport": d.name.replace("_recon",""), "verdict": "(no summary yet)"})
        continue
    try:
        s = json.loads(f.read_text(encoding="utf-8"))
        rows.append(s)
    except Exception as e:
        rows.append({"sport": d.name.replace("_recon",""), "verdict": f"(error: {e})"})

# Sort by qualifying wallets desc
rows.sort(key=lambda r: -(r.get("qualifying_wallets") or 0))

print(f"\n{'sport':>10} {'markets':>9} {'trades':>10} {'wallets':>9} "
      f"{'qual':>6} {'top_loss':>13}  verdict")
print("-" * 88)
for r in rows:
    print(f"{r.get('sport','?'):>10} {r.get('in_window_markets',0):>9} "
          f"{r.get('trades_in_window',0):>10,} {r.get('unique_wallets',0):>9,} "
          f"{r.get('qualifying_wallets',0):>6} "
          f"${r.get('top_loser_pnl_usd', 0):>11,.0f}  "
          f"{r.get('verdict','?')}")
