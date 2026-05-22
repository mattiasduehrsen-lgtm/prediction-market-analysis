"""Quick: current pUSD + open position value."""
import os, contextlib, io as _io
import requests
from dotenv import load_dotenv
load_dotenv()
proxy = os.getenv("POLYMARKET_PROXY_ADDRESS")
from py_clob_client_v2 import ClobClient, BalanceAllowanceParams, AssetType
with contextlib.redirect_stderr(_io.StringIO()):
    c = ClobClient("https://clob.polymarket.com",
                   key=os.getenv("POLYMARKET_PRIVATE_KEY"),
                   chain_id=137, signature_type=2, funder=proxy)
    c.set_api_creds(c.create_or_derive_api_key())
    b = c.get_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
cash = int(b.get("balance", 0)) / 1e6
r = requests.get(f"https://data-api.polymarket.com/value?user={proxy}", timeout=8).json()
pos = float(r[0]["value"]) if r else 0
print(f"pUSD cash:           ${cash:.2f}")
print(f"Open positions val:  ${pos:.2f}")
print(f"TOTAL on-platform:   ${cash + pos:.2f}")
