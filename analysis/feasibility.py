"""FEASIBILITY: does an Elo model beat the Polymarket CS2 price?

Joins:
  - PandaScore Elo predictions (cs2_elo_history)  [model probability]
  - Polymarket series markets (polymarket_cs2_markets)  [outcome truth]
  - Pre-match prices (prematch_prices)  [market implied probability]
Join key: team names (normalized) + match date within +/- 2 days.

Then simulates: when |model_prob - market_prob| > edge threshold, bet the side
the model favours, buying at the market price, settling on the actual outcome.
Reports ROI by edge bucket. This is the gate for the whole pivot.
"""
from __future__ import annotations
import re
from pathlib import Path
from collections import defaultdict
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
GD = ROOT / "cowork_snapshot" / "gamedata"

def norm(s):
    """Normalize a team name for matching. Strips (BO3)/(BO1) and other
    parentheticals, 'ex-' prefixes, and generic org suffixes — but KEEPS
    distinguishing words like 'academy'/'future'/'youngsters' so a junior
    team isn't wrongly matched to its main roster."""
    if not isinstance(s, str): return ""
    s = s.lower()
    s = re.sub(r"\(.*?\)", " ", s)          # drop (BO3), (+8.5), etc.
    s = s.replace("ex-", " ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\bbo\d\b", " ", s)         # stray 'bo3' tokens
    for junk in [" esports", " e sports", " gaming", " team ", " clan "]:
        s = s.replace(junk, " ")
    return re.sub(r"\s+", " ", s).strip()

def is_handicap_market(a, b):
    blob = f"{a} {b}".lower()
    return ("handicap" in blob or "rounds" in blob
            or re.search(r"[+-]\d+\.?\d*\)?$", a or "") is not None
            or re.search(r"[+-]\d+\.?\d*\)?$", b or "") is not None)

