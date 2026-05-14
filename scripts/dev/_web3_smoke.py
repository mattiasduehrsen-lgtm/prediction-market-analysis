"""Smoke test for web3 + eth_account before running redeem."""
from web3 import Web3
from eth_account.messages import encode_typed_data
from eth_account import Account

w3 = Web3(Web3.HTTPProvider("https://polygon-rpc.com", request_kwargs={"timeout": 10}))
print(f"connected: {w3.is_connected()}, chain_id: {w3.eth.chain_id}")

# Test encode_typed_data signature
try:
    encoded = encode_typed_data(
        domain_data={"chainId": 137, "verifyingContract": "0x0000000000000000000000000000000000000000"},
        message_types={"X": [{"name": "v", "type": "uint256"}]},
        message_data={"v": 1},
    )
    print("encode_typed_data: OK")
except Exception as e:
    print(f"encode_typed_data error: {e}")

# Test reading Safe contract
SAFE_ABI = [
    {"name": "nonce", "type": "function", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "uint256"}]},
    {"name": "getOwners", "type": "function", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "address[]"}]},
    {"name": "getThreshold", "type": "function", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "uint256"}]},
]
import os
from dotenv import load_dotenv
load_dotenv()
safe_addr = os.environ.get("POLYMARKET_PROXY_ADDRESS")
print(f"\nSafe (proxy): {safe_addr}")
safe = w3.eth.contract(address=Web3.to_checksum_address(safe_addr), abi=SAFE_ABI)
try:
    nonce = safe.functions.nonce().call()
    owners = safe.functions.getOwners().call()
    threshold = safe.functions.getThreshold().call()
    print(f"  Safe nonce: {nonce}")
    print(f"  Safe owners ({len(owners)}, threshold={threshold}): {owners}")

    pk = os.environ.get("POLYMARKET_PRIVATE_KEY", "")
    if pk and not pk.startswith("0x"):
        pk = "0x" + pk
    if pk:
        eoa = Account.from_key(pk).address
        print(f"  Our EOA: {eoa}")
        print(f"  EOA-is-owner: {eoa.lower() in [o.lower() for o in owners]}")
except Exception as e:
    print(f"  ERROR: {e}")
