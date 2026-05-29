"""Dump ALL exchange logs for a few trades, fully, to learn the real structure."""
from __future__ import annotations
import requests
from web3 import Web3
from eth_abi import decode as abi_decode

EXCHANGE = "0x4d97dcd97ec945f40cf65f87097ace5ea0476045".lower()
RPCS = ["https://polygon-bor-rpc.publicnode.com", "https://polygon-rpc.com"]
def connect():
    for url in RPCS:
        w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 12}))
        try:
            from web3.middleware import ExtraDataToPOAMiddleware
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        except Exception: pass
        if w3.is_connected(): return w3
    raise SystemExit("no rpc")
w3 = connect()

trades = requests.get("https://data-api.polymarket.com/trades", params={"limit":60}, timeout=10).json()
shown = 0
for t in trades:
    h = t.get("transactionHash"); pw = (t.get("proxyWallet") or "").lower()
    if not h or not pw: continue
    rcpt = w3.eth.get_transaction_receipt(h)
    ex_logs = [lg for lg in rcpt["logs"] if lg["address"].lower()==EXCHANGE]
    if not ex_logs: continue
    print("="*92)
    print(f"tx {h[:20]}  proxyWallet={pw}")
    print(f"  data-api: side={t.get('side')} outcome={t.get('outcome')} "
          f"price={t.get('price')} size={t.get('size')} cond={t.get('conditionId','')[:18]}")
    print(f"  {len(ex_logs)} exchange logs:")
    for lg in ex_logs:
        topic0 = Web3.to_hex(lg["topics"][0])
        nt = len(lg["topics"])
        dlen = len(bytes(lg["data"]))
        addrs = []
        for tp in lg["topics"][1:]:
            hx = Web3.to_hex(tp)
            # address-looking topic?
            if hx[:26] == "0x000000000000000000000000":
                addrs.append("0x"+hx[-40:])
            else:
                addrs.append(hx[:14]+"..")
        pw_here = any(a.lower()==pw for a in addrs)
        # try decode data as N uint256
        decoded = ""
        if dlen % 32 == 0 and dlen>0:
            try:
                vals = abi_decode(["uint256"]*(dlen//32), bytes(lg["data"]))
                # show compactly: 0 stays 0, big numbers truncated
                show=[]
                for v in vals:
                    if v==0: show.append("0")
                    elif v < 10**9: show.append(str(v))
                    else: show.append(str(v)[:6]+f"..({len(str(v))}d)")
                decoded = " ".join(show)
            except Exception as e:
                decoded = f"(decode err)"
        mark = "  <<< PW HERE" if pw_here else ""
        print(f"    topic0=…{topic0[-14:]} ntopics={nt} dlen={dlen}{mark}")
        print(f"        topics[1:]={addrs}")
        print(f"        data={decoded}")
    shown += 1
    if shown >= 2: break
