"""Generic fade-the-losers recon for any Polymarket category.

Reusable from _nhl_recon.py. Takes a slug prefix list, scrapes recent trades,
identifies losing wallets, reports verdict.

Usage:
    python _sports_recon.py --sport nhl
    python _sports_recon.py --sport nba
    python _sports_recon.py --sport mlb
    python _sports_recon.py --sport nfl
    python _sports_recon.py --sport tennis  # = atp|wta
    python _sports_recon.py --sport soccer  # = epl|laliga|champions|...
"""
import argparse
import datetime as dt
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent
ES_DIR = ROOT / "cowork_snapshot" / "esports"

API = "https://data-api.polymarket.com/trades"
PAGE_SIZE = 500
THREADS = 8
LOOKBACK_DAYS = 14
MIN_TRADES = 30
MIN_LOSS_ROI = -5.0

SPORT_PREFIXES = {
    "nhl":      ["nhl-"],
    "nba":      ["nba-"],
    "mlb":      ["mlb-"],
    "nfl":      ["nfl-"],
    "tennis":   ["atp-", "wta-"],
    "soccer":   ["epl-", "laliga-", "champions-", "uefa-", "fifa-"],
    "ufc":      ["ufc-"],
    "boxing":   ["boxing-"],
    "f1":       ["f1-", "formula-"],
    "cbb":      ["cbb-"],  # college basketball
}


def fetch_trades(condition_id):
    out = []
    offset = 0
    while True:
        try:
            r = requests.get(API, params={
                "market": condition_id, "limit": PAGE_SIZE, "offset": offset,
            }, timeout=15)
        except Exception:
            time.sleep(1); continue
        if r.status_code == 429:
            time.sleep(5); continue
        if r.status_code != 200:
            break
        page = r.json()
        if not page: break
        out.extend(page)
        if len(page) < PAGE_SIZE: break
        offset += PAGE_SIZE
    return out


