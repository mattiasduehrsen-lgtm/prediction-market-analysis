"""Perps data package for the Cowork funding-carry study (2026-07-19).

Fetches into cowork_snapshot/perps/ (the Cowork sandbox has no API egress,
so everything it needs must be here):
  - binance_funding.parquet    2y of 8h funding rates, 6 USDT-perps
  - hyperliquid_funding.parquet 1y of hourly funding, 4 coins
  - binance_basis.parquet      2y daily closes, spot vs perp (basis series)

All public endpoints, read-only, re-runnable (full refetch each run).
Run (dev): .venv\\Scripts\\python.exe -u analysis/perps_data_fetch.py
"""
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "cowork_snapshot" / "perps"
OUT.mkdir(parents=True, exist_ok=True)
S = requests.Session()

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT")
HL_COINS = ("BTC", "ETH", "SOL", "HYPE")
NOW_MS = int(time.time() * 1000)
TWO_Y_MS = NOW_MS - 2 * 365 * 86400 * 1000
ONE_Y_MS = NOW_MS - 365 * 86400 * 1000


def binance_funding():
    rows = []
    for sym in SYMBOLS:
        start = TWO_Y_MS
        while True:
            r = S.get("https://fapi.binance.com/fapi/v1/fundingRate",
                      params={"symbol": sym, "startTime": start, "limit": 1000}, timeout=15)
            page = r.json() if r.status_code == 200 else []
            if not page:
                break
            rows += [{"symbol": sym, "ts": p["fundingTime"] // 1000,
                      "rate": float(p["fundingRate"]),
                      "mark": float(p.get("markPrice") or 0)} for p in page]
            if len(page) < 1000:
                break
            start = page[-1]["fundingTime"] + 1
            time.sleep(0.3)
        print(f"  binance {sym}: {sum(1 for x in rows if x['symbol'] == sym)} fundings")
    df = pd.DataFrame(rows).drop_duplicates(["symbol", "ts"])
    df.to_parquet(OUT / "binance_funding.parquet", index=False)
    print(f"[binance_funding] {len(df):,} rows")


def hyperliquid_funding():
    rows = []
    for coin in HL_COINS:
        start = ONE_Y_MS
        while True:
            r = S.post("https://api.hyperliquid.xyz/info", timeout=15,
                       json={"type": "fundingHistory", "coin": coin, "startTime": start})
            page = r.json() if r.status_code == 200 else []
            if not page:
                break
            rows += [{"coin": coin, "ts": p["time"] // 1000,
                      "rate": float(p["fundingRate"]),
                      "premium": float(p.get("premium") or 0)} for p in page]
            new_start = page[-1]["time"] + 1
            if new_start <= start or len(page) < 2:
                break
            start = new_start
            time.sleep(0.3)
        print(f"  hyperliquid {coin}: {sum(1 for x in rows if x['coin'] == coin)} fundings")
    df = pd.DataFrame(rows).drop_duplicates(["coin", "ts"])
    df.to_parquet(OUT / "hyperliquid_funding.parquet", index=False)
    print(f"[hyperliquid_funding] {len(df):,} rows")


def binance_basis():
    rows = []
    for sym in SYMBOLS:
        for kind, url in (("spot", "https://api.binance.com/api/v3/klines"),
                          ("perp", "https://fapi.binance.com/fapi/v1/klines")):
            start = TWO_Y_MS
            while True:
                r = S.get(url, params={"symbol": sym, "interval": "1d",
                                       "startTime": start, "limit": 1000}, timeout=15)
                page = r.json() if r.status_code == 200 else []
                if not isinstance(page, list) or not page:
                    break
                rows += [{"symbol": sym, "kind": kind, "ts": k[0] // 1000,
                          "close": float(k[4]), "volume": float(k[5])} for k in page]
                if len(page) < 1000:
                    break
                start = page[-1][0] + 86400000
                time.sleep(0.3)
    df = pd.DataFrame(rows).drop_duplicates(["symbol", "kind", "ts"])
    df.to_parquet(OUT / "binance_basis.parquet", index=False)
    print(f"[binance_basis] {len(df):,} rows")


if __name__ == "__main__":
    binance_funding()
    hyperliquid_funding()
    binance_basis()
    print("done ->", OUT)
