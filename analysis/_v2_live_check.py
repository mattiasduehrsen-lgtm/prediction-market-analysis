"""Pre-restart verification that v1.57's full chain works ON THE LAPTOP:
v2 Predictor loads (ensemble), predicts sanely, bet_ok fires, tier index resolves
a real upcoming CS2 matchup. Read-only."""
import sys
from pathlib import Path
ROOT = Path(r"C:\Users\matti\Desktop\prediction-market-analysis")
sys.path.insert(0, str(ROOT / "esports_model" / "src"))
import pandas as pd
from predict import Predictor

p = Predictor("cs2")
r = p.predict("Vitality", "NRG")
print(f"v2 predict: ok={r['ok']} p={r.get('model_prob_a')} (ensemble)")
print(f"bet_ok(0.15,2)={p.bet_ok(0.15,2)[0]}  bet_ok(0.35,None)={p.bet_ok(0.35,None)[0]}  "
      f"bet_ok(0.35,4)={p.bet_ok(0.35,4)[0]}  bet_ok(0.35,2)={p.bet_ok(0.35,2)[0]}")
pl = Predictor("lol")
print(f"lol v2: ok={pl.predict('T1','Gen.G')['ok']}")

ti = pd.read_parquet(ROOT / "cowork_snapshot" / "gamedata" / "bo3" / "tier_index.parquet")
future = ti[ti.date >= "2026-07-02"]
print(f"tier index: {len(ti):,} rows | future-dated: {len(future):,}")
print(future.head(3).to_string(index=False))
