"""
Paginates the full CLOB /markets endpoint (much larger archive than gamma-api)
and builds a token_id -> market index. Then filters to esports by slug.

Output:
  cowork_snapshot/esports/clob_markets.parquet
  cowork_snapshot/esports/clob_token_to_market.json
"""
import base64, json, time
from pathlib import Path

import requests
import pandas as pd

OUT_DIR = Path(__file__).resolve().parents[1] / "cowork_snapshot" / "esports"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CLOB = "https://clob.polymarket.com"

# Tight esports keyword patterns — only patterns that ONLY appear in true esports slugs
ESPORTS_PATTERNS = [
    "csgo-","cs2-","-cs2","-csgo",
    "lol-worlds","lol-lcs","lol-lec","lol-lck","lol-lpl","lol-msi","-lol-",
    "dota-2","dota-international","-dota-",
    "valorant-","-vct-","valorant-champions",
    "rocket-league","-rlcs",
    "starcraft-","-sc2-",
    "overwatch-","ow2-","-owl-",
    "apex-legends","apex-",
    "call-of-duty","cdl-","-cdl-",
    "esl-pro","-iem-","blast-pro","blast-premier","blast-fall","blast-spring",
    "dreamhack-","ewc-","esports-world-cup",
    "fortnite-","pubg-",
    "league-of-legends",
]


def looks_esports(slug):
    if not slug:
        return False, None
    s = slug.lower()
    for pat in ESPORTS_PATTERNS:
        if pat in s:
            return True, pat
    return False, None


def main():
    cursor = ""
    rows = []
    t0 = time.time()
    page = 0
    while True:
        params = {}
        if cursor:
            params["next_cursor"] = cursor
        r = requests.get(f"{CLOB}/markets", params=params, timeout=30)
        if r.status_code != 200:
            print(f"HTTP {r.status_code} on page {page}, stopping")
            break
        j = r.json()
        data = j.get("data", [])
        if not data:
            break
        for m in data:
            tokens = []
            for t in (m.get("tokens") or []):
                tid = t.get("token_id") or t.get("tokenId") or ""
                outc = t.get("outcome") or ""
                if tid:
                    tokens.append({"token_id": str(tid), "outcome": outc})
            rows.append({
                "condition_id": m.get("condition_id") or "",
                "question_id":  m.get("question_id") or "",
                "slug":         m.get("market_slug") or "",
                "question":     m.get("question") or "",
                "active":       bool(m.get("active")),
                "closed":       bool(m.get("closed")),
                "archived":     bool(m.get("archived")),
                "end_date":     m.get("end_date_iso") or "",
                "game_start":   m.get("game_start_time") or "",
                "neg_risk":     bool(m.get("neg_risk")),
                "tokens":       tokens,
                "n_tokens":     len(tokens),
            })
        page += 1
        cursor = j.get("next_cursor", "")
        if not cursor or cursor == "LTE=":   # LTE= is the "end" sentinel
            break
        if page % 5 == 0:
            print(f"  page {page}: total markets={len(rows)} elapsed={time.time()-t0:.0f}s")
        if len(rows) > 500_000:
            print("  cap 500k — stopping")
            break

    print(f"\nTotal CLOB markets: {len(rows)}")
    df = pd.DataFrame(rows)
    df.to_parquet(OUT_DIR / "clob_markets.parquet", index=False)

    # Esports filter
    df["es_match"]    = df["slug"].apply(looks_esports)
    df["is_esports"]  = df["es_match"].apply(lambda x: x[0])
    df["es_keyword"]  = df["es_match"].apply(lambda x: x[1] or "")
    es = df[df["is_esports"]].copy().drop(columns=["es_match"])
    es.to_parquet(OUT_DIR / "clob_esports_markets.parquet", index=False)
    print(f"\nEsports markets: {len(es)}")
    print("Keyword distribution:")
    print(es["es_keyword"].value_counts().to_string())

    # Build token -> condition_id index
    tok2cond = {}
    tok2slug = {}
    for _, r in es.iterrows():
        for t in r["tokens"]:
            tok2cond[t["token_id"]] = r["condition_id"]
            tok2slug[t["token_id"]] = r["slug"]
    (OUT_DIR / "clob_token_to_market.json").write_text(json.dumps({
        "token_to_condition": tok2cond,
        "token_to_slug":      tok2slug,
    }), encoding="utf-8")
    print(f"\nToken index: {len(tok2cond)} esports tokens")

    # Sample
    print("\nSample esports slugs:")
    for s in es["slug"].sample(min(15, len(es))).tolist():
        print(f"  {s[:100]}")


if __name__ == "__main__":
    main()
