"""Reverse-engineer the real exchange contract + event from a known trade.

Take a recent trade from the data-api (has transactionHash), pull its on-chain
receipt, and dump which contracts emitted logs + their topic0. This tells us
exactly what to subscribe to — no guessing addresses.
"""
from __future__ import annotations
import time, requests
from web3 import Web3

RPCS = ["https://polygon-bor-rpc.publicnode.com", "https://polygon-rpc.com"]

def connect():
    for url in RPCS:
        try:
            w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 12}))
            try:
                from web3.middleware import ExtraDataToPOAMiddleware
                w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            except Exception: pass
            if w3.is_connected():
                print(f"connected: {url}"); return w3
        except Exception: pass
    return None

# Grab recent trades; find ones with a txn hash. Prefer an esports (cs2) trade.
r = requests.get("https://data-api.polymarket.com/trades", params={"limit": 200}, timeout=10)
trades = r.json()
print(f"pulled {len(trades)} trades from data-api")
sample = []
for t in trades:
    h = t.get("transactionHash")
    if h:
        sample.append(t)
    if len(sample) >= 3:
        break

w3 = connect()
if not w3:
    raise SystemExit("no RPC")

KNOWN = {
    "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E".lower(): "CTF_Exchange(guess)",
    "0xC5d563A36AE78145C45a50134d48A1215220f80a".lower(): "NegRisk_Exchange(guess)",
}

for t in sample:
    h = t.get("transactionHash")
    print("\n" + "="*80)
    print(f"trade: wallet={t.get('proxyWallet','')[:12]} side={t.get('side')} "
          f"outcome={t.get('outcome')} price={t.get('price')} slug={t.get('slug','')[:40]}")
    print(f"  tx={h}  data-api ts age={time.time()-float(t.get('timestamp',0)):.0f}s")
    try:
        rcpt = w3.eth.get_transaction_receipt(h)
    except Exception as e:
        print(f"  receipt fetch failed: {e}"); continue
    print(f"  block #{rcpt['blockNumber']}  to={rcpt['to']}  {len(rcpt['logs'])} logs")
    # Tally emitting contracts and topic0s
    seen = {}
    for lg in rcpt["logs"]:
        addr = lg["address"].lower()
        topic0 = lg["topics"][0].hex() if lg["topics"] else ""
        ntopics = len(lg["topics"])
        seen.setdefault((addr, topic0, ntopics), 0)
        seen[(addr, topic0, ntopics)] += 1
    for (addr, topic0, ntopics), cnt in seen.items():
        tag = KNOWN.get(addr, "")
        print(f"    {addr}  topic0=0x{topic0[-16:]}  n_topics={ntopics}  x{cnt}  {tag}")

print("\n" + "="*80)
print("Look for the contract+topic0 that appears on EVERY trade with 3+ topics")
print("(indexed maker/taker). That's our subscription target.")
