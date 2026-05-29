"""Feasibility probe: can we see Polymarket trades ON-CHAIN within seconds?

If yes, an on-chain log listener (filtered to our target wallets) replaces the
~4-minute-stale data-api feed and collapses segment A from 108s to ~2-5s.

Tests:
  1. Connect to a public Polygon RPC, get latest block age (should be ~2s).
  2. Pull recent OrderFilled events from Polymarket's CTF Exchange contracts.
  3. Report how fresh those on-chain fills are vs the data-api's ~220s.
  4. Confirm maker/taker addresses are filterable (indexed topics).
"""
from __future__ import annotations
import time
from web3 import Web3

# Public Polygon RPC (no key) — fine for a probe. Production would use a
# websocket RPC (Alchemy/QuickNode free tier) for push subscriptions.
RPCS = [
    "https://polygon-rpc.com",
    "https://polygon-bor-rpc.publicnode.com",
    "https://rpc.ankr.com/polygon",
]

# Polymarket exchange contracts on Polygon
CTF_EXCHANGE      = Web3.to_checksum_address("0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E")
NEG_RISK_EXCHANGE = Web3.to_checksum_address("0xC5d563A36AE78145C45a50134d48A1215220f80a")

# OrderFilled(bytes32 orderHash, address maker, address taker, uint256 makerAssetId,
#             uint256 takerAssetId, uint256 makerAmountFilled, uint256 takerAmountFilled, uint256 fee)
ORDER_FILLED_TOPIC = Web3.keccak(
    text="OrderFilled(bytes32,address,address,uint256,uint256,uint256,uint256,uint256)"
).hex()

def connect():
    for url in RPCS:
        try:
            w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 10}))
            # Polygon is POA — inject middleware so block parsing works
            try:
                from web3.middleware import ExtraDataToPOAMiddleware
                w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            except Exception:
                pass
            if w3.is_connected():
                print(f"  connected: {url}")
                return w3
        except Exception as e:
            print(f"  {url} failed: {e}")
    return None

def main():
    print("="*84)
    print(" ON-CHAIN FRESHNESS PROBE (Polygon)")
    print("="*84)
    w3 = connect()
    if not w3:
        print("  could not connect to any RPC"); return

    now = time.time()
    latest = w3.eth.block_number
    blk = w3.eth.get_block(latest)
    print(f"\n  latest block #{latest}, timestamp age = {now - blk['timestamp']:.1f}s "
          f"(Polygon block time ~2s)")

    # Pull OrderFilled logs from the last ~60 blocks (~2 min of chain)
    from_block = latest - 60
    for name, addr in [("CTF_EXCHANGE", CTF_EXCHANGE), ("NEG_RISK_EXCHANGE", NEG_RISK_EXCHANGE)]:
        try:
            logs = w3.eth.get_logs({
                "fromBlock": from_block, "toBlock": latest,
                "address": addr,
                "topics": ["0x"+ORDER_FILLED_TOPIC.lstrip("0x")],
            })
        except Exception as e:
            print(f"\n  {name}: get_logs failed: {e}")
            continue
        print(f"\n  {name}: {len(logs)} OrderFilled events in last 60 blocks")
        if logs:
            # freshness of the newest event
            newest_blk = max(l["blockNumber"] for l in logs)
            b = w3.eth.get_block(newest_blk)
            print(f"    newest event block #{newest_blk}, age = {now - b['timestamp']:.1f}s")
            # decode maker/taker from a sample (topics[2], topics[3] are indexed addresses)
            sample = logs[-1]
            try:
                maker = "0x" + sample["topics"][2].hex()[-40:]
                taker = "0x" + sample["topics"][3].hex()[-40:]
                print(f"    sample maker={maker}  taker={taker}")
                print(f"    -> maker/taker are INDEXED topics: we can filter by target wallet")
            except Exception as e:
                print(f"    topic decode note: {e}")

    print("\n" + "="*84)
    print(" VERDICT")
    print("="*84)
    print("  data-api /trades freshness measured earlier : ~220-350s behind")
    print(f"  on-chain latest block                        : ~{now - blk['timestamp']:.0f}s behind")
    print("  If OrderFilled events are present and fresh, on-chain is the fix.")

if __name__ == "__main__":
    main()
