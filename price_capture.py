"""Price-capture logger — the infrastructure that unblocks three research avenues.

WHY (war-room 2026-07-01): prop-model backtests, series-vs-map consistency arb, and
the LoL edge validation are ALL blocked on the same missing data: nobody logs the
order book of esports markets over time (prematch_prices.parquet has 3 prop rows
total). This logs best bid/ask + depth for every OPEN esports market near its
game_start, every cycle, forever. In a week we have the backtest data no one else has.

Scope control: markets with game_start in [-6h, +48h] (bound the set), one CLOB
/book call per market (token A; token B's book is its mirror in a binary market).
Cycle budget caps requests; nearest-to-start markets are always captured, the rest
round-robin. Output: output/price_capture/prices_YYYYMMDD.jsonl

Run: .venv\\Scripts\\python.exe -u price_capture.py   (via watch_price_capture.bat)
"""
from __future__ import annotations
import json, re, time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent
MK = ROOT / "cowork_snapshot" / "esports" / "clob_esports_markets.parquet"
OUT_DIR = ROOT / "output" / "price_capture"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CYCLE_S = 60              # one pass per minute
MAX_BOOKS_PER_CYCLE = 150 # request budget (~2.5 req/s worst case)
WINDOW_PRE_H, WINDOW_POST_H = 48.0, 6.0   # game_start within [-6h, +48h from now]
RELOAD_MARKETS_S = 600    # re-read the markets parquet every 10 min
PROP = re.compile(r"-game\d|kill-over|first-blood|-map-|handicap|total-|-map\b", re.I)

S = requests.Session()


def load_universe():
    """Open esports markets near game_start -> list of dicts (soonest first)."""
    df = pd.read_parquet(MK, columns=["condition_id", "slug", "tokens",
                                      "game_start", "closed", "archived"])
    df = df[(~df["closed"].astype(bool)) & (~df["archived"].astype(bool))]
    df = df[df["slug"].str.contains("cs2-|csgo-|lol-|league-", case=False, na=False)]
    gs = pd.to_datetime(df["game_start"], errors="coerce", utc=True)
    now = pd.Timestamp.utcnow()
    m = df[(gs.notna())
           & (gs > now - pd.Timedelta(hours=WINDOW_POST_H))
           & (gs < now + pd.Timedelta(hours=WINDOW_PRE_H))].copy()
    m["gs"] = gs[m.index]
    m = m.sort_values("gs")
    out = []
    for r in m.itertuples(index=False):
        toks = [t for t in (list(r.tokens) if r.tokens is not None else []) if t.get("token_id")]
        if not toks:
            continue
        out.append({"cid": r.condition_id, "slug": r.slug,
                    "token": str(toks[0]["token_id"]),
                    "outcome": toks[0].get("outcome", ""),
                    "is_prop": bool(PROP.search(r.slug or "")),
                    "gs": r.gs.isoformat()})
    return out


def book(token_id):
    """(best_bid, best_ask, bid_depth$, ask_depth$) within 2c of touch, or None."""
    try:
        r = S.get("https://clob.polymarket.com/book",
                  params={"token_id": token_id}, timeout=6)
        if r.status_code != 200:
            return None
        j = r.json()
        bids = sorted(((float(x["price"]), float(x["size"])) for x in (j.get("bids") or [])),
                      key=lambda x: -x[0])
        asks = sorted(((float(x["price"]), float(x["size"])) for x in (j.get("asks") or [])),
                      key=lambda x: x[0])
        bb = bids[0][0] if bids else None
        ba = asks[0][0] if asks else None
        bd = round(sum(p * s for p, s in bids if bb and p >= bb - 0.02), 2) if bids else 0.0
        ad = round(sum(p * s for p, s in asks if ba and p <= ba + 0.02), 2) if asks else 0.0
        return bb, ba, bd, ad
    except Exception:
        return None


def main():
    print(f"[price-capture] starting; window -{WINDOW_POST_H}h..+{WINDOW_PRE_H}h, "
          f"{MAX_BOOKS_PER_CYCLE} books/cycle")
    universe, loaded_at, rr = [], 0.0, 0
    while True:
        t0 = time.time()
        if t0 - loaded_at > RELOAD_MARKETS_S or not universe:
            try:
                universe = load_universe(); loaded_at = t0
            except Exception as e:
                print(f"[price-capture] universe load failed: {e}")
                time.sleep(30); continue
        # nearest-to-start always; round-robin the tail within budget
        batch = universe[:MAX_BOOKS_PER_CYCLE]
        tail = universe[MAX_BOOKS_PER_CYCLE:]
        if tail:
            rr %= len(tail)
            extra = max(0, MAX_BOOKS_PER_CYCLE - len(batch))
            batch += tail[rr:rr + extra]; rr += extra
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        path = OUT_DIR / f"prices_{day}.jsonl"
        n_ok = 0
        with path.open("a", encoding="utf-8") as fh:
            for mkt in batch:
                b = book(mkt["token"])
                if b is None:
                    continue
                bb, ba, bd, ad = b
                fh.write(json.dumps({"ts": round(time.time(), 1), "cid": mkt["cid"],
                                     "slug": mkt["slug"], "outcome": mkt["outcome"],
                                     "prop": int(mkt["is_prop"]), "gs": mkt["gs"],
                                     "bid": bb, "ask": ba,
                                     "bid_depth": bd, "ask_depth": ad}) + "\n")
                n_ok += 1
                time.sleep(0.25)   # politeness: ~4 req/s ceiling
        print(f"[price-capture] heartbeat: universe={len(universe)} captured={n_ok} "
              f"cycle={time.time()-t0:.0f}s")
        time.sleep(max(1.0, CYCLE_S - (time.time() - t0)))


if __name__ == "__main__":
    main()
