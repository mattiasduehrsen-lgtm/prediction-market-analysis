import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cs2_inplay_bot as b
# math sanity
for P,W in [(0.55,2),(0.55,3),(0.70,2)]:
    p=b.invert(P,W)
    print(f"pre-series {P} Bo{2*W-1} -> single-map p={p:.3f}  check={b.series_prob(p,0,0,W):.3f}")
# post-map states (Bo3, p from 0.55)
p=b.invert(0.55,2)
print(f"Bo3 p={p:.3f}: after 1-0 -> {b.series_prob(p,1,0,2):.3f}, after 0-1 -> {b.series_prob(p,0,1,2):.3f}")
# live bo3 fetch
m=(b.bo3_get('matches',{'sort':'-start_date','page[limit]':30}) or {}).get('results') or []
live=[x for x in m if x.get('status') in ('live','current','running','started')]
print(f"\nbo3 reachable: {len(m)} recent matches, {len(live)} currently live")
for x in live[:5]:
    print(f"  LIVE bo{x.get('bo_type')} {x.get('slug','')[:45]} status={x.get('status')}")
