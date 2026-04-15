"""
One-time setup: approve the Polymarket CLOB contracts to spend USDC from proxy wallet.
Required before any order can be placed. Safe to run multiple times.

Run: .venv\Scripts\python.exe setup_allowances.py
"""
import os
from dotenv import load_dotenv
load_dotenv()

from src.bot.clob_auth import get_client
from eth_account import Account

key = os.environ.get("POLYMARKET_PRIVATE_KEY", "").strip()
if not key.startswith("0x"):
    key = "0x" + key

eoa = Account.from_key(key).address
print(f"Signing wallet (EOA) : {eoa}")

client = get_client()

# Print the proxy wallet address Polymarket derives from this key
try:
    proxy = client.get_address()
    print(f"Proxy wallet address : {proxy}")
    print(f"Expected             : 0x0529A7b9bf204488aDF0119D6E70a879bD9C44BB")
    if proxy.lower() == "0x0529A7b9bf204488aDF0119D6E70a879bD9C44BB".lower():
        print("✅ Proxy address matches your Polymarket account")
    else:
        print("⚠️  Proxy address mismatch — wrong private key")
except Exception as e:
    print(f"Could not get proxy address: {e}")

# Check current balance and allowance
print("\nChecking balance/allowance...")
try:
    bal = client.get_balance_allowance()
    print(f"Balance/allowance response: {bal}")
except Exception as e:
    print(f"Could not check balance: {e}")

# Set allowances — approves CLOB contracts to spend USDC
# This sends a Polygon transaction and requires a small amount of MATIC for gas
print("\nSetting CLOB allowances (one-time on-chain tx, needs MATIC for gas)...")
try:
    result = client.set_allowances()
    print(f"✅ Allowances set: {result}")
except Exception as e:
    print(f"Error setting allowances: {e}")
    print("\nIf this failed due to insufficient MATIC, you need a small amount of")
    print("MATIC on Polygon in your signing wallet for gas:")
    print(f"  Send MATIC to: {eoa}")
    print("  ~0.5 MATIC is more than enough (~$0.10)")
