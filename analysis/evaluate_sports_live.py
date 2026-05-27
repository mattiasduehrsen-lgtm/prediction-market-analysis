"""
Evaluate realized PnL on LIVE orders placed by sports_fade_bot --live.

Mirror of analysis/evaluate_live.py but for the sports bot. Reads
sports-side live_orders.jsonl and writes live_daily_pnl.json that the
bot's DAILY_LOSS_CAP guard reads.

The wallet is shared with the esports bot, so wallet-equity tracking lives
in evaluate_live.py only. This script is a pure ledger-based PnL.

Inputs:
  output/sports_fade/live_orders.jsonl  — each line = one posted order

Outputs:
  output/sports_fade/live_results.csv   — per-order WIN/LOSS/UNRESOLVED + PnL
  output/sports_fade/live_daily_pnl.json — read by sports_fade_bot's
                                            maybe_reload_daily_pnl()

Run via scheduled task PolyBotSportsLiveEval (every 10 min).
"""
from __future__ import annotations

import csv
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT  = ROOT / "output" / "sports_fade"
ORDERS_PATH    = OUT / "live_orders.jsonl"
RESULTS_PATH   = OUT / "live_results.csv"
DAILY_PNL_PATH = OUT / "live_daily_pnl.json"

CACHE: dict[str, dict] = {}
SESSION = requests.Session()


def fetch_market(cid: str) -> dict | None:
    if cid in CACHE:
        return CACHE[cid]
    try:
        r = SESSION.get(f"https://clob.polymarket.com/markets/{cid}", timeout=8)
        if r.status_code != 200:
            return None
        j = r.json()
        CACHE[cid] = j
        return j
    except Exception:
        return None


def fetch_sell_price(token_id: str) -> float | None:
    """Best bid for token_id — what we'd realize if we sold right now."""
    if not token_id:
        return None
    try:
        r = SESSION.get(
            "https://clob.polymarket.com/price",
            params={"token_id": token_id, "side": "sell"},
            timeout=5,
        )
        if r.status_code != 200:
            return None
        j = r.json()
        p = j.get("price")
        return float(p) if p is not None else None
    except Exception:
        return None


def winning_outcome(mkt: dict) -> str | None:
    if not mkt or not mkt.get("closed"):
        return None
    for t in mkt.get("tokens", []) or []:
        if t.get("winner"):
            return t.get("outcome")
    return None


def _write_daily(d: dict):
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = DAILY_PNL_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, indent=2), encoding="utf-8")
    os.replace(tmp, DAILY_PNL_PATH)


