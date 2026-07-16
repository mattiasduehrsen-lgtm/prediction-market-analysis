"""One-shot probe: size the maker-rebate opportunity on crypto Up/Down markets.

Answers, with live API data (run on the laptop — dev sandbox has no API egress):
  1. Are current updown markets fee-enabled, and what are the exact fee params?
  2. How much taker notional / taker fees does one day of windows generate
     per (asset, window)?  -> rebate pool = 20% of that, split among makers.
  3. What does the flow look like (taker side balance, trade sizes, # of
     distinct price levels) -> naive fill-share estimate for a small maker.

Read-only. No orders. Run: .venv\\Scripts\\python.exe -u analysis\\updown_rebate_probe.py
"""
from __future__ import annotations
import json, time, sys
from collections import defaultdict

import requests

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DATA = "https://data-api.polymarket.com"

# families verified live 2026-07-16 (no 1h exists; bnb/doge/hype added)
ASSETS = ("btc", "eth", "sol", "xrp", "bnb", "doge", "hype")
WINDOWS = {"5m": 300, "15m": 900}
LOOKBACK_WINDOWS = 24          # how many past windows per family to sample
CRYPTO_FEE_RATE = 0.072        # per help.polymarket.com maker-rebates article; verify below
REBATE_SHARE = 0.20

S = requests.Session()


def gamma_market(slug):
    r = S.get(f"{GAMMA}/markets", params={"slug": slug}, timeout=8)
    if r.status_code == 200 and r.json():
        return r.json()[0]
    return None


def clob_market(cid):
    r = S.get(f"{CLOB}/markets/{cid}", timeout=8)
    return r.json() if r.status_code == 200 else None


def trades(cid, limit=500):
    out, offset = [], 0
    while len(out) < limit:
        r = S.get(f"{DATA}/trades", params={"market": cid, "limit": 100, "offset": offset}, timeout=8)
        if r.status_code != 200 or not r.json():
            break
        batch = r.json()
        out += batch
        if len(batch) < 100:
            break
        offset += 100
    return out


def fee_usdc(price, shares, rate=CRYPTO_FEE_RATE):
    # fee-curve form used by the rebates article: C * rate * p * (1-p)
    return shares * rate * price * (1.0 - price)


def main():
    now = time.time()
    print("=" * 70)
    print("1) FEE PARAMS on a current window per family (CLOB market object)")
    print("=" * 70)
    for a in ASSETS:
        for wname, wsec in WINDOWS.items():
            w0 = int(now // wsec) * wsec
            slug = f"{a}-updown-{wname}-{w0}"
            gm = gamma_market(slug)
            if not gm:
                print(f"{slug:34s} -> not found (family may not exist)")
                continue
            cm = clob_market(gm.get("conditionId")) or {}
            fee_fields = {k: v for k, v in cm.items() if "fee" in k.lower()}
            print(f"{slug:34s} feesEnabled={gm.get('feesEnabled')} clob_fee_fields={fee_fields}")
            time.sleep(0.2)

    print()
    print("=" * 70)
    print(f"2) TAKER FLOW, last {LOOKBACK_WINDOWS} windows per family")
    print("=" * 70)
    summary = {}
    for a in ASSETS:
        for wname, wsec in WINDOWS.items():
            tot_notional = tot_fee = n_trades = 0.0
            n_found = 0
            sizes = []
            for i in range(1, LOOKBACK_WINDOWS + 1):
                w0 = (int(now // wsec) - i) * wsec
                slug = f"{a}-updown-{wname}-{w0}"
                gm = gamma_market(slug)
                if not gm:
                    continue
                n_found += 1
                for t in trades(gm.get("conditionId")):
                    px, sz = float(t.get("price", 0)), float(t.get("size", 0))
                    tot_notional += px * sz
                    tot_fee += fee_usdc(px, sz)
                    sizes.append(px * sz)
                    n_trades += 1
                time.sleep(0.15)
            if n_found == 0:
                continue
            per_day = 86400 / (wsec * n_found)
            pool_day = tot_fee * REBATE_SHARE * per_day
            summary[(a, wname)] = (tot_notional * per_day, pool_day, n_trades)
            med = sorted(sizes)[len(sizes) // 2] if sizes else 0
            print(f"{a}-{wname}: windows_found={n_found} trades={n_trades:.0f} "
                  f"taker_notional=${tot_notional:,.0f} est_fees=${tot_fee:,.2f} "
                  f"median_trade=${med:,.0f}")
            print(f"   -> per-day: notional ${tot_notional*per_day:,.0f}, "
                  f"MAKER REBATE POOL ~ ${pool_day:,.0f}/day (at {REBATE_SHARE:.0%} share)")

    print()
    print("=" * 70)
    print("3) SMALL-MAKER PROJECTION (fill share -> rebate income)")
    print("=" * 70)
    for share in (0.005, 0.01, 0.02, 0.05):
        daily = sum(pool * share for _, pool, _ in summary.values())
        print(f"   fill share {share:.1%} of every pool -> ~${daily:,.2f}/day rebates "
              f"(before spread capture / adverse selection)")
    print("\nNOTE: rebate ~= REBATE_SHARE x fee-equivalent of YOUR filled maker volume.")
    print("A $300 bankroll turning over N x per day at mid prices earns roughly")
    print("300 * N * 0.072 * p(1-p)/p * 0.20 per day; the binding question is not the")
    print("rebate, it is ADVERSE SELECTION on the fills — Phase 1 measures that from")
    print("updown_book_capture data before any order is placed.")


if __name__ == "__main__":
    sys.exit(main())
