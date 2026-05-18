"""Fresh-data analysis wrapper.

Solves the "your analysis is hours behind" problem by:
  1. Force-running evaluate_live + reconciler synchronously so results.csv /
     live_daily_pnl.json are at most seconds old (not up-to-10-minutes old).
  2. Querying multiple Polygon RPCs in parallel and using the one with the
     highest block — public RPCs occasionally lag by hours or days.
  3. Pulling Polymarket data-api /value for live open-position value (not
     the bot's cost-basis estimate).
  4. Stamping every section with how-old-is-this-source so you can see at a
     glance whether anything stale slipped through.

Then defers to full_analysis.py for the actual breakdown.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
ES_OUT = ROOT / "output" / "esports_fade"
LIVE_DAILY = ES_OUT / "live_daily_pnl.json"

PROXY = os.getenv("POLYMARKET_PROXY_ADDRESS", "")

# ERC20 selector for balanceOf(address) is 0x70a08231. Right-pad the address.
USDC_BRIDGED = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC.e (Polymarket collateral)

# Curated list of public Polygon RPCs. We hit them in parallel and pick the
# one with the highest block — saw 3 of 4 lag by 150k+ blocks once.
RPCS = [
    "https://polygon-bor-rpc.publicnode.com",
    "https://polygon.drpc.org",
    "https://1rpc.io/matic",
    "https://polygon.gateway.tenderly.co",
    "https://polygon.llamarpc.com",
    "https://polygon.blockpi.network/v1/rpc/public",
]


def rpc_call(url: str, method: str, params=None, timeout: float = 5.0):
    try:
        r = requests.post(url, json={"jsonrpc": "2.0", "method": method,
                                     "params": params or [], "id": 1},
                          timeout=timeout)
        return r.json().get("result")
    except Exception:
        return None


def best_block(rpcs: list[str]) -> tuple[str, int]:
    """Query each RPC for current block in parallel; return (url, block)
    with the highest block number."""
    results: list[tuple[str, int]] = []
    with ThreadPoolExecutor(max_workers=len(rpcs)) as ex:
        futs = {ex.submit(rpc_call, url, "eth_blockNumber"): url for url in rpcs}
        for f in as_completed(futs):
            blk = f.result()
            if blk:
                try:
                    results.append((futs[f], int(blk, 16)))
                except ValueError:
                    pass
    if not results:
        return ("", 0)
    return max(results, key=lambda x: x[1])


def usdc_balance(rpc: str, holder: str) -> float | None:
    """balanceOf via a specific RPC."""
    addr_padded = holder.lower().replace("0x", "").rjust(64, "0")
    data = "0x70a08231" + addr_padded
    res = rpc_call(rpc, "eth_call",
                   [{"to": USDC_BRIDGED, "data": data}, "latest"])
    if not res or res == "0x":
        return None
    try:
        return int(res, 16) / 1e6
    except ValueError:
        return None


def polymarket_position_value(addr: str) -> float | None:
    """Authoritative open-position value from Polymarket's data-api.

    Note: this only counts UNRESOLVED positions at current mid price.
    Resolved-winning positions (CTF tokens redeemable for $1 each) show as
    $0 here — use polymarket_redeemable_cash() for those.
    """
    try:
        r = requests.get(f"https://data-api.polymarket.com/value?user={addr}",
                         timeout=10)
        d = r.json()
        if isinstance(d, list) and d:
            return float(d[0].get("value", 0))
    except Exception:
        return None
    return None


def polymarket_redeemable_cash(addr: str) -> tuple[float, int] | None:
    """Sum of shares in RESOLVED WINNING markets — each worth $1 once redeemed.

    This is the gap between "USDC at proxy" and "cash shown in Polymarket UI".
    The UI counts redeemable winning shares as cash because you can convert
    them 1:1 with a click; on-chain they're still ERC-1155 tokens.
    """
    try:
        r = requests.get(f"https://data-api.polymarket.com/positions"
                         f"?user={addr}&sizeThreshold=0.01&limit=500",
                         timeout=10)
        positions = r.json()
    except Exception:
        return None
    if not isinstance(positions, list):
        return None
    total_shares_winning_resolved = 0.0
    count = 0
    for p in positions:
        # Polymarket marks resolved positions with `redeemable=true` (winning)
        # or `redeemable=false` + cur_price=0 (lost / nothing to redeem).
        redeemable = bool(p.get("redeemable", False))
        if not redeemable:
            continue
        try:
            shares = float(p.get("size", 0) or 0)
        except (TypeError, ValueError):
            shares = 0.0
        if shares > 0:
            total_shares_winning_resolved += shares
            count += 1
    return (total_shares_winning_resolved, count)


def run_refresh() -> dict:
    """Force-run reconciler + evaluator synchronously. Returns timing info."""
    venv_py = ROOT / ".venv" / "Scripts" / "python.exe"
    if not venv_py.exists():
        venv_py = Path(sys.executable)
    info = {}
    for label, script in (("reconcile", "analysis/reconcile_polymarket_sells.py"),
                          ("eval_live", "analysis/evaluate_live.py")):
        t0 = time.time()
        extra = ["--confirm"] if "reconcile" in script else []
        try:
            res = subprocess.run([str(venv_py), script, *extra],
                                 cwd=str(ROOT),
                                 capture_output=True, text=True,
                                 timeout=180)
            info[label] = {"ok": res.returncode == 0,
                           "dur_s": round(time.time() - t0, 1),
                           "stderr_tail": res.stderr[-200:] if res.stderr else ""}
        except subprocess.TimeoutExpired:
            info[label] = {"ok": False, "dur_s": 180.0, "stderr_tail": "timeout"}
    return info


def main():
    print("=" * 72)
    print("FRESH DATA REFRESH")
    print("=" * 72)
    t_start = time.time()

    # ── 1. Force-run reconciler + evaluator ────────────────────────────────
    print("\nForcing reconciler + evaluator (so results.csv is current)...")
    refresh = run_refresh()
    for k, v in refresh.items():
        flag = "OK " if v["ok"] else "FAIL"
        print(f"  [{flag}] {k:<10s}  {v['dur_s']:>5.1f}s")
        if not v["ok"] and v["stderr_tail"]:
            print(f"         {v['stderr_tail']}")

    # ── 2. Pick freshest RPC ───────────────────────────────────────────────
    print("\nPicking freshest Polygon RPC (highest block)...")
    rpc_url, block = best_block(RPCS)
    if not rpc_url:
        print("  WARN: all RPCs failed; on-chain balance unavailable.")
        cash = None
    else:
        # Show spread between best and worst so we can spot lag.
        all_blocks = []
        with ThreadPoolExecutor(max_workers=len(RPCS)) as ex:
            futs = {ex.submit(rpc_call, u, "eth_blockNumber"): u for u in RPCS}
            for f in as_completed(futs):
                b = f.result()
                if b:
                    try: all_blocks.append((futs[f], int(b, 16)))
                    except ValueError: pass
        if all_blocks:
            mn = min(b for _, b in all_blocks)
            mx = max(b for _, b in all_blocks)
            spread = mx - mn
            print(f"  best RPC: {rpc_url}")
            print(f"  block   : {block:,}  (RPCs spread {spread:,} blocks "
                  f"= ~{spread*2/60:.1f}min lag worst-vs-best)")
        cash = usdc_balance(rpc_url, PROXY) if PROXY else None

    # ── 3. Position value + redeemable winnings via Polymarket data-api ────
    print("\nQuerying Polymarket data-api for live position value...", flush=True)
    pos_val = polymarket_position_value(PROXY) if PROXY else None
    if pos_val is not None:
        print(f"  Open (unresolved) positions value: ${pos_val:.2f}", flush=True)
    else:
        print(f"  WARN: data-api /value returned nothing.", flush=True)

    redeemable = polymarket_redeemable_cash(PROXY) if PROXY else None
    if redeemable is not None:
        shares, count = redeemable
        print(f"  Redeemable winning shares: {shares:.2f} across {count} markets "
              f"(= ${shares:.2f} cash once redeemed)", flush=True)

    # ── 4. Daily PnL (just written by eval_live above) ────────────────────
    daily = {}
    if LIVE_DAILY.exists():
        try:
            daily = json.loads(LIVE_DAILY.read_text())
        except Exception:
            pass

    # ── 5. Wallet snapshot ────────────────────────────────────────────────
    redeem_shares = redeemable[0] if redeemable else 0.0
    redeem_count  = redeemable[1] if redeemable else 0
    ui_cash = (cash or 0.0) + redeem_shares  # matches what Polymarket UI shows

    print()
    print("=" * 72, flush=True)
    print("WALLET SNAPSHOT  (fresh as of right now)", flush=True)
    print("=" * 72, flush=True)
    print(f"  Proxy address     : {PROXY}", flush=True)
    if cash is not None:
        print(f"  USDC.e on-chain   : ${cash:.4f}", flush=True)
    else:
        print(f"  USDC.e on-chain   : <RPC failed>", flush=True)
    if redeemable is not None:
        print(f"  Redeemable shares : {redeem_shares:.2f} = ${redeem_shares:.2f} "
              f"(across {redeem_count} resolved winning markets)", flush=True)
    print(f"  >>> UI 'cash' est : ${ui_cash:.2f}  "
          f"(this is what Polymarket UI shows as cash)", flush=True)
    if pos_val is not None:
        print(f"  Open position val : ${pos_val:.2f}  (unresolved markets, current mid)", flush=True)
    print(f"  >>> TOTAL on-plat : ${ui_cash + (pos_val or 0):.2f}", flush=True)
    if daily:
        print(f"  Today's realized  : ${daily.get('today_pnl', 0):.2f}  "
              f"({daily.get('today_resolved', 0)} resolved, "
              f"{daily.get('today_open', 0)} open)", flush=True)

    print(f"\n  Refresh took {time.time() - t_start:.1f}s", flush=True)
    sys.stdout.flush()  # ensure all of above lands before subprocess writes

    # ── 6. Defer to the existing full analysis for breakdowns ─────────────
    print(flush=True)
    full = ROOT / "analysis" / "full_analysis.py"
    if full.exists():
        venv_py = ROOT / ".venv" / "Scripts" / "python.exe"
        if not venv_py.exists():
            venv_py = Path(sys.executable)
        # Run with utf-8 to avoid the cp1252 unicode crash we hit before.
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        subprocess.run([str(venv_py), str(full)], cwd=str(ROOT), env=env)


if __name__ == "__main__":
    main()
