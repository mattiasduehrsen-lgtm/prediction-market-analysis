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

print("="*72); print(" 1) LoL MARKET COVERAGE  (watch for Valorant 'league' contamination)")
df = pd.read_parquet(ES, columns=["slug","tokens","closed","archived","game_start"])
def is_valorant(s): s=s.lower(); return ("vct" in s or "valorant" in s)
# TRUE LoL: lol- prefix, league-of-legends, or a LoL-specific league tag — NOT valorant
def is_true_lol(s):
    s=s.lower()
    if is_valorant(s): return False
    return ("lol-" in s or "league-of-legends" in s
            or any(t in s for t in ["-lck","-lpl","-lcs","-lec","lol-worlds","lol-msi"]))
broad = df[df["slug"].str.contains("league|lol|lck|lpl|lec|lcs|worlds|msi", case=False, na=False)]
val = broad[broad["slug"].apply(is_valorant)]
truelol = df[df["slug"].apply(is_true_lol)].copy()
print(f"  broad 'league/lol/...' matches={len(broad)}  of which Valorant(VCT)={len(val)}  TRUE-LoL={len(truelol)}")
op = truelol[(~truelol["closed"].astype(bool)) & (~truelol["archived"].astype(bool))]
def n_team_tokens(toks):
    toks = list(toks) if toks is not None else []
    return len([t for t in toks if t.get("outcome")])
# head-to-head = exactly 2 outcomes and not a 'will-...-win' futures slug
op_h2h = op[op["tokens"].apply(lambda t: n_team_tokens(t)==2) & ~op["slug"].str.startswith("will-")]
op_series = op_h2h[~op_h2h["slug"].apply(lambda s: bool(SINGLE_MAP_RE.search(s or "")))]
print(f"  TRUE-LoL: total={len(truelol)} open={len(op)} open_head2head={len(op_h2h)} open_series_moneyline={len(op_series)}")
print("  recent TRUE-LoL slugs:")
for s in truelol["slug"].tail(12): print("     ", s)
if len(truelol)==0:
    print("  >>> NO real LoL markets in the index at all.")
# CRITICAL: across the FULL archive (open+closed), are there ANY 2-team head-to-head
# match markets to fade? (futures like 'will-...-win' are not fadeable head-to-head)
all_h2h = truelol[truelol["tokens"].apply(lambda t: n_team_tokens(t)==2)
                  & ~truelol["slug"].str.startswith("will-")]
print(f"\n  >>> TRUE-LoL 2-team HEAD-TO-HEAD across ENTIRE archive (open+closed): {len(all_h2h)}")
for s in all_h2h["slug"].tail(15): print("       h2h:", s)
# how many futures vs other
fut = truelol[truelol["slug"].str.startswith("will-")]
print(f"  futures ('will-...'): {len(fut)} / {len(truelol)} true-LoL markets")

print("="*72); print(" 1b) GAME-LABEL mismatch (target selector uses slug.split('-')[0])")
firsttok = truelol["slug"].str.split("-").str[0].value_counts()
print("  first-token (=target 'game' label) for TRUE-LoL markets:")
for tok,c in firsttok.head(10).items(): print(f"     {tok!r}: {c}")
print("  -> target selector only keeps game in ['cs2','league']; LoL H2H markets")
print("     that start with 'lol'/'arch' are NOT labeled 'league' -> excluded.")
h2h_tok = all_h2h["slug"].str.split("-").str[0].value_counts()
print("  first-token for LoL HEAD-TO-HEAD markets specifically:")
for tok,c in h2h_tok.head(8).items(): print(f"     {tok!r}: {c}")

print("="*72); print(" 2) TEAM MATCHING on REAL LoL market outcomes (the key metric)")
mod = M.CS2Model(game="lol")
print(f"  lol model teams={len(mod.elo_by_id)}  names indexed={len(mod.name_to_id)}")
ok=unmatched=lowgames=0; ex_unmatched=[]; ex_low=[]
checked=0
# none open, so measure match rate on the historical head-to-head markets (real LoL matches)
for _,r in all_h2h.iterrows():
    toks = list(r["tokens"]) if r["tokens"] is not None else []
    outs=[t.get("outcome") for t in toks if t.get("outcome")]
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