def main():
    elo = pd.read_parquet(GD / "pandascore" / "cs2_elo_history.parquet")
    mk = pd.read_parquet(GD / "polymarket_cs2_markets.parquet")
    px = pd.read_parquet(GD / "prematch_prices.parquet")

    mk = mk[(~mk["is_single_map"]) & mk["resolved"].fillna(False)
            & mk["winning_outcome"].notna() & mk["game_start"].notna()].copy()
    elo = elo.copy()
    elo["nA"] = elo["teamA_name"].map(norm); elo["nB"] = elo["teamB_name"].map(norm)
    elo["date"] = pd.to_datetime(elo["begin_at"], utc=True).dt.floor("D")
    # index elo matches by calendar day for windowed lookup
    elo_by_day = defaultdict(list)
    for r in elo.itertuples(index=False):
        elo_by_day[r.date.toordinal()].append(r)

    def teq(x, y):
        return bool(x) and bool(y) and (x == y or (len(x) >= 4 and len(y) >= 4 and (x in y or y in x)))

    # market implied prob for teamA = price of teamA outcome
    px_by = {(r.condition_id, r.outcome): r.price for r in px.itertuples(index=False)}

    joined = []
    n_handicap = 0
    for r in mk.itertuples(index=False):
        if is_handicap_market(r.teamA, r.teamB):
            n_handicap += 1
            continue
        nA, nB = norm(r.teamA), norm(r.teamB)
        gd = pd.Timestamp(r.game_start).floor("D")
        god = gd.toordinal()
        # scan elo matches within +/- 2 days, fuzzy-match the team pair
        best = None; best_gap = 99
        for dd in range(-2, 3):
            for c in elo_by_day.get(god + dd, []):
                if (teq(nA, c.nA) and teq(nB, c.nB)) or (teq(nA, c.nB) and teq(nB, c.nA)):
                    if abs(dd) < best_gap:
                        best = c; best_gap = abs(dd)
        if best is None:
            continue
        # model prob for THIS market's teamA (orient to which side matched)
        if teq(nA, best.nA):
            model_pA = best.pred_pA
        else:
            model_pA = 1 - best.pred_pA
        # require both teams to have reliable Elo history
        if min(best.gamesA, best.gamesB) < 10:
            continue
        mpx_A = px_by.get((r.condition_id, r.teamA))
        mpx_B = px_by.get((r.condition_id, r.teamB))
        # market implied prob for A: prefer A's own price; else 1 - B price
        if mpx_A is not None:
            market_pA = mpx_A
        elif mpx_B is not None:
            market_pA = 1 - mpx_B
        else:
            continue
        if not (0.02 < market_pA < 0.98):
            continue
        A_won = 1 if r.winning_outcome == r.teamA else 0
        joined.append({"cid": r.condition_id, "teamA": r.teamA, "teamB": r.teamB,
                       "model_pA": model_pA, "market_pA": market_pA, "A_won": A_won,
                       "edge": model_pA - market_pA,
                       "ts_start": pd.Timestamp(r.game_start).value})
    j = pd.DataFrame(joined)
    print(f"handicap markets skipped: {n_handicap}")
    print(f"joined markets (model+market+outcome): {len(j)}")
    if not len(j):
        print("no joined rows — check team-name matching / data coverage")
        return
    j.to_parquet(GD / "feasibility_joined.parquet")

    # Model accuracy vs market accuracy on these matches
    macc = ((j["model_pA"] > 0.5).astype(int) == j["A_won"]).mean()
    kacc = ((j["market_pA"] > 0.5).astype(int) == j["A_won"]).mean()
    print(f"  model accuracy: {macc*100:.1f}%   market accuracy: {kacc*100:.1f}%")
    print(f"  model Brier: {((j['model_pA']-j['A_won'])**2).mean():.4f}   "
          f"market Brier: {((j['market_pA']-j['A_won'])**2).mean():.4f}")

    # Simulate betting when model disagrees with market by > threshold.
    # We bet the side the model favours, buy at market price, win $1 if right.
    print("\n  edge-threshold sweep (bet the model's side when |edge|>thr):")
    print(f"    {'thr':>5} {'bets':>5} {'WR':>6} {'ROI':>8}")
    for thr in [0.0, 0.05, 0.10, 0.15, 0.20]:
        bets = j[j["edge"].abs() > thr]
        if not len(bets):
            print(f"    {thr:>5.2f}    0"); continue
        pnl = 0.0; cost = 0.0; wins = 0
        for r in bets.itertuples(index=False):
            if r.edge > 0:   # model likes A more than market -> buy A at market_pA
                price = r.market_pA; won = r.A_won
            else:            # model likes B -> buy B at (1-market_pA)
                price = 1 - r.market_pA; won = 1 - r.A_won
            cost += price
            pnl += (1 - price) if won else (-price)
            wins += won
        roi = pnl / cost * 100 if cost else 0
        print(f"    {thr:>5.2f} {len(bets):>5} {wins/len(bets)*100:>5.0f}% {roi:>+7.1f}%")
    print("\n  (positive ROI at higher thresholds = model finds real market mispricings)")

    # ── RIGOR 1: execution friction (we pay SLIP more per share) ─────────────
    def sim(bets, slip):
        pnl = cost = 0.0; wins = 0
        for r in bets.itertuples(index=False):
            if r.edge > 0: price = min(0.99, r.market_pA + slip); won = r.A_won
            else:          price = min(0.99, (1 - r.market_pA) + slip); won = 1 - r.A_won
            cost += price; pnl += (1 - price) if won else (-price); wins += won
        return (pnl / cost * 100 if cost else 0), len(bets)
    print("\n  RIGOR 1 — with 2c slippage haircut:")
    for thr in [0.05, 0.10, 0.15, 0.20]:
        bets = j[j["edge"].abs() > thr]
        roi, n = sim(bets, 0.02)
        print(f"    thr {thr:.2f}  n={n:>4}  ROI {roi:>+6.1f}%")

    # ── RIGOR 2: out-of-sample time split (does edge persist on later data?) ─
    if "game_start" not in j.columns:
        pass
    js = j.sort_values("ts_start") if "ts_start" in j.columns else j
    cut = int(len(js) * 0.6)
    train, test = js.iloc[:cut], js.iloc[cut:]
    print(f"\n  RIGOR 2 — out-of-sample time split (train={len(train)}, test={len(test)}):")
    for label, d in [("TRAIN", train), ("TEST (later, unseen)", test)]:
        for thr in [0.10]:
            bets = d[d["edge"].abs() > thr]
            roi, n = sim(bets, 0.02)
            print(f"    {label:<22} thr {thr:.2f}  n={n:>4}  ROI(2c slip) {roi:>+6.1f}%")

if __name__ == "__main__":
    main()
