"""Updown book capture — Phase 0 of the maker-rebate lane (EDGE_AUDIT 2026-07-15).

Logs, for every ACTIVE crypto Up/Down window (BTC/ETH/SOL/XRP x 5m/15m/1h):
  - best bid/ask + depth of the UP token (DOWN book is the binary mirror)
  - the most recent public trades (taker flow -> fee-pool + fill-sim ground truth)
  - Binance spot for all four assets (the fair-value anchor)

This is the fill-true referee for the maker simulation: a hypothetical resting
quote counts as filled ONLY if a real taker print crossed it. No maker order is
ever placed by this script. Zero risk, read-only.

Run (laptop): .venv\\Scripts\\python.exe -u updown_book_capture.py
Scheduled task: UpdownCapture -> watch_updown_capture.bat
Output: output/updown_capture/updown_YYYYMMDD.jsonl  (~15-40 MB/day)
"""
from __future__ import annotations
import json, time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "output" / "updown_capture"
OUT_DIR.mkdir(parents=True, exist_ok=True)

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DATA = "https://data-api.polymarket.com"
BINANCE = "https://api.binance.com/api/v3/ticker/price"

# Verified against gamma 2026-07-16: live families are {btc,eth,sol,xrp,bnb,doge,hype}
# x {5m,15m}. NO 1h family exists (all slug variants 404). HYPE has no Binance
# spot (Hyperliquid-native) -> books/trades still captured, spot anchor absent.
ASSETS = {"btc": "BTCUSDT", "eth": "ETHUSDT", "sol": "SOLUSDT", "xrp": "XRPUSDT",
          "bnb": "BNBUSDT", "doge": "DOGEUSDT", "hype": None}
WINDOWS = {"5m": 300, "15m": 900}
CYCLE_S = 10.0
TRADES_EVERY = 3          # poll trades every Nth cycle per market (dedupe offline by tx)
SLUG_CACHE: dict[str, dict | None] = {}

S = requests.Session()
S.headers["User-Agent"] = "updown-capture/1.0"


def resolve_slug(slug: str) -> dict | None:
    """slug -> {cid, up_token} via gamma; cached (incl. negative)."""
    if slug in SLUG_CACHE:
        return SLUG_CACHE[slug]
    info = None
    try:
        r = S.get(f"{GAMMA}/markets", params={"slug": slug}, timeout=6)
        if r.status_code == 200 and r.json():
            m = r.json()[0]
            toks = json.loads(m["clobTokenIds"]) if isinstance(m.get("clobTokenIds"), str) \
                else (m.get("clobTokenIds") or [])
            outs = json.loads(m["outcomes"]) if isinstance(m.get("outcomes"), str) \
                else (m.get("outcomes") or [])
            up_i = next((i for i, o in enumerate(outs) if str(o).lower() in ("up", "yes")), 0)
            if toks:
                info = {"cid": m.get("conditionId"), "up_token": str(toks[up_i]),
                        "fees_enabled": m.get("feesEnabled"), "closed": m.get("closed")}
    except Exception:
        info = None
    SLUG_CACHE[slug] = info
    if len(SLUG_CACHE) > 3000:
        SLUG_CACHE.clear()
    return info


def get_book(token_id: str):
    try:
        r = S.get(f"{CLOB}/book", params={"token_id": token_id}, timeout=6)
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
        # depth at touch only (queue-position matters for maker sims)
        bd0 = round(bids[0][0] * bids[0][1], 2) if bids else 0.0
        ad0 = round(asks[0][0] * asks[0][1], 2) if asks else 0.0
        return bb, ba, bd, ad, bd0, ad0
    except Exception:
        return None


def get_trades(cid: str, limit=100):
    try:
        r = S.get(f"{DATA}/trades", params={"market": cid, "limit": limit}, timeout=6)
        if r.status_code != 200:
            return None
        return [{"ts": t.get("timestamp"), "px": t.get("price"), "sz": t.get("size"),
                 "side": t.get("side"), "out": t.get("outcome"),
                 "tx": (t.get("transactionHash") or "")[:18]}
                for t in (r.json() or [])]
    except Exception:
        return None


def get_spot():
    try:
        syms = [s for s in ASSETS.values() if s]   # one invalid symbol 400s the batch
        r = S.get(BINANCE, params={"symbols": json.dumps(syms, separators=(",", ":"))},
                  timeout=6)
        if r.status_code == 200:
            return {d["symbol"]: float(d["price"]) for d in r.json()}
    except Exception:
        pass
    return None


def active_slugs(now: float) -> list[tuple[str, str, int]]:
    """(slug, window_name, window_start) for current + next window of each family."""
    out = []
    for a in ASSETS:
        for wname, wsec in WINDOWS.items():
            cur = int(now // wsec) * wsec
            for w0 in (cur, cur + wsec):
                out.append((f"{a}-updown-{wname}-{w0}", wname, w0))
    return out


def main():
    print(f"[updown-capture] start; assets={list(ASSETS)} windows={list(WINDOWS)} cycle={CYCLE_S}s")
    cyc = 0
    while True:
        t0 = time.time()
        cyc += 1
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        path = OUT_DIR / f"updown_{day}.jsonl"
        spot = get_spot()
        n_books = n_trades = 0
        with path.open("a", encoding="utf-8") as fh:
            if spot:
                fh.write(json.dumps({"ts": round(t0, 2), "type": "spot", "px": spot}) + "\n")
            for slug, wname, w0 in active_slugs(t0):
                info = resolve_slug(slug)
                if not info:
                    continue
                b = get_book(info["up_token"])
                if b:
                    bb, ba, bd, ad, bd0, ad0 = b
                    fh.write(json.dumps({
                        "ts": round(time.time(), 2), "type": "book", "slug": slug,
                        "cid": info["cid"], "win": wname, "w0": w0,
                        "fees": info.get("fees_enabled"),
                        "bid": bb, "ask": ba, "bid_depth": bd, "ask_depth": ad,
                        "bid_touch": bd0, "ask_touch": ad0}) + "\n")
                    n_books += 1
                if cyc % TRADES_EVERY == 0 and info.get("cid"):
                    tr = get_trades(info["cid"])
                    if tr:
                        fh.write(json.dumps({"ts": round(time.time(), 2), "type": "trades",
                                             "slug": slug, "cid": info["cid"],
                                             "win": wname, "w0": w0, "trades": tr}) + "\n")
                        n_trades += 1
                time.sleep(0.1)
        if cyc % 30 == 0:
            print(f"[updown-capture] heartbeat: books={n_books} trade-polls={n_trades} "
                  f"cache={len(SLUG_CACHE)} cycle={time.time()-t0:.1f}s")
        time.sleep(max(0.5, CYCLE_S - (time.time() - t0)))


if __name__ == "__main__":
    main()
