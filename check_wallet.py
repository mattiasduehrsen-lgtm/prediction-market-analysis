"""Print the wallet address derived from POLYMARKET_PRIVATE_KEY in .env"""
import os
from dotenv import load_dotenv
load_dotenv()
from eth_account import Account

key = os.environ.get("POLYMARKET_PRIVATE_KEY", "").strip()
if not key:
    print("ERROR: POLYMARKET_PRIVATE_KEY not set")
else:
    if not key.startswith("0x"):
        key = "0x" + key
    acc = Account.from_key(key)
    print(f"Wallet address: {acc.address}")
    print(f"(This is the address that must hold USDC on Polygon in Polymarket)")