def run_sport(sport):
    prefixes = SPORT_PREFIXES[sport]
    print(f"\n{'=' * 70}")
    print(f" SPORT: {sport.upper()}  (prefixes: {prefixes})")
    print(f"{'=' * 70}")

    out_dir = ROOT / "cowork_snapshot" / f"{sport}_recon"
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # Filter markets
    df = pd.read_parquet(ES_DIR / "clob_markets.parquet")
    slugs = df["slug"].fillna("").astype(str).str.lower()
    sport_mask = pd.Series(False, index=df.index)
    for p in prefixes:
        sport_mask |= slugs.str.startswith(p)
    sport_df = df[sport_mask].copy()

    now = dt.datetime.now(dt.timezone.utc)
    cutoff_date = now - dt.timedelta(days=LOOKBACK_DAYS)
    sport_df["end_date_parsed"] = pd.to_datetime(sport_df["end_date"], errors="coerce", utc=True)
    recent = sport_df[sport_df["end_date_parsed"] >= cutoff_date].copy()
    print(f"  Markets: total={len(sport_df):,}, in last {LOOKBACK_DAYS}d={len(recent):,}")
    if len(recent) == 0:
        return {"sport": sport, "verdict": "NO_MARKETS",
                "qualifying_wallets": 0, "in_window_markets": 0}

    # Scrape
    t_scrape = time.time()
    all_trades = []
    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        futures = {ex.submit(fetch_trades, cid): cid for cid in recent["condition_id"]}
        done = 0
        for fut in as_completed(futures):
            try: all_trades.extend(fut.result())
            except Exception: continue
            done += 1
            if done % 100 == 0:
                print(f"    {done}/{len(recent)} markets, {len(all_trades):,} trades", flush=True)
    print(f"  Scraped {len(all_trades):,} trades in {time.time()-t_scrape:.0f}s")
    if not all_trades:
        return {"sport": sport, "verdict": "NO_TRADES",
                "qualifying_wallets": 0, "in_window_markets": len(recent)}

    trades_df = pd.DataFrame(all_trades)
    trades_df.to_parquet(out_dir / "trades.parquet", index=False)

    # Resolve winners
    winner_map = {}
    for _, row in recent.iterrows():
        tokens = row.get("tokens")
        if tokens is None: continue
        try: token_list = list(tokens)
        except Exception: continue
        winners = [t for t in token_list if (isinstance(t, dict) and t.get("winner"))]
        if len(winners) == 1:
            winner_map[row["condition_id"]] = winners[0].get("outcome", "")

    # PnL aggregation
    trades_df["timestamp"] = pd.to_numeric(trades_df["timestamp"], errors="coerce")
    trades_df["price"] = pd.to_numeric(trades_df["price"], errors="coerce")
    trades_df["size"] = pd.to_numeric(trades_df["size"], errors="coerce")
    trades_df = trades_df.dropna(subset=["timestamp", "proxyWallet", "price", "size"])
    cutoff_ts = cutoff_date.timestamp()
    rt = trades_df[trades_df["timestamp"] >= cutoff_ts].copy()
    buys = rt[rt["side"].str.upper() == "BUY"].copy()
    buys["winner_outcome"] = buys["conditionId"].map(winner_map)
    resolved = buys.dropna(subset=["winner_outcome"]).copy()
    if len(resolved) == 0:
        return {"sport": sport, "verdict": "NO_RESOLVED",
                "qualifying_wallets": 0, "in_window_markets": len(recent)}
    resolved["won"] = resolved["outcome"] == resolved["winner_outcome"]
    resolved["cost"] = resolved["price"] * resolved["size"]
    resolved["pnl"] = resolved.apply(
        lambda r: r["size"] - r["cost"] if r["won"] else -r["cost"], axis=1
    )

    grp = resolved.groupby("proxyWallet").agg(
        trades=("pnl", "size"),
        wins=("pnl", lambda s: (s > 0).sum()),
        pnl=("pnl", "sum"),
        cost=("cost", "sum"),
    )
    grp["wr"] = grp["wins"] / grp["trades"] * 100
    grp["roi"] = grp["pnl"] / grp["cost"].clip(lower=0.01) * 100
    grp = grp.sort_values("pnl")
    qualified = grp[(grp["trades"] >= MIN_TRADES) & (grp["roi"] <= MIN_LOSS_ROI)]

    print(f"  Unique wallets: {len(grp):,}")
    print(f"  Qualifying (n>={MIN_TRADES}, ROI<={MIN_LOSS_ROI}%): <<<{len(qualified)}>>>")
    if len(qualified) > 0:
        print(f"  Top 5 losers:")
        print(qualified.head(5)[["trades","wr","pnl","roi"]].to_string())
    top_loser_pnl = float(qualified.iloc[0]["pnl"]) if len(qualified) else 0

    # Save wallet list
    qualified.to_parquet(out_dir / "losing_wallets.parquet")

    summary = {
        "sport": sport,
        "in_window_markets":  len(recent),
        "resolved_markets":   len(winner_map),
        "trades_scraped":     len(all_trades),
        "trades_in_window":   len(rt),
        "trades_resolved":    len(resolved),
        "unique_wallets":     len(grp),
        "qualifying_wallets": len(qualified),
        "top_loser_pnl_usd":  round(top_loser_pnl, 2),
        "elapsed_seconds":    round(time.time() - t0, 1),
    }
    if len(qualified) >= 100:
        summary["verdict"] = "STRONG_GO"
    elif len(qualified) >= 30:
        summary["verdict"] = "WEAK_GO"
    else:
        summary["verdict"] = "NO_GO"
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", nargs="+", default=list(SPORT_PREFIXES.keys()),
                    help="One or more sports. Default: all.")
    args = ap.parse_args()

    results = []
    for sport in args.sport:
        if sport not in SPORT_PREFIXES:
            print(f"[skip] unknown sport: {sport}")
            continue
        try:
            results.append(run_sport(sport))
        except Exception as e:
            print(f"[ERROR] {sport}: {e}")
            import traceback; traceback.print_exc()

    # Cross-sport comparison
    print(f"\n{'=' * 90}")
    print(f" CROSS-SPORT SUMMARY")
    print(f"{'=' * 90}")
    print(f"{'sport':>10} {'markets':>9} {'trades':>10} {'wallets':>9} "
          f"{'qual':>6} {'top_loser_$':>13}  verdict")
    print(f"-" * 90)
    for r in sorted(results, key=lambda x: -x.get("qualifying_wallets", 0)):
        print(f"{r['sport']:>10} {r.get('in_window_markets',0):>9} "
              f"{r.get('trades_in_window',0):>10,} {r.get('unique_wallets',0):>9,} "
              f"{r.get('qualifying_wallets',0):>6} ${r.get('top_loser_pnl_usd',0):>11,.0f}  "
              f"{r.get('verdict','?')}")


if __name__ == "__main__":
    main()
