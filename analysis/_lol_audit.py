"""LoL readiness audit — replays every CS2 problem class against real LoL data.
Run on the laptop (needs lol Elo + markets parquet). Read-only."""
import re, json, sys
from collections import Counter, defaultdict
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cs2_model as M

ROOT = Path(r"C:\Users\matti\Desktop\prediction-market-analysis")
ES = ROOT / "cowork_snapshot" / "esports" / "clob_esports_markets.parquet"

# build_clob_index LoL patterns + the bot's single-map regex
LOL_PATTERNS = ["lol-worlds","lol-lcs","lol-lec","lol-lck","lol-lpl","lol-msi","-lol-","league-of-legends"]
SINGLE_MAP_RE = re.compile(r"-game\d+|-map-?\d*\b|-map-", re.I)

print("="*72); print(" 1) LoL MARKET COVERAGE")
df = pd.read_parquet(ES, columns=["slug","tokens","closed","archived","game_start"])
lol = df[df["slug"].str.contains("league-|lol-|-lol|lck|lpl|lec|lcs|worlds|msi", case=False, na=False)].copy()
op = lol[(~lol["closed"].astype(bool)) & (~lol["archived"].astype(bool))]
print(f"  LoL markets total={len(lol)}  open={len(op)}")
# how many match build_clob_index patterns (i.e. would even be INDEXED)?
def matches_index(s):
    s=s.lower(); return any(p in s for p in LOL_PATTERNS)
covered = lol["slug"].apply(matches_index).sum()
print(f"  slugs matching build_clob_index LoL patterns: {covered}/{len(lol)}"
      f"  (unmatched = markets we'd MISS at index time)")
# series vs single-map among open
op_series = op[~op["slug"].apply(lambda s: bool(SINGLE_MAP_RE.search(s or "")))]
print(f"  open: series(moneyline)={len(op_series)}  single-map/prop={len(op)-len(op_series)}")
print("  recent LoL slugs:")
for s in lol["slug"].tail(12): print("     ", s)

print("="*72); print(" 2) TEAM MATCHING on REAL LoL market outcomes (the key metric)")
mod = M.CS2Model(game="lol")
print(f"  lol model teams={len(mod.elo_by_id)}  names indexed={len(mod.name_to_id)}")
ok=unmatched=lowgames=0; ex_unmatched=[]; ex_low=[]
checked=0
for _,r in op_series.iterrows():
    outs=[t.get("outcome") for t in (r["tokens"] or []) if t.get("outcome")]
    if len(outs)!=2: continue
    checked+=1
    pred=mod.predict(outs[0],outs[1])
    if pred and pred.get("ok"): ok+=1
    elif pred and pred.get("reason")=="low_games":
        lowgames+=1;  ex_low.append((outs[0],outs[1],pred.get("gamesA"),pred.get("gamesB")))
    else:
        unmatched+=1; ex_unmatched.append((outs[0],outs[1]))
print(f"  open series markets checked={checked}: ok={ok} low_games={lowgames} unmatched={unmatched}")
for a,b in ex_unmatched[:10]: print(f"     UNMATCHED: {a!r} vs {b!r}")
for a,b,ga,gb in ex_low[:8]: print(f"     LOW_GAMES: {a!r}({ga}) vs {b!r}({gb})")

print("="*72); print(" 3) NAME-COLLISION class (the Falcons bug) on LoL")
# how many normalized names map to >1 team_id, and does higher-games win?
norm_to_ids=defaultdict(list)
for tid,nm in mod.id_to_name.items():
    n=M.norm(nm)
    if n: norm_to_ids[n].append(tid)
collisions={n:ids for n,ids in norm_to_ids.items() if len(set(ids))>1}
print(f"  normalized names with >1 team: {len(collisions)}")
for n,ids in list(collisions.items())[:10]:
    rows=sorted({tid for tid in ids}, key=lambda t: -mod.elo_by_id.get(t,(0,0))[1])
    chosen=mod.name_to_id.get(n)
    parts=[f"{mod.id_to_name.get(t)}({mod.elo_by_id.get(t,(0,0))[1]}g){'<-' if t==chosen else ''}" for t in rows]
    print(f"     {n!r}: "+", ".join(parts))

print("="*72); print(" 4) KNOWN CURRENT TOP TEAMS (rebrand / matching spot-check)")
for nm in ["T1","Gen.G","Hanwha Life Esports","Dplus KIA","KT Rolster","Bilibili Gaming",
           "JD Gaming","Top Esports","G2 Esports","Fnatic","Cloud9","FlyQuest",
           "Team Liquid","100 Thieves","Anyone's Legends","Weibo Gaming"]:
    p=mod.predict(nm,"T1")
    mt=mod.match_team(nm)
    tag = "OK" if mt else "UNMATCHED"
    g = mt[2] if mt else "-"
    print(f"     {nm:<24} -> {tag} games={g}")
