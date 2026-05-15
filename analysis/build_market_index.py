"""
Paginates ALL Polymarket markets from gamma-api into a local index, then
filters to esports based on slug + tag patterns.

Output:
  cowork_snapshot/esports/all_markets.parquet  — every market (slug, question, tokens, tags, dates)
  cowork_snapshot/esports/esports_markets.parquet — filtered to esports
  cowork_snapshot/esports/token_to_market.json — token_id -> market_id lookup

Run:
  .venv\\Scripts\\python.exe analysis/build_market_index.py
"""
import json, os, time
from pathlib import Path

import requests
import pandas as pd

OUT_DIR = Path(__file__).resolve().parents[1] / "cowork_snapshot" / "esports"
OUT_DIR.mkdir(parents=True, exist_ok=True)

GAMMA = "https://gamma-api.polymarket.com"

# Esports keywords — slugs containing any of these get flagged
ESPORTS_KW = {
    "cs2","csgo","counter-strike","counterstrike",
    "dota","dota-2","dota2",
    "league-of-legends","league of legends","-lol-","-lec-","-lck-","-lpl-","-msi-","worlds-",
    "valorant","vct","vct-",
    "rocket-league","rlcs",
    "starcraft","sc2",
    "fortnite",
    "overwatch","ow2","owl",
    "apex-legends","apex legends",
    "call-of-duty","cod-","callofduty","cdl-",
    "esl-pro","iem-","epl-","blast-","major-","dreamhack",
    "esports","gaming-tournament",
    "g2","fnatic","navi","faze","heroic","mibr","liquid","cloud9","tsm","100thieves",
    "evilgeniuses","spirit-","vitality-","gentlemates","virtus-pro","heroic-",
    "t1-","gen-g","dwg","kt-rolster","sk-telecom",
    "sentinels","loud-","drx-","paper-rex","fnatic-",
}

def looks_esports(slug, question, tag_labels):
    text = (str(slug) + " " + str(question)).lower()
    for kw in ESPORTS_KW:
        if kw in text:
            return True, kw
    for t in tag_labels:
        tl = str(t).lower()
        if any(kw in tl for kw in ("esports","gaming","cs2","dota","valorant","league of legends","rocket league","overwatch","starcraft","call of duty")):
            return True, "tag:" + tl
    return False, None


def main():
    page_size = 100  # gamma-api hard caps at 100
    offset = 0
    rows = []
    print("Paginating gamma-api /markets (incl. closed) ...")
    t0 = time.time()
    seen_slugs = set()
    consecutive_empty = 0
    while True:
        r = requests.get(f"{GAMMA}/markets",
                         params={"limit": page_size, "offset": offset, "closed": "true"},
                         timeout=30)
        if r.status_code != 200:
            print(f"  HTTP {r.status_code} at offset {offset}, stopping")
            break
        page = r.json()
        if not page:
            consecutive_empty += 1
            if consecutive_empty >= 3:
                break
            offset += page_size
            continue
        consecutive_empty = 0
        new_in_page = 0
        for m in page:
            s = m.get("slug") or ""
            if s in seen_slugs:
                continue
            seen_slugs.add(s)
            new_in_page += 1
            tags = m.get("tags") or []
            tag_labels = [t.get("label") if isinstance(t, dict) else str(t) for t in tags]
            try:
                tok_ids = json.loads(m.get("clobTokenIds") or "[]")
            except Exception:
                tok_ids = []
            try:
                outcomes = json.loads(m.get("outcomes") or "[]")
            except Exception:
                outcomes = []
            try:
                outcome_prices = json.loads(m.get("outcomePrices") or "[]")
            except Exception:
                outcome_prices = []
            rows.append({
                "id":            m.get("id"),
                "slug":          m.get("slug") or "",
                "question":      m.get("question") or "",
                "condition_id":  m.get("conditionId") or "",
                "neg_risk":      bool(m.get("negRisk")),
                "active":        bool(m.get("active")),
                "closed":        bool(m.get("closed")),
                "archived":      bool(m.get("archived")),
                "end_date":      m.get("endDate") or m.get("end_date_iso") or "",
                "game_start":    m.get("gameStartTime") or "",
                "tokens":        tok_ids,
                "outcomes":      outcomes,
                "outcome_prices": outcome_prices,
                "tag_labels":    tag_labels,
                "tag_count":     len(tag_labels),
                "volume":        float(m.get("volume") or m.get("volumeNum") or 0),
                "liquidity":     float(m.get("liquidity") or m.get("liquidityNum") or 0),
            })
        offset += page_size
        if offset % 5000 == 0:
            print(f"  offset={offset:>7}  new_in_page={new_in_page}  total={len(rows)}  elapsed={time.time()-t0:.0f}s")
        if len(rows) > 200000:
            print(f"  (cap at 200k markets — stopping)")
            break

    print(f"\nTotal markets pulled: {len(rows)}")

    df = pd.DataFrame(rows)
    # save full index
    df.to_parquet(OUT_DIR / "all_markets.parquet", index=False)
    print(f"Saved all markets: {OUT_DIR / 'all_markets.parquet'}")

    # filter to esports
    df["es_match"] = df.apply(
        lambda r: looks_esports(r["slug"], r["question"], r["tag_labels"]), axis=1
    )
    df["is_esports"] = df["es_match"].apply(lambda x: x[0])
    df["es_keyword"] = df["es_match"].apply(lambda x: x[1] or "")
    df = df.drop(columns=["es_match"])

    es = df[df["is_esports"]].copy()
    print(f"\nEsports markets: {len(es)}")
    print("Top 10 keywords matched:")
    print(es["es_keyword"].value_counts().head(10).to_string())
    es.to_parquet(OUT_DIR / "esports_markets.parquet", index=False)

    # build token -> market_id index
    tok2mkt = {}
    for _, r in es.iterrows():
        for t in r["tokens"]:
            tok2mkt[str(t)] = r["id"]
    (OUT_DIR / "token_to_market.json").write_text(
        json.dumps(tok2mkt), encoding="utf-8"
    )
    print(f"Token index: {len(tok2mkt)} esports tokens -> {len(es)} markets")
    print(f"\nSample esports markets:")
    for _, r in es.sample(min(8, len(es))).iterrows():
        print(f"  [{r['es_keyword']:<25}] {r['slug'][:70]}")


if __name__ == "__main__":
    main()
