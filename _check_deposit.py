"""Track for incoming USDC: pUSD balance + USDC.e ERC20 + recent inbound transfers."""
import os, contextlib, io as _io, requests
from dotenv import load_dotenv
load_dotenv()
proxy = os.getenv("POLYMARKET_PROXY_ADDRESS")

# 1. pUSD via CLOB SDK
from py_clob_client_v2 import ClobClient, BalanceAllowanceParams, AssetType
with contextlib.redirect_stderr(_io.StringIO()):
    c = ClobClient("https://clob.polymarket.com",
                   key=os.getenv("POLYMARKET_PRIVATE_KEY"),
                   chain_id=137, signature_type=2, funder=proxy)
    c.set_api_creds(c.create_or_derive_api_key())
    b = c.get_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
pusd = int(b.get("balance", 0)) / 1e6
print(f"pUSD (Polymarket collateral): ${pusd:.4f}")

# 2. Native USDC and USDC.e on Polygon (in case USDC arrives but doesn't auto-wrap)
RPCS = ["https://polygon-bor-rpc.publicnode.com", "https://polygon.drpc.org"]
TOKENS = {
    "USDC.e": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
    "USDC native": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
}
pad = proxy.lower().replace("0x","").rjust(64,"0")
for name, addr in TOKENS.items():
    for rpc in RPCS:
        try:
            r = requests.post(rpc, json={"jsonrpc":"2.0","method":"eth_call",
                                         "params":[{"to":addr,"data":"0x70a08231"+pad},"latest"],"id":1},
                              timeout=8).json()
            raw = r.get("result", "0x0") or "0x0"
            bal = int(raw, 16) / 1e6 if raw not in ("0x", "0x0") else 0
            print(f"{name:<14} on-chain: ${bal:.4f}")
            break
        except Exception:
            continue

# 3. Live position value
try:
    r = requests.get(f"https://data-api.polymarket.com/value?user={proxy}", timeout=8).json()
    pos = float(r[0]["value"]) if r else 0
    print(f"Open positions val:           ${pos:.4f}")
    print(f"TOTAL on-platform (pUSD+pos): ${pusd + pos:.2f}")
except Exception as e:
    print(f"position value: {e}")
