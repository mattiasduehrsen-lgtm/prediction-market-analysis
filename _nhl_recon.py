"""NHL fade-the-losers recon.

Tests the core hypothesis: do NHL markets on Polymarket have enough
habitually-losing retail wallets to support a fade strategy?

Pipeline:
  1. Filter clob_markets.parquet to NHL markets active/resolved in last 14 days
  2. Scrape recent trades for each (multi-threaded)
  3. Aggregate per-wallet stats: trades, win rate, PnL, ROI
  4. Report: how many wallets qualify (n>=30, ROI<-5%)?

If 100+ qualifying wallets exist, NHL is a viable expansion target.
If <30, the strategy probably doesn't transfer.
"""
import datetime as dt
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent
ES_DIR = ROOT / "cowork_snapshot" / "esports"
OUT_DIR = ROOT / "cowork_snapshot" / "nhl_recon"
OUT_DIR.mkdir(parents=True, exist_ok=True)

API = "https://data-api.polymarket.com/trades"
PAGE_SIZE = 500
THREADS = 8
LOOKBACK_DAYS = 14
MIN_TRADES_PER_WALLET = 30
MIN_LOSS_ROI = -5.0


def fetch_trades(condition_id):
    """Paginate trades for one market."""
    out = []
    offset = 0
    while True:
        try:
            r = requests.get(API, params={
                "market": condition_id, "limit": PAGE_SIZE, "offset": offset,
            }, timeout=15)
        except Exception:
            time.sleep(1)
            continue
        if r.status_code == 429:
            time.sleep(5); continue
        if r.status_code != 200:
            break
        page = r.json()
        if not page:
            break
        out.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return out


