"""Measure how fresh each candidate data source is, RIGHT NOW.

For each, compute (now - newest_trade_timestamp) = how far behind real-time.
This decides the fix:
  - if global /trades feed is itself ~100s behind -> need a different source
  - if per-user /trades is fresher -> switch endpoint (easy win)
  - on-chain is the ground-truth real-time reference
"""
from __future__ import annotations
import time, json
import requests

NOW = time.time()
S = requests.Session()

def newest_age(label, url, params):
    try:
        r = S.get(url, params=params, timeout=10)
        if r.status_code != 200:
            print(f"  {label:<42} HTTP {r.status_code}")
            return
        data = r.json()
        if not data:
            print(f"  {label:<42} empty")
            return
        if isinstance(data, dict):
            data = data.get("data") or data.get("history") or []
        if not data:
            print(f"  {label:<42} empty list")
            return
        # find max timestamp field
        ts_vals = []
        for row in data[:200]:
            for k in ("timestamp","matchtime","match_time","createdAt","time"):
                v = row.get(k) if isinstance(row, dict) else None
                if v is not None:
                    try: ts_vals.append(float(v))
                    except Exception: pass
                    break
        if not ts_vals:
            print(f"  {label:<42} no timestamp field; keys={list(data[0].keys())[:8]}")
            return
        newest = max(ts_vals)
        # some endpoints use ms
        if newest > 1e12: newest /= 1000.0
        age = NOW - newest
        print(f"  {label:<42} newest trade age = {age:>7.1f}s   (n={len(data)})")
    except Exception as e:
        print(f"  {label:<42} ERROR {e}")

print("="*84)
print(" DATA SOURCE FRESHNESS PROBE  (lower age = closer to real-time)")
print("="*84)

# 1. Global trades feed (what we use now)
newest_age("data-api /trades (global, limit=500)",
           "https://data-api.polymarket.com/trades", {"limit": 500})

# 2. Global trades feed, takerOnly / different sort if supported
newest_age("data-api /trades (limit=100)",
           "https://data-api.polymarket.com/trades", {"limit": 100})

# 3. Activity feed (sometimes fresher)
newest_age("data-api /activity (limit=500)",
           "https://data-api.polymarket.com/activity", {"limit": 500})

# 4. CLOB trades endpoint (different service)
newest_age("clob /trades",
           "https://clob.polymarket.com/trades", {})

# Sample a couple known-active target wallets for per-user freshness
import pathlib, json as _j
ROOT = pathlib.Path(__file__).resolve().parents[1]
tj = _j.loads((ROOT/"cowork_snapshot"/"esports"/"fade_targets.json").read_text(encoding="utf-8"))
wallets = tj.get("target_wallets", [])[:3]
print("\n  per-user /trades for 3 sample target wallets:")
for w in wallets:
    newest_age(f"    user={w[:12]}",
               "https://data-api.polymarket.com/trades", {"user": w, "limit": 50})

print("\n  NOTE: repeat this a few times; a single sample can be noisy.")
