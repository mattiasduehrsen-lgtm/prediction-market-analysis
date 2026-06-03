"""Does combining the FADE signal with the ELO MODEL beat either alone?

Three strategies compared on historical CS2 series markets:
  A. model-only   : bet the side the model thinks is underpriced (|edge|>thr)
  B. fade-only    : bet the opposite side of what target 'loser' wallets bought
  C. fade+model   : fade, but ONLY when the model also likes the fade side

If C > A, the fade adds value as a model filter (or vice-versa). If C ~= A,
the model is the edge and the fade is along for the ride.
"""
from __future__ import annotations
import glob, json
from pathlib import Path
from collections import defaultdict
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ES = ROOT / "cowork_snapshot" / "esports"
GD = ROOT / "cowork_snapshot" / "gamedata"

def main():
    j = pd.read_parquet(GD / "feasibility_joined.parquet")  # cid, teamA/B, model_pA, market_pA, A_won
    j = j.set_index("cid")
    target_path = ES / "fade_targets_paper.json"
    targets = set(w.lower() for w in json.loads(target_path.read_text())["target_wallets"])
    cids = set(j.index)
    print(f"joined markets: {len(cids)}  target wallets: {len(targets)}")

    # Reconstruct: for each market, which outcome did target wallets BUY (by count)?
    buys = defaultdict(lambda: defaultdict(int))  # cid -> outcome -> n target buys
    shards = sorted(glob.glob(str(ES / "scrape" / "shards" / "*.parquet")))
    for i, sh in enumerate(shards):
        try:
            d = pd.read_parquet(sh, columns=["conditionId", "outcome", "side", "proxyWallet"])
        except Exception:
            continue
        d = d[d["conditionId"].isin(cids)]
        if not len(d):
            continue
        d = d[(d["side"].str.upper() == "BUY")]
        d["proxyWallet"] = d["proxyWallet"].astype(str).str.lower()
        d = d[d["proxyWallet"].isin(targets)]
        for r in d.itertuples(index=False):
            buys[r.conditionId][r.outcome] += 1
        if (i+1) % 200 == 0:
            print(f"  {i+1}/{len(shards)} shards, {len(buys)} markets w/ target activity")
    print(f"markets with target-wallet buys: {len(buys)}")

    # Build per-market record with fade side
    rows = []
    for cid, outs in buys.items():
        if cid not in j.index: continue
        r = j.loc[cid]
        # which side did targets favour (more buys)?
        teamA, teamB = r.teamA, r.teamB
        a_buys, b_buys = outs.get(teamA, 0), outs.get(teamB, 0)
        if a_buys == b_buys:
            continue
        target_side = teamA if a_buys > b_buys else teamB
        fade_side = teamB if target_side == teamA else teamA   # we bet opposite
        # model & market prob for the fade side
        model_fade = r.model_pA if fade_side == teamA else 1 - r.model_pA
        market_fade = r.market_pA if fade_side == teamA else 1 - r.market_pA
        fade_won = int(r.A_won) if fade_side == teamA else 1 - int(r.A_won)
        # model preferred side (for model-only on this subset)
        model_edge_A = r.model_pA - r.market_pA
        rows.append({"cid": cid, "model_pA": r.model_pA, "market_pA": r.market_pA,
                     "A_won": int(r.A_won), "fade_side_isA": fade_side == teamA,
                     "model_fade": model_fade, "market_fade": market_fade,
                     "fade_won": fade_won, "model_edge_A": model_edge_A,
                     "n_target": a_buys + b_buys})
    df = pd.DataFrame(rows)
    print(f"\nmarkets with a clear target side: {len(df)}")
    if not len(df):
        return

    def roi(bets_price_won):
        cost = pnl = 0.0; n = w = 0
        for price, won in bets_price_won:
            cost += price; pnl += (1 - price) if won else -price; n += 1; w += won
        return n, (w/n*100 if n else 0), (pnl/cost*100 if cost else 0)

    print("\n  strategy comparison (on markets WITH target activity):")
    print(f"    {'strategy':<26}{'thr':>5}{'bets':>6}{'WR':>6}{'ROI':>8}")
    for thr in [0.0, 0.10, 0.15]:
        # A. model-only: bet model side when |edge|>thr
        a = [(r.market_pA if r.model_edge_A > 0 else 1-r.market_pA,
              r.A_won if r.model_edge_A > 0 else 1-r.A_won)
             for r in df.itertuples(index=False) if abs(r.model_edge_A) > thr]
        # B. fade-only: bet fade side (only meaningful at thr=0)
        b = [(r.market_fade, r.fade_won) for r in df.itertuples(index=False)]
        # C. fade+model: fade only when model likes the fade side by > thr
        c = [(r.market_fade, r.fade_won) for r in df.itertuples(index=False)
             if (r.model_fade - r.market_fade) > thr]
        for name, bets in [("A model-only", a), ("C fade+model", c)] + ([("B fade-only", b)] if thr==0 else []):
            n, wr, rr = roi(bets)
            print(f"    {name:<26}{thr:>5.2f}{n:>6}{wr:>5.0f}%{rr:>+7.1f}%")

if __name__ == "__main__":
    main()