def main():
    print("=" * 72)
    print("NHL FADE-THE-LOSERS RECON")
    print("=" * 72)
    print()

    # STEP 1: Filter clob_markets.parquet
    t0 = time.time()
    print(f"[1/4] Loading clob_markets.parquet...", flush=True)
    df = pd.read_parquet(ES_DIR / "clob_markets.parquet")
    print(f"      Total markets in index: {len(df):,}")

    slugs = df["slug"].fillna("").astype(str).str.lower()
    nhl_mask = slugs.str.startswith("nhl-")
    nhl = df[nhl_mask].copy()
    print(f"      NHL markets: {len(nhl):,}")

    # Filter to last LOOKBACK_DAYS by end_date
    now = dt.datetime.now(dt.timezone.utc)
    cutoff_date = now - dt.timedelta(days=LOOKBACK_DAYS)
    nhl["end_date_parsed"] = pd.to_datetime(nhl["end_date"], errors="coerce", utc=True)
    recent = nhl[(nhl["end_date_parsed"] >= cutoff_date)].copy()
    print(f"      NHL markets ending in last {LOOKBACK_DAYS}d or future: {len(recent):,}")
    if len(recent) == 0:
        print("ERROR: no recent NHL markets found")
        return

    # STEP 2: Scrape trades (multi-threaded)
    print(f"\n[2/4] Scraping trades for {len(recent)} markets ({THREADS} threads)...", flush=True)
    all_trades = []
    completed = 0
    t_scrape = time.time()
    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        futures = {ex.submit(fetch_trades, cid): (cid, slug)
                   for cid, slug in zip(recent["condition_id"], recent["slug"])}
        for fut in as_completed(futures):
            cid, slug = futures[fut]
            try:
                trades = fut.result()
            except Exception as e:
                print(f"      [err] {slug}: {e}")
                continue
            for t in trades:
                t["_slug"] = slug
            all_trades.extend(trades)
            completed += 1
            if completed % 25 == 0:
                rate = completed / (time.time() - t_scrape)
                eta = (len(recent) - completed) / rate if rate > 0 else 0
                print(f"      {completed}/{len(recent)} markets  "
                      f"{len(all_trades):,} trades so far  "
                      f"({rate:.1f} mkt/s, ETA {eta:.0f}s)", flush=True)
    print(f"      Done. {len(all_trades):,} total trades pulled "
          f"in {time.time()-t_scrape:.0f}s")

    if not all_trades:
        print("ERROR: no trades found")
        return

    # Save raw trades for future re-analysis
    trades_df = pd.DataFrame(all_trades)
    trades_df.to_parquet(OUT_DIR / "trades.parquet", index=False)
    print(f"      Saved to {OUT_DIR}/trades.parquet")

    # STEP 3: Per-wallet aggregation
    print(f"\n[3/4] Aggregating per-wallet PnL...", flush=True)
    trades_df["timestamp"] = pd.to_numeric(trades_df["timestamp"], errors="coerce")
    trades_df["price"] = pd.to_numeric(trades_df["price"], errors="coerce")
    trades_df["size"] = pd.to_numeric(trades_df["size"], errors="coerce")
    trades_df = trades_df.dropna(subset=["timestamp", "proxyWallet", "price", "size"])

    # Restrict to last 14d by trade timestamp
    cutoff_ts = cutoff_date.timestamp()
    recent_trades = trades_df[trades_df["timestamp"] >= cutoff_ts].copy()
    print(f"      Trades within {LOOKBACK_DAYS}d window: {len(recent_trades):,}")

    # For each trade, we need to know if it WON. Need market resolution data.
    # Simplification for recon: estimate PnL using current best-bid as exit price.
    # That's wrong for fully-resolved markets but gives us a directional read.
    # Better: pull winners from CLOB market metadata.
    # For now: use a CRUDE proxy — wallet's PnL ≈ sum((size * winner_payout) - cost)
    # where winner_payout = 1 if their outcome won, 0 if lost.
    # For unresolved markets, mark as unresolved.

    # Build a map: condition_id → winning outcome (from clob_markets tokens field)
    # The tokens field has format [{outcome, winner, token_id}, ...]
    print(f"      Resolving market winners...", flush=True)
    winner_map = {}  # condition_id → winning outcome string
    for _, row in recent.iterrows():
        tokens = row.get("tokens")
        if not isinstance(tokens, (list, dict)):
            continue
        if isinstance(tokens, dict):
            tokens = [{"outcome": k, "winner": False} for k in tokens]
        winners = [t for t in tokens if (isinstance(t, dict) and t.get("winner"))]
        if len(winners) == 1:
            winner_map[row["condition_id"]] = winners[0].get("outcome", "")

    print(f"      Resolved markets in our scrape: {len(winner_map):,}/{len(recent):,}")

    # Compute PnL per trade
    def trade_pnl(t):
        cid = t.get("conditionId") or ""
        outcome = t.get("outcome") or ""
        price = float(t.get("price") or 0)
        size = float(t.get("size") or 0)
        cost = price * size
        winner_outcome = winner_map.get(cid)
        if winner_outcome is None:
            return None  # unresolved
        won = (outcome == winner_outcome)
        # If trade was a BUY of the winning outcome: payout = size, profit = size - cost
        # If BUY of losing outcome: lose cost
        side = (t.get("side") or "BUY").upper()
        if side == "BUY":
            return (size - cost) if won else (-cost)
        else:  # SELL
            # SELL = exit; treat as: they gave up shares of `outcome` for cost
            return cost if won else (-cost * 0)  # rough — simplification

    recent_trades["pnl"] = recent_trades.apply(trade_pnl, axis=1)
    recent_trades["cost"] = recent_trades["price"] * recent_trades["size"]
    resolved = recent_trades.dropna(subset=["pnl"]).copy()
    print(f"      Trades on resolved markets (usable for PnL): {len(resolved):,}")

    # Per-wallet
    grp = resolved.groupby("proxyWallet").agg(
        trades=("pnl", "size"),
        wins=("pnl", lambda s: (s > 0).sum()),
        pnl=("pnl", "sum"),
        cost=("cost", "sum"),
    )
    grp["wr"] = grp["wins"] / grp["trades"] * 100
    grp["roi"] = grp["pnl"] / grp["cost"].clip(lower=0.01) * 100
    grp = grp.sort_values("pnl")

    # STEP 4: Report
    print(f"\n[4/4] Wallet analysis:")
    print(f"      Total unique wallets with trades: {len(grp):,}")
    qualified = grp[(grp["trades"] >= MIN_TRADES_PER_WALLET) & (grp["roi"] <= MIN_LOSS_ROI)]
    print(f"      Wallets w/ n>={MIN_TRADES_PER_WALLET} trades AND ROI<={MIN_LOSS_ROI}%: "
          f"<<<{len(qualified)}>>>")

    # Top 10 worst (best fade targets)
    print(f"\n      Top 10 losing wallets (NHL, last {LOOKBACK_DAYS}d):")
    cols = ["trades", "wr", "pnl", "roi"]
    print(qualified.head(10)[cols].to_string())

    # Save summary
    summary = {
        "run_at_utc":          dt.datetime.now(dt.timezone.utc).isoformat(),
        "lookback_days":       LOOKBACK_DAYS,
        "markets_in_window":   len(recent),
        "markets_resolved":    len(winner_map),
        "trades_scraped":      len(all_trades),
        "trades_in_window":    len(recent_trades),
        "trades_resolved":     len(resolved),
        "unique_wallets":      len(grp),
        "qualifying_wallets":  len(qualified),
        "top_loser_wallet":    grp.index[0] if len(grp) else None,
        "top_loser_pnl_usd":   float(grp.iloc[0]["pnl"]) if len(grp) else None,
        "elapsed_seconds":     round(time.time() - t0, 1),
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nSummary saved to {OUT_DIR}/summary.json")
    print(f"Total runtime: {summary['elapsed_seconds']:.0f}s")

    # Verdict
    print()
    print("=" * 72)
    if len(qualified) >= 100:
        print(f"VERDICT: STRONG GO. {len(qualified)} qualifying NHL fade targets exist.")
        print("Strategy likely transfers cleanly. Recommend NHL paper deployment.")
    elif len(qualified) >= 30:
        print(f"VERDICT: WEAK GO. Only {len(qualified)} qualifying wallets — "
              f"workable but signal volume will be lower than esports.")
    else:
        print(f"VERDICT: NO-GO. Only {len(qualified)} qualifying wallets. "
              f"Either off-season effect, or NHL is more efficient than esports.")
    print("=" * 72)


if __name__ == "__main__":
    main()
