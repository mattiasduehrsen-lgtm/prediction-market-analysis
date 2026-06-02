"""Extract Polymarket CS2 head-to-head markets into a clean table for joining
to PandaScore. Parses team names from the `question` field, attaches the
resolved winner, game_start, condition_id, and the two outcome token_ids.

Output: cowork_snapshot/gamedata/polymarket_cs2_markets.parquet
"""
from __future__ import annotations
import re
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ES = ROOT / "cowork_snapshot" / "esports"
OUT = ROOT / "cowork_snapshot" / "gamedata"
OUT.mkdir(parents=True, exist_ok=True)

VS_RE = re.compile(r"\s+vs\.?\s+", re.IGNORECASE)
SINGLE_MAP_RE = re.compile(r"-game\d+|-map-?\d*\b|-map-", re.IGNORECASE)

def parse_teams(question: str):
    """'CS2: <event>: <A> vs. <B>' -> (A, B). Returns None if not H2H."""
    if not question:
        return None
    q = question.strip()
    # take the part after the last ': ' (drops 'CS2: <event>:')
    tail = q.split(": ")[-1]
    parts = VS_RE.split(tail)
    if len(parts) != 2:
        return None
    a, b = parts[0].strip(), parts[1].strip()
    if not a or not b or len(a) > 40 or len(b) > 40:
        return None
    return a, b

def main():
    m = pd.read_parquet(ES / "clob_esports_markets.parquet")
    res = pd.read_parquet(ES / "resolutions.parquet")[
        ["condition_id", "winning_outcome", "resolved"]]
    cs = m[m["slug"].fillna("").str.startswith("cs2-")].copy()
    cs = cs.merge(res, on="condition_id", how="left")

    rows = []
    for _, r in cs.iterrows():
        teams = parse_teams(r.get("question"))
        if not teams:
            continue
        a, b = teams
        toks = r.get("tokens")
        outs = {}
        try:
            for t in toks:
                if t.get("outcome") and t.get("token_id"):
                    outs[t["outcome"]] = t["token_id"]
        except TypeError:
            pass
        rows.append({
            "condition_id": r["condition_id"],
            "slug": r["slug"],
            "question": r.get("question"),
            "game_start": r.get("game_start"),
            "teamA": a, "teamB": b,
            "outcomes": list(outs.keys()),
            "tokenA": outs.get(a), "tokenB": outs.get(b),
            "winning_outcome": r.get("winning_outcome"),
            "resolved": r.get("resolved"),
            "is_single_map": bool(SINGLE_MAP_RE.search(r["slug"] or "")),
            "closed": r.get("closed"),
        })
    df = pd.DataFrame(rows)
    df["game_start"] = pd.to_datetime(df["game_start"], errors="coerce", utc=True)
    df.to_parquet(OUT / "polymarket_cs2_markets.parquet")
    print(f"CS2 H2H markets parsed: {len(df)}")
    print(f"  resolved: {df['resolved'].fillna(False).sum()}")
    print(f"  single-map: {df['is_single_map'].sum()}  series: {(~df['is_single_map']).sum()}")
    print(f"  with both token ids: {df['tokenA'].notna().__and__(df['tokenB'].notna()).sum()}")
    print(f"  date range: {df['game_start'].min()} .. {df['game_start'].max()}")
    print("\n  sample:")
    for _, r in df[~df['is_single_map']].head(6).iterrows():
        print(f"    {r['game_start']}  {r['teamA']} vs {r['teamB']}  -> winner={r['winning_outcome']}")

if __name__ == "__main__":
    main()