def main():
    if not ORDERS_PATH.exists():
        print(f"No sports live orders file at {ORDERS_PATH} yet — writing empty snapshot")
        _write_daily({"date": str(datetime.now(timezone.utc).date()),
                      "realized_pnl_usd": 0.0, "n_resolved": 0, "n_open": 0,
                      "generated_at": time.time()})
        return

    orders = []
    with ORDERS_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                orders.append(json.loads(line))
            except Exception:
                continue
    print(f"Loaded {len(orders):,} sports live orders")

    cids = sorted({o.get("fade_condition") for o in orders if o.get("fade_condition")})
    print(f"Unique markets to resolve: {len(cids)}")
    for i, cid in enumerate(cids):
        fetch_market(cid)
        if (i + 1) % 25 == 0:
            print(f"  {i+1}/{len(cids)}")
        time.sleep(0.05)

    today_str = str(datetime.now(timezone.utc).date())
    today_pnl = 0.0
    today_resolved = 0
    today_open = 0
    today_open_cost = 0.0
    today_open_shares: list[tuple[str, float, float]] = []
    lifetime_open_shares: list[tuple[str, float, float]] = []

    out_rows = []
    n_resolved = 0
    n_wins = 0
    total_pnl = 0.0
    total_cost = 0.0

    # Aggregate SELLs per token_id so BUYs can be paired with SELL exits.
    sells_by_token: dict[str, dict] = {}
    for o in orders:
        if str(o.get("side", "BUY")).upper() != "SELL":
            continue
        if str(o.get("status", "")).lower() != "matched":
            continue
        tid = str(o.get("token_id") or "")
        if not tid:
            continue
        sells_by_token.setdefault(tid, {"shares": 0.0, "proceeds": 0.0})
        sells_by_token[tid]["shares"]   += float(o.get("shares") or 0)
        sells_by_token[tid]["proceeds"] += float(o.get("cost_usd") or 0)

    consumed: dict[str, dict] = {tid: {"shares": 0.0, "proceeds": 0.0}
                                 for tid in sells_by_token}

    buy_orders = sorted(
        [o for o in orders if str(o.get("side", "BUY")).upper() == "BUY"
                          and str(o.get("status", "")).lower() == "matched"
                          and float(o.get("shares") or 0) > 0],
        key=lambda x: float(x.get("ts") or 0)
    )
    other_rows = [o for o in orders if str(o.get("side", "BUY")).upper() == "BUY"
                                    and (str(o.get("status", "")).lower() != "matched"
                                         or float(o.get("shares") or 0) <= 0)]

    for o in buy_orders + other_rows:
        cid    = o.get("fade_condition") or ""
        our_o  = o.get("our_outcome") or ""
        price  = float(o.get("price") or 0)
        shares = float(o.get("shares") or 0)
        cost   = price * shares
        ts     = float(o.get("ts") or 0)
        tid    = str(o.get("token_id") or "")

        mkt    = CACHE.get(cid)
        winner = winning_outcome(mkt) if mkt else None

        is_today = ts and str(datetime.fromtimestamp(ts, tz=timezone.utc).date()) == today_str

        pool      = sells_by_token.get(tid, {"shares": 0.0, "proceeds": 0.0})
        used      = consumed.get(tid, {"shares": 0.0, "proceeds": 0.0})
        remain_sh = max(0.0, pool["shares"]   - used["shares"])
        remain_pr = max(0.0, pool["proceeds"] - used["proceeds"])
        sold_shares = min(shares, remain_sh)
        sold_proceeds = remain_pr * (sold_shares / remain_sh) if remain_sh > 0 else 0.0
        if tid in consumed:
            consumed[tid]["shares"]   += sold_shares
            consumed[tid]["proceeds"] += sold_proceeds
        unsold_shares = max(0.0, shares - sold_shares)

        bo_status = str(o.get("status", "")).lower()
        if shares < 0.01 or bo_status in ("cancelled", "canceled"):
            out_rows.append({**o,
                "status":        "CANCELLED",
                "realized_pnl":  "",
                "cost_usd":      round(cost, 4),
                "sold_shares":   0,
                "sold_proceeds": 0,
            })
            continue

        if shares > 0 and unsold_shares < 0.01 and sold_shares > 0:
            pnl = sold_proceeds - cost
            n_resolved += 1
            if pnl > 0: n_wins += 1
            total_pnl  += pnl
            total_cost += cost
            if is_today:
                today_resolved += 1
                today_pnl += pnl
            out_rows.append({**o,
                "status": "TP_SOLD" if pnl > 0 else "TP_LOSS",
                "realized_pnl": round(pnl, 4),
                "cost_usd":     round(cost, 4),
                "sold_shares":  round(sold_shares, 4),
                "sold_proceeds": round(sold_proceeds, 4),
            })
            continue

        if winner is None:
            remaining_cost = cost * (unsold_shares / shares) if shares else 0.0
            lifetime_open_shares.append((tid, unsold_shares, remaining_cost))
            out_rows.append({**o, "status": "UNRESOLVED", "realized_pnl": "",
                             "cost_usd": round(cost, 4),
                             "sold_shares":  round(sold_shares, 4),
                             "sold_proceeds": round(sold_proceeds, 4)})
            if is_today:
                today_open += 1
                today_open_cost += remaining_cost
                today_open_shares.append((tid, unsold_shares, remaining_cost))
            continue

        n_resolved += 1
        if winner == our_o:
            pnl = (unsold_shares * 1.0) + sold_proceeds - cost
            n_wins += 1
        else:
            pnl = sold_proceeds - cost
        total_pnl  += pnl
        total_cost += cost
        if is_today:
            today_resolved += 1
            today_pnl += pnl

        out_rows.append({**o,
            "status": "WIN" if pnl > 0 else "LOSS",
            "realized_pnl": round(pnl, 4),
            "cost_usd":     round(cost, 4),
            "sold_shares":  round(sold_shares, 4),
            "sold_proceeds": round(sold_proceeds, 4),
        })

    if out_rows:
        cols_set = set()
        for r in out_rows:
            cols_set.update(r.keys())
        tail_cols = ["status", "realized_pnl", "cost_usd"]
        head_cols = [c for c in out_rows[0].keys() if c not in tail_cols]
        cols = head_cols + [c for c in tail_cols if c in cols_set]

        OUT.mkdir(parents=True, exist_ok=True)
        tmp = RESULTS_PATH.with_suffix(".csv.tmp")
        with tmp.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for x in out_rows:
                w.writerow({c: x.get(c, "") for c in cols})
        os.replace(tmp, RESULTS_PATH)

    # Mark open positions to market
    unique_open_tokens = {t for (t, _s, _c) in lifetime_open_shares if t}
    price_cache: dict[str, float] = {}
    for tid in unique_open_tokens:
        p = fetch_sell_price(tid)
        if p is not None:
            price_cache[tid] = p
        time.sleep(0.03)

    def _mtm(rows: list[tuple[str, float, float]]) -> tuple[float, float, int]:
        mv = 0.0; cb = 0.0; n = 0
        for tid, sh, c in rows:
            p = price_cache.get(tid, 0.50)
            mv += sh * p
            cb += c
            n += 1
        return mv, cb, n

    today_mv,    today_cb,    today_priced    = _mtm(today_open_shares)
    lifetime_mv, lifetime_cb, lifetime_priced = _mtm(lifetime_open_shares)
    today_unrealized    = today_mv    - today_cb
    lifetime_unrealized = lifetime_mv - lifetime_cb

    _write_daily({
        "date":                         today_str,
        "realized_pnl_usd":             round(today_pnl, 4),
        "unrealized_pnl_usd":           round(today_unrealized, 4),
        "mtm_pnl_usd":                  round(today_pnl + today_unrealized, 4),
        "open_positions_value_usd":     round(today_mv, 4),
        "open_positions_cost_usd":      round(today_cb, 4),
        "n_resolved":                   today_resolved,
        "n_open":                       today_open,
        "n_open_priced":                today_priced,
        "lifetime_realized_pnl_usd":    round(total_pnl, 4),
        "lifetime_unrealized_pnl_usd":  round(lifetime_unrealized, 4),
        "lifetime_mtm_pnl_usd":         round(total_pnl + lifetime_unrealized, 4),
        "lifetime_cost_usd":            round(total_cost, 4),
        "lifetime_n_resolved":          n_resolved,
        "lifetime_n_open":              len(lifetime_open_shares),
        "lifetime_wins":                n_wins,
        "lifetime_wr_pct":              round(n_wins / max(n_resolved, 1) * 100, 2),
        "lifetime_roi_pct":             round(total_pnl / max(total_cost, 1) * 100, 2),
        "generated_at":                 time.time(),
    })

    print("\n" + "=" * 60)
    print("SPORTS LIVE REALIZED PNL SUMMARY")
    print("=" * 60)
    print(f"  Total orders        : {len(orders):,}")
    print(f"  Resolved (all-time) : {n_resolved:,}  ({n_wins} wins, "
          f"{n_wins/max(n_resolved,1)*100:.1f}% WR)")
    print(f"  PnL (all-time)      : ${total_pnl:+,.2f}  on ${total_cost:,.2f} cost  "
          f"({total_pnl/max(total_cost,1)*100:+.2f}% ROI)")
    print()
    print(f"  TODAY ({today_str})")
    print(f"    resolved      : {today_resolved}")
    print(f"    open          : {today_open}  (priced: {today_priced})")
    print(f"    realized PnL  : ${today_pnl:+,.2f}")
    print(f"    unrealized    : ${today_unrealized:+,.2f}  "
          f"(open value ${today_mv:,.2f} vs cost ${today_cb:,.2f})")
    print(f"    MTM PnL       : ${today_pnl + today_unrealized:+,.2f}")
    print()
    print(f"  LIFETIME MTM (includes open positions @ best bid)")
    print(f"    realized      : ${total_pnl:+,.2f}")
    print(f"    unrealized    : ${lifetime_unrealized:+,.2f}")
    print(f"    MTM PnL       : ${total_pnl + lifetime_unrealized:+,.2f}")


if __name__ == "__main__":
    main()
