import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cs2_model import CS2Model, norm
m=CS2Model()
print("elo teams loaded:", len(m.elo_by_id), "name keys:", len(m.name_to_id))
for t in ["Team Spirit","9z Team","Spirit","9z","9Z Team","Team Spirit "]:
    r=m.match_team(t)
    print(f"  match_team({t!r}) norm={norm(t)!r} -> {r}")
print("\npredict Team Spirit vs 9z Team:", m.predict("Team Spirit","9z Team"))
# what name keys contain spirit / 9z?
hits=[k for k in m.name_to_id if "spirit" in k or "9z" in k]
print("\nname keys containing spirit/9z:", hits[:20])
