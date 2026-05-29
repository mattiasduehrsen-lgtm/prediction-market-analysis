"""Validate full on-chain decode (side+outcome+price) vs data-api ground truth.

Signal source = ERC1155 TransferSingle on the Polymarket Conditional Tokens
contract (0x4d97...6045), topic0 = keccak(TransferSingle(...)).
  topics: [operator, from, to];  data: [id, value]
  to==target   -> BUY   (received shares)
  from==target -> SELL  (sent shares)
  shares = value / 1e6 ; token_id = id

Price from the USDC ERC20 Transfer (0x2791bca1...) touching the target in the
same tx:  price = usdc_amount / shares  (both 6-dec).
"""
from __future__ import annotations
import requests
from pathlib import Path
import pandas as pd
from web3 import Web3
from eth_abi import decode as abi_decode

ROOT = Path(__file__).resolve().parents[1]
ES_DIR = ROOT / "cowork_snapshot" / "esports"
CTF = "0x4d97dcd97ec945f40cf65f87097ace5ea0476045".lower()
USDC = "0x2791bca1f2de4661ed88a30c99a7a9449aa84174".lower()
TRANSFER_SINGLE = Web3.to_hex(Web3.keccak(text="TransferSingle(address,address,address,uint256,uint256)")).lower()
ERC20_TRANSFER  = Web3.to_hex(Web3.keccak(text="Transfer(address,address,uint256)")).lower()
RPCS = ["https://polygon-bor-rpc.publicnode.com", "https://polygon-rpc.com"]

def connect():
    for url in RPCS:
        w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 12}))
        try:
            from web3.middleware import ExtraDataToPOAMiddleware
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        except Exception: pass
        if w3.is_connected(): print(f"connected {url}"); return w3
    raise SystemExit("no rpc")

print(f"TransferSingle topic0 = {TRANSFER_SINGLE}")
tok2mkt = {}
df = pd.read_parquet(ES_DIR/"clob_esports_markets.parquet", columns=["condition_id","tokens"])
for _, row in df.iterrows():
    try:
        for t in row["tokens"]:
            if t.get("token_id") and t.get("outcome"):
                tok2mkt[str(t["token_id"])] = (row["condition_id"], t["outcome"])
    except TypeError: pass
print(f"indexed {len(tok2mkt)} tokens")
w3 = connect()

def topic_addr(tp):
    return "0x"+Web3.to_hex(tp)[-40:]

trades = requests.get("https://data-api.polymarket.com/trades", params={"limit":150}, timeout=10).json()
ok=miss=skip=0; samples=0
for t in trades:
    h=t.get("transactionHash"); pw=(t.get("proxyWallet") or "").lower()
    if not h or not pw: continue
    try: rcpt=w3.eth.get_transaction_receipt(h)
    except Exception: continue

    # 1) find TransferSingle on CTF touching PW
    ts_hit=None
    for lg in rcpt["logs"]:
        if lg["address"].lower()!=CTF: continue
        if len(lg["topics"])!=4: continue
        if Web3.to_hex(lg["topics"][0]).lower()!=TRANSFER_SINGLE: continue
        frm=topic_addr(lg["topics"][2]); to=topic_addr(lg["topics"][3])
        if pw not in (frm.lower(), to.lower()): continue
        tid, val = abi_decode(["uint256","uint256"], bytes(lg["data"]))
        side = "BUY" if to.lower()==pw else "SELL"
        ts_hit=(side, str(tid), val/1e6)
        break
    if not ts_hit:
        skip+=1; continue
    side, token, shares = ts_hit
    if shares<=0: skip+=1; continue

    # 2) USDC transfer touching PW -> price
    usdc=0.0
    for lg in rcpt["logs"]:
        if lg["address"].lower()!=USDC: continue
        if len(lg["topics"])!=3: continue
        if Web3.to_hex(lg["topics"][0]).lower()!=ERC20_TRANSFER: continue
        frm=topic_addr(lg["topics"][1]).lower(); to=topic_addr(lg["topics"][2]).lower()
        if pw not in (frm,to): continue
        (amt,)=abi_decode(["uint256"], bytes(lg["data"]))
        usdc=max(usdc, amt/1e6)   # take the PW-side USDC leg
    price = round(usdc/shares,3) if shares else 0

    cid_out=tok2mkt.get(token)
    dec_out=cid_out[1] if cid_out else "?"
    api_side=(t.get("side") or "").upper(); api_price=float(t.get("price") or 0)
    api_out=t.get("outcome")
    samples+=1
    side_ok=side==api_side
    price_ok=abs(price-api_price)<=0.02
    out_ok=(dec_out==api_out) or cid_out is None
    good=side_ok and price_ok and out_ok
    ok+=good; miss+=(not good)
    if samples<=18:
        f="OK " if good else "MISS"
        intok="" if cid_out else " (non-esports token)"
        print(f"  {f} api[{api_side:<4}{str(api_out)[:14]:<15}@{api_price:<5}] "
              f"dec[{side:<4}{dec_out[:14]:<15}@{price:<5}] sh={shares:>6.1f}{intok}")
print(f"\nvalidated {samples}: {ok} match, {miss} mismatch, {skip} no-transfer. "
      f"match={ok/max(samples,1)*100:.0f}%")
