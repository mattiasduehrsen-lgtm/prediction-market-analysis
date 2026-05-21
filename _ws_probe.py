"""Polymarket WebSocket probe — does the trade event include wallet info?

Connects to wss://ws-subscriptions-clob.polymarket.com/ws/market, subscribes
to a handful of currently-active CS2 markets, listens for 30s, dumps every
event to stdout. Looking specifically for:
  - whether 'trade' events include `proxyWallet` / `maker_address` / similar
  - whether we get push updates faster than 1s data-api polling would

Doesn't trade. Read-only probe.
"""
from __future__ import annotations
import asyncio
import json
import time
from pathlib import Path

try:
    import websockets
except ImportError:
    print("Need: pip install websockets")
    raise SystemExit(1)

ROOT = Path(__file__).resolve().parent
CLOB_MARKETS = ROOT / "cowork_snapshot" / "esports" / "clob_esports_markets.parquet"

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


def pick_active_cs2_tokens(limit: int = 5) -> list[str]:
    """Pick a few currently-active CS2 markets, return their token_ids."""
    import pandas as pd
    df = pd.read_parquet(CLOB_MARKETS)
    cs2 = df[df["slug"].fillna("").str.startswith(("cs2-", "csgo-"))].copy()
    # Active = not closed, has end_date in the future or recent
    if "closed" in cs2.columns:
        cs2 = cs2[~cs2["closed"].fillna(False)]
    if "end_date_iso" in cs2.columns:
        # Keep ones ending within next 48h
        import datetime as dt
        now = dt.datetime.now(dt.timezone.utc)
        soon = (now + dt.timedelta(hours=48)).isoformat()
        cs2["end_date_iso"] = cs2["end_date_iso"].fillna("")
        cs2 = cs2[(cs2["end_date_iso"] > now.isoformat()) & (cs2["end_date_iso"] < soon)]
    # tokens column has both yes/no token_ids
    tokens: list[str] = []
    for _, row in cs2.head(limit).iterrows():
        tk = row.get("tokens")
        if isinstance(tk, dict):
            for v in tk.values():
                tokens.append(str(v))
        elif isinstance(tk, str):
            try:
                d = json.loads(tk)
                for v in d.values():
                    tokens.append(str(v))
            except Exception:
                pass
    return tokens[:limit * 2]  # 2 tokens per market


async def probe(token_ids: list[str], duration: int = 30):
    print(f"Connecting to {WS_URL}...")
    async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=10) as ws:
        sub_msg = {"type": "MARKET", "assets_ids": token_ids}
        print(f"Subscribing to {len(token_ids)} tokens...")
        await ws.send(json.dumps(sub_msg))
        print(f"Listening for {duration}s. Each unique event_type gets logged once with full sample.")
        seen_types: dict[str, dict] = {}
        n_msgs = 0
        start = time.time()
        try:
            while time.time() - start < duration:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                except asyncio.TimeoutError:
                    continue
                n_msgs += 1
                try:
                    msg = json.loads(raw)
                except Exception:
                    print(f"  (non-JSON message: {raw[:120]})")
                    continue
                # Sample format we get back can be a list or a single dict
                items = msg if isinstance(msg, list) else [msg]
                for it in items:
                    et = it.get("event_type") or it.get("type") or "?"
                    if et not in seen_types:
                        seen_types[et] = it
                        print(f"\n=== First {et} message ===")
                        print(json.dumps(it, indent=2)[:1500])
        except KeyboardInterrupt:
            pass
        print(f"\n--- Summary ---")
        print(f"Total messages: {n_msgs}")
        print(f"Unique event_types seen: {list(seen_types.keys())}")
        # Specifically check for wallet info on trade events
        for et, sample in seen_types.items():
            if "trade" in et.lower():
                keys = list(sample.keys()) if isinstance(sample, dict) else []
                wallet_keys = [k for k in keys if any(w in k.lower() for w in ("wallet", "address", "maker", "taker", "from", "user"))]
                print(f"  trade-event keys: {keys}")
                print(f"  wallet-ish keys:  {wallet_keys}")


def main():
    if not CLOB_MARKETS.exists():
        print(f"Need CLOB markets file at {CLOB_MARKETS}")
        return
    tokens = pick_active_cs2_tokens(limit=8)
    if not tokens:
        print("Couldn't find any active CS2 tokens to subscribe to.")
        return
    print(f"Picked {len(tokens)} CS2 tokens to probe.")
    asyncio.run(probe(tokens, duration=30))


if __name__ == "__main__":
    main()
