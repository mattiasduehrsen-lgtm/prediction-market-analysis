"""Find a working public Polygon RPC."""
from web3 import Web3
from eth_account import Account
import os
from dotenv import load_dotenv
load_dotenv()

candidates = [
    "https://polygon-bor-rpc.publicnode.com",
    "https://polygon.llamarpc.com",
    "https://1rpc.io/matic",
    "https://rpc.ankr.com/polygon",
    "https://polygon-rpc.com",
    "https://polygon.drpc.org",
]
SAFE_ABI = [
    {"name": "nonce", "type": "function", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "uint256"}]},
    {"name": "getOwners", "type": "function", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "address[]"}]},
    {"name": "getThreshold", "type": "function", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "uint256"}]},
]
safe_addr = os.environ["POLYMARKET_PROXY_ADDRESS"]

for url in candidates:
    try:
        w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 6}))
        if not w3.is_connected():
            print(f"  {url:60s} FAIL connect")
            continue
        safe = w3.eth.contract(address=Web3.to_checksum_address(safe_addr), abi=SAFE_ABI)
        nonce = safe.functions.nonce().call()
        owners = safe.functions.getOwners().call()
        threshold = safe.functions.getThreshold().call()
        print(f"  {url:60s} OK  chain={w3.eth.chain_id} safe_nonce={nonce} owners={len(owners)} threshold={threshold}")
        pk = os.environ.get("POLYMARKET_PRIVATE_KEY", "")
        if pk and not pk.startswith("0x"):
            pk = "0x" + pk
        if pk:
            eoa = Account.from_key(pk).address
            print(f"    EOA={eoa}  is_owner={eoa.lower() in [o.lower() for o in owners]}")
        break  # first working one is enough
    except Exception as e:
        print(f"  {url:60s} FAIL: {type(e).__name__}: {str(e)[:50]}")
