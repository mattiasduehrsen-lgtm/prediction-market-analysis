"""Decisive check: does the on-chain OrderFilled maker/taker == the data-api
proxyWallet? If yes, we can filter chain logs by our target wallet set.

Also confirm we can map makerAssetId/takerAssetId (ERC1155 token ids) to a
market/outcome via the CLOB index the bot already loads.
"""
from __future__ import annotations
import time, requests
from web3 import Web3
from eth_abi import decode as abi_decode

RPCS = ["https://polygon-bor-rpc.publicnode.com", "https://polygon-rpc.com"]
EXCHANGE = "0x4d97dcd97ec945f40cf65f87097ace5ea0476045"
ORDER_FILLED = Web3.keccak(text="OrderFilled(bytes32,address,address,uint256,uint256,uint256,uint256,uint256)").hex()

def connect():
    for url in RPCS:
        w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 12}))
        try:
            from web3.middleware import ExtraDataToPOAMiddleware
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        except Exception: pass
        if w3.is_connected():
            print(f"connected: {url}"); return w3
    raise SystemExit("no rpc")

w3 = connect()
tf = "0x" + ORDER_FILLED.lstrip("0x")

# Get a batch of recent trades, find one whose tx we can fully decode
r = requests.get("https://data-api.polymarket.com/trades", params={"limit": 100}, timeout=10)
trades = r.json()

checked = 0
for t in trades:
    h = t.get("transactionHash")
    pw = (t.get("proxyWallet") or "").lower()
    if not h or not pw:
        continue
    try:
        rcpt = w3.eth.get_transaction_receipt(h)
    except Exception:
        continue
    # Match empirically: log on the exchange contract with 4 topics
    # (topic0 + indexed orderHash + indexed maker + indexed taker = OrderFilled).
    of_logs = [lg for lg in rcpt["logs"]
               if lg["address"].lower() == EXCHANGE.lower() and len(lg["topics"]) == 4]
    if not of_logs:
        continue
    makers_takers = set()
    asset_ids = set()
    for lg in of_logs:
        maker = "0x" + lg["topics"][2].hex()[-40:]
        taker = "0x" + lg["topics"][3].hex()[-40:]
        makers_takers.add(maker.lower()); makers_takers.add(taker.lower())
        # data: makerAssetId, takerAssetId, makerAmountFilled, takerAmountFilled, fee
        data = bytes(lg["data"])
        try:
            mAsset, tAsset, mAmt, tAmt, fee = abi_decode(
                ["uint256","uint256","uint256","uint256","uint256"], data)
            if mAsset: asset_ids.add(str(mAsset))
            if tAsset: asset_ids.add(str(tAsset))
        except Exception as e:
            pass
    match = pw in makers_takers
    print(f"\ntx={h[:18]}  proxyWallet={pw[:14]}")
    print(f"  OrderFilled maker/taker set ({len(makers_takers)}): "
          f"{[m[:14] for m in list(makers_takers)[:6]]}")
    print(f"  proxyWallet in maker/taker set? {'YES ✓' if match else 'NO'}")
    print(f"  asset ids seen: {[a[:18]+'...' for a in list(asset_ids)[:3]]}")
    checked += 1
    if checked >= 5:
        break

print("\nIf proxyWallet appears in maker/taker on these, we can subscribe to")
print("OrderFilled logs filtered by our 300 target wallets (indexed topics).")
