"""
Join bo3.gg matches to PandaScore CS2 matches -> tier / tier_rank / LAN-ish
context features, keyed by PandaScore match_id.

Join strategy (no scraping, local dump only):
  1. Parse team names from the bo3 match slug ("team1-vs-team2-dd-mm-yyyy") --
     covers 99.6% of finished matches (teams.jsonl only covers ~15% of ids).
  2. Normalized-name pair + date (+/-1 day) join to PandaScore.
  3. Serie-level tier propagation: tier is EVENT metadata (bo3 publishes it on
     upcoming matches, so it is pre-match information). For PS matches that
     didn't join directly, inherit the majority tier of their (league, serie)
     if >=2 direct joins exist for that serie. This is not outcome leakage --
     the tier of an event is fixed and known before every match in it.

Outputs artifacts/cs2_bo3_join.parquet:
  match_id (PS), bo3_id, tier, tier_rank, bo3_rating, bo3_stars, tier_source
"""
import json, re, sys
from pathlib import Path
import numpy as np, pandas as pd
import pyarrow.parquet as pq

_REPO = Path(__file__).resolve().parents[2]
SNAP = _REPO / "cowork_snapshot" / "gamedata"
OUT = _REPO / "esports_model" / "artifacts"
OUT.mkdir(parents=True, exist_ok=True)

TIER_ORD = {"s": 4, "a": 3, "b": 2, "c": 1, "d": 0}


def norm(s):
    if not isinstance(s, str):
        return ""
    s = s.lower().strip()
    s = re.sub(r"\b(esports|esport|gaming|team|club|gg|e-sports)\b", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def load_bo3():
    rows = []
    with open(SNAP / "bo3" / "matches.jsonl") as f:
        for ln in f:
            d = json.loads(ln)
            if d.get("status") not in ("finished", "defwin"):
                continue
            m = re.match(r"^(.+)-vs-(.+)-(\d{2})-(\d{2})-(\d{4})$", d.get("slug") or "")
            if not m:
                continue
            rows.append({
                "bo3_id": d["id"], "n1": m.group(1), "n2": m.group(2),
                "start_date": d.get("start_date"), "tier": d.get("tier"),
                "tier_rank": d.get("tier_rank"), "bo3_rating": d.get("rating"),
                "bo3_stars": d.get("stars"),
            })
    b = pd.DataFrame(rows)
    b["start_date"] = pd.to_datetime(b["start_date"], utc=True)
    b["bn1"] = b.n1.map(norm); b["bn2"] = b.n2.map(norm)
    b = b[(b.bn1 != "") & (b.bn2 != "")]
    b["pair"] = [tuple(sorted(x)) for x in zip(b.bn1, b.bn2)]
    b["date"] = b.start_date.dt.date
    return b


def main():
    b = load_bo3()
    ps = pq.read_table(SNAP / "pandascore" / "cs2_matches.parquet").to_pandas()
    ps["begin_at"] = pd.to_datetime(ps.begin_at, utc=True)
    ps["pair"] = [tuple(sorted((norm(a), norm(c)))) for a, c in zip(ps.teamA_name, ps.teamB_name)]
    ps["date"] = ps.begin_at.dt.date

    idx = {}
    for r in b.itertuples(index=False):
        idx.setdefault(r.pair, []).append(r)

    one = pd.Timedelta(days=1).to_pytimedelta()
    used = set()
    recs = []
    for r in ps.itertuples(index=False):
        hit = None
        for d in (r.date, r.date - one, r.date + one):
            for x in idx.get(r.pair, []):
                if x.date == d and x.bo3_id not in used:
                    hit = x; break
            if hit: break
        if hit is None:
            continue
        used.add(hit.bo3_id)
        recs.append({"match_id": r.match_id, "bo3_id": hit.bo3_id, "tier": hit.tier,
                     "tier_rank": hit.tier_rank, "bo3_rating": hit.bo3_rating,
                     "bo3_stars": hit.bo3_stars, "tier_source": "direct"})
    j = pd.DataFrame(recs)
    print(f"direct join: {len(j):,} / {len(ps):,} PS matches ({len(j)/len(ps):.1%})")

    # ---- serie-level propagation ----
    meta = ps[["match_id", "league", "serie", "tournament"]].copy()
    j2 = j.merge(meta, on="match_id")
    j2["tord"] = j2.tier.map(TIER_ORD)
    grp = j2.groupby(["league", "serie"]).agg(
        n=("tier", "size"),
        tier_mode=("tier", lambda s: s.mode().iloc[0]),
        agree=("tier", lambda s: (s == s.mode().iloc[0]).mean()),
    ).reset_index()
    grp = grp[(grp.n >= 2) & (grp.agree >= 0.8)]
    serie_tier = {(r.league, r.serie): r.tier_mode for r in grp.itertuples(index=False)}

    joined_ids = set(j.match_id)
    prop = []
    for r in ps.itertuples(index=False):
        if r.match_id in joined_ids:
            continue
        t = serie_tier.get((r.league, r.serie))
        if t is not None:
            prop.append({"match_id": r.match_id, "bo3_id": np.nan, "tier": t,
                         "tier_rank": np.nan, "bo3_rating": np.nan,
                         "bo3_stars": np.nan, "tier_source": "serie"})
    out = pd.concat([j, pd.DataFrame(prop)], ignore_index=True)
    out["tier_ord"] = out.tier.map(TIER_ORD)
    out.to_parquet(OUT / "cs2_bo3_join.parquet", index=False)
    print(f"with serie propagation: {len(out):,} / {len(ps):,} ({len(out)/len(ps):.1%})")
    rec = ps[ps.begin_at >= pd.Timestamp("2025-09-18", tz="UTC")]
    cov = rec.match_id.isin(set(out.match_id)).mean()
    print(f"coverage in recent (OOS) window: {cov:.1%} of {len(rec):,}")
    print(out.tier.value_counts().to_string())


if __name__ == "__main__":
    main()
