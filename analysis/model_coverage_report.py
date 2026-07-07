"""Model-state coverage report for GRID-era markets (2026-07-06).

The GRID re-fit found only 54/67 July series markets got a model price — every
unpriced market is an R1 eval that never happens, stretching the road to the
pre-registered n=150. This reports exactly which teams the Predictor cannot
resolve, with candidate state rows for alias review.

DO NOT auto-apply suggestions: a wrong alias prices the WRONG TEAM confidently
and poisons the R1 stream (v1.57's fuzzy-matcher lesson). Review by hand, then
add vetted entries to esports_model/artifacts/{game}_aliases.json.

Run: .venv\\Scripts\\python.exe -u analysis/model_coverage_report.py
"""
import re, sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "analysis"))
sys.path.insert(0, str(ROOT / "esports_model" / "src"))

from tape_backfill import universe          # GRID-era series markets
from predict import Predictor, _norm


def suggest(state, name, k=3):
    """Token-overlap candidates from the state for a missed market name."""
    n = _norm(name)
    toks = set(re.findall(r"[a-z0-9]+", (name or "").lower()))
    scored = []
    for key, row in state.items():
        rt = set(re.findall(r"[a-z0-9]+", (row.name or "").lower()))
        inter = toks & rt
        score = 0.0
        if n and (n in key or key in n):
            score += min(len(key), len(n)) / max(len(key), len(n))
        if inter:
            score += len(inter) / max(len(toks | rt), 1)
        if score > 0.15:
            scored.append((score, row.name, int(row.games)))
    return sorted(scored, reverse=True)[:k]


def main():
    uni = universe()
    preds = {g: Predictor(g) for g in ("cs2", "lol")}
    missed = defaultdict(Counter)     # game -> team -> n markets
    stats = Counter()
    for r in uni.itertuples(index=False):
        p = preds[r.game]
        a, b = r.outcomes
        ra, rb = p._row(a), p._row(b)
        stats[(r.game, "markets")] += 1
        if ra is not None and rb is not None:
            stats[(r.game, "priced")] += 1
        for team, row in ((a, ra), (b, rb)):
            if row is None:
                missed[r.game][team] += 1

    for g in ("cs2", "lol"):
        n, ok = stats[(g, "markets")], stats[(g, "priced")]
        print(f"\n[{g}] GRID-era series markets: {n}, fully priced: {ok} "
              f"({ok / n:.0%})" if n else f"\n[{g}] no markets")
        if not missed[g]:
            continue
        print(f"  unresolved teams ({len(missed[g])}):")
        for team, cnt in missed[g].most_common():
            cands = suggest(preds[g].state, team)
            cs = "; ".join(f"{nm} ({gm}g, {sc:.2f})" for sc, nm, gm in cands) or "-"
            print(f"    {team:32} x{cnt:<3} candidates: {cs}")
    print("\nVetted aliases go in esports_model/artifacts/<game>_aliases.json "
          "({\"market name\": \"state canonical name\"}). Predictor hot-loads on init;"
          " bot picks up on restart.")


if __name__ == "__main__":
    main()
