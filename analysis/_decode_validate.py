"""Validate the on-chain OrderFilled decoder against data-api ground truth.

For recent data-api trades (which give true side/outcome/price/wallet), fetch
the tx receipt, decode the OrderFilled log for that wallet, and check our
derived (side, outcome, price) matches. We must match before going live.

OrderFilled(bytes32 orderHash, address maker, address taker,
            uint256 makerAssetId, uint256 takerAssetId,
            uint256 makerAmountFilled, uint256 takerAmountFilled, uint256 fee)
  indexed: orderHash, maker, taker  -> topics[1],[2],[3]
  data (non-indexed): makerAssetId, takerAssetId, makerAmt, takerAmt, fee

Semantics (maker order's perspective):
  makerAssetId = asset the maker GAVE; takerAssetId = asset the maker RECEIVED.
  USDC/collateral asset id == 0.
  - makerAssetId==0  -> maker paid USDC, received token  => maker BOUGHT token
      price = makerAmt / takerAmt ; shares = takerAmt
  - takerAssetId==0  -> maker gave token, received USDC  => maker SOLD token
      price = takerAmt / makerAmt ; shares = makerAmt
Amounts are 6-decimals (both USDC and shares).
"""
from __future__ import annotations
import time, requests
from pathlib import Path
import pandas as pd
from web3 import Web3
from eth_abi import decode as abi_decode

ROOT = Path(__file__).resolve().parents[1]
ES_DIR = ROOT / "cowork_snapshot" / "esports"
EXCHANGE = "0x4d97dcd97ec945f40cf65f87097ace5ea0476045".lower()
RPCS = ["https://polygon-bor-rpc.publicnode.com", "https://polygon-rpc.com"]

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

# Build token_id -> (condition_id, outcome) reverse index from the CLOB parquet
print("building token->market reverse index...")
tok2mkt = {}
p = ES_DIR / "clob_esports_markets.parquet"
df = pd.read_parquet(p, columns=["condition_id", "tokens"])
for _, row in df.iterrows():
    cid = row["condition_id"]
    try:
        for t in row["tokens"]:
            tid = str(t.get("token_id")); o = t.get("outcome")
            if tid and o:
                tok2mkt[tid] = (cid, o)
    except TypeError:
        continue
print(f"  indexed {len(tok2mkt)} tokens")

w3 = connect()

OF_SIG = "OrderFilled(bytes32,address,address,uint256,uint256,uint256,uint256,uint256)"
OF_TOPIC = Web3.to_hex(Web3.keccak(text=OF_SIG)).lower()
print(f"OrderFilled topic0 = {OF_TOPIC}")

def is_order_filled(log):
    if log["address"].lower() != EXCHANGE: return False
    if len(log["topics"]) != 4: return False
    return Web3.to_hex(log["topics"][0]).lower() == OF_TOPIC

def decode_orderfilled(log):
    maker = "0x" + log["topics"][2].hex()[-40:]
    taker = "0x" + log["topics"][3].hex()[-40:]
    mAsset, tAsset, mAmt, tAmt, fee = abi_decode(
        ["uint256","uint256","uint256","uint256","uint256"], bytes(log["data"]))
    return maker.lower(), taker.lower(), mAsset, tAsset, mAmt, tAmt

def derive(maker_asset, taker_asset, m_amt, t_amt):
    """Return (side, token_id, price, shares) from the MAKER's perspective."""
    if maker_asset == 0:      # paid USDC, got token -> BUY
        token = str(taker_asset); usdc = m_amt; shares = t_amt; side = "BUY"
    elif taker_asset == 0:    # gave token, got USDC -> SELL
        token = str(maker_asset); usdc = t_amt; shares = m_amt; side = "SELL"
    else:
        return None
    if shares == 0: return None
    price = usdc / shares  # both 6-dec, ratio is unitless
    return side, token, round(price, 3), shares / 1e6

# Pull recent trades, validate
trades = requests.get("https://data-api.polymarket.com/trades",
                      params={"limit": 120}, timeout=10).json()
ok = miss = nodecode = 0
samples = 0
for t in trades:
    h = t.get("transactionHash"); pw = (t.get("proxyWallet") or "").lower()
    if not h or not pw: continue
    try:
        rcpt = w3.eth.get_transaction_receipt(h)
    except Exception:
        continue
    # find OrderFilled logs where our wallet is the MAKER (topics[2])
    matched = None
    for lg in rcpt["logs"]:
        if not is_order_filled(lg): continue
        maker, taker, mA, tA, mAmt, tAmt = decode_orderfilled(lg)
        if maker == pw:
            d = derive(mA, tA, mAmt, tAmt)
            if d:
                matched = d; break
    if matched is None:
        nodecode += 1
        continue
    side, token, price, shares = matched
    cid_out = tok2mkt.get(token)
    samples += 1
    api_side = (t.get("side") or "").upper()
    api_price = float(t.get("price") or 0)
    api_outcome = t.get("outcome")
    dec_outcome = cid_out[1] if cid_out else "?"
    side_ok = side == api_side
    price_ok = abs(price - api_price) <= 0.02
    out_ok = (dec_outcome == api_outcome)
    good = side_ok and price_ok and out_ok
    ok += good; miss += (not good)
    if samples <= 12:
        flag = "OK" if good else "MISMATCH"
        print(f"  {flag}  api[{api_side} {api_outcome} @{api_price}] "
              f"decoded[{side} {dec_outcome} @{price}] shares={shares:.1f}"
              f"{'' if cid_out else '  (token not in index)'}")

print(f"\nvalidated {samples} maker-side trades: {ok} match, {miss} mismatch, "
      f"{nodecode} had no decodable maker log")
print(f"match rate: {ok/max(samples,1)*100:.0f}%")
