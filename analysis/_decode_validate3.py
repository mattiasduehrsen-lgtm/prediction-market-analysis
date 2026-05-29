"""Validate decode on ESPORTS trades specifically: side + outcome (token index)
+ price via CLOB midpoint. This is the exact path the live listener will use.
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
TRANSFER_SINGLE = Web3.to_hex(Web3.keccak(text="TransferSingle(address,address,address,uint256,uint256)")).lower()
RPCS = ["https://polygon-bor-rpc.publicnode.com", "https://polygon-rpc.com"]
S = requests.Session()

def connect():
    for url in RPCS:
        w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 12}))
        try:
            from web3.middleware import ExtraDataToPOAMiddleware
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        except Exception: pass
        if w3.is_connected(): print(f"connected {url}"); return w3
    raise SystemExit("no rpc")

tok2mkt = {}
df = pd.read_parquet(ES_DIR/"clob_esports_markets.parquet", columns=["condition_id","tokens"])
for _, row in df.iterrows():
    try:
        for t in row["tokens"]:
            if t.get("token_id") and t.get("outcome"):
                tok2mkt[str(t["token_id"])] = (row["condition_id"], t["outcome"])
    except TypeError: pass
print(f"indexed {len(tok2mkt)} esports tokens")
w3 = connect()

def topic_addr(tp): return "0x"+Web3.to_hex(tp)[-40:]

def clob_midpoint(token_id):
    try:
        r = S.get("https://clob.polymarket.com/midpoint", params={"token_id": token_id}, timeout=5)
        if r.status_code==200:
            return float(r.json().get("mid"))
    except Exception: pass
    return None

# Pull a big batch, keep esports slugs
trades = S.get("https://data-api.polymarket.com/trades", params={"limit":1000}, timeout=15).json()
es = [t for t in trades if (t.get("slug","") or "").lower().startswith(("cs2-","csgo-","league-"))]
print(f"esports trades in batch: {len(es)} of {len(trades)}")

ok=miss=skip=0; samples=0
for t in es:
    h=t.get("transactionHash"); pw=(t.get("proxyWallet") or "").lower()
    if not h or not pw: continue
    try: rcpt=w3.eth.get_transaction_receipt(h)
    except Exception: continue
    hit=None
    for lg in rcpt["logs"]:
        if lg["address"].lower()!=CTF or len(lg["topics"])!=4: continue
        if Web3.to_hex(lg["topics"][0]).lower()!=TRANSFER_SINGLE: continue
        frm=topic_addr(lg["topics"][2]).lower(); to=topic_addr(lg["topics"][3]).lower()
        if pw not in (frm,to): continue
        tid,val=abi_decode(["uint256","uint256"], bytes(lg["data"]))
        hit=("BUY" if to==pw else "SELL", str(tid), val/1e6); break
    if not hit: skip+=1; continue
    side,token,shares=hit
    cid_out=tok2mkt.get(token)
    if not cid_out: skip+=1; continue
    dec_out=cid_out[1]
    mid=clob_midpoint(token)
    their_price = mid if mid is not None else 0
    api_side=(t.get("side") or "").upper(); api_out=t.get("outcome"); api_price=float(t.get("price") or 0)
    samples+=1
    side_ok=side==api_side; out_ok=dec_out==api_out
    # price: CLOB midpoint NOW vs their fill price THEN (will differ a bit; just sanity)
    price_close = abs(their_price-api_price)<=0.10 if mid is not None else False
    good=side_ok and out_ok
    ok+=good; miss+=(not good)
    if samples<=20:
        f="OK " if good else "MISS"
        print(f"  {f} api[{api_side:<4}{str(api_out)[:16]:<17}@{api_price:<5}] "
              f"dec[{side:<4}{dec_out[:16]:<17}] mid={their_price}  sideOK={side_ok} outOK={out_ok} priceClose={price_close}")
print(f"\nesports validated {samples}: {ok} side+outcome match, {miss} mismatch, {skip} skipped")
print(f"side+outcome match rate: {ok/max(samples,1)*100:.0f}%")
