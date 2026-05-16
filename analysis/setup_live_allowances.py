"""
One-time on-chain allowance setup for the esports fade bot (standard CTF Exchange).

py_clob_client_v2 dropped the v1 set_allowances() helper. This script does the
two on-chain approvals manually via the Gnosis Safe execTransaction pattern
(same machinery as redeem_positions.py):

  1. USDC.approve(CTF_Exchange, max_uint256)         # so exchange can pull USDC for BUYs
  2. CTF.setApprovalForAll(CTF_Exchange, true)       # so exchange can move shares for SELLs

Both txs are sent from the EOA owner (POLYMARKET_PRIVATE_KEY) through the Safe
proxy (POLYMARKET_PROXY_ADDRESS). Requires ~0.15 MATIC for gas in the EOA.

Usage:
  .venv\\Scripts\\python.exe analysis\\setup_live_allowances.py            # dry-run
  .venv\\Scripts\\python.exe analysis\\setup_live_allowances.py --confirm  # actually send the txs
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

# Polygon contract addresses
USDC_ADDR    = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"   # USDC on Polygon
CTF_ADDR     = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"   # Polymarket Conditional Tokens
CTF_EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"   # standard CTF Exchange (esports markets)
MAX_UINT256  = 2**256 - 1

POLYGON_RPCS = [
    os.environ.get("POLYGON_RPC", "").strip() or None,
    "https://polygon-bor-rpc.publicnode.com",
    "https://polygon.llamarpc.com",
    "https://1rpc.io/matic",
    "https://polygon.drpc.org",
    "https://rpc.ankr.com/polygon",
]
POLYGON_RPCS = [r for r in POLYGON_RPCS if r]


def _connect_polygon():
    from web3 import Web3
    for url in POLYGON_RPCS:
        try:
            w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 8}))
            if w3.eth.chain_id == 137:
                print(f"  Connected via {url}")
                return w3
        except Exception:
            continue
    return None


# Minimal ABIs
ERC20_ABI = [{
    "name": "approve", "type": "function", "stateMutability": "nonpayable",
    "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
    "outputs": [{"type": "bool"}],
}, {
    "name": "allowance", "type": "function", "stateMutability": "view",
    "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}],
    "outputs": [{"type": "uint256"}],
}]

CTF_ABI_LOCAL = [{
    "name": "setApprovalForAll", "type": "function", "stateMutability": "nonpayable",
    "inputs": [{"name": "operator", "type": "address"}, {"name": "approved", "type": "bool"}],
    "outputs": [],
}, {
    "name": "isApprovedForAll", "type": "function", "stateMutability": "view",
    "inputs": [{"name": "owner", "type": "address"}, {"name": "operator", "type": "address"}],
    "outputs": [{"type": "bool"}],
}]


def safe_exec_transaction(w3, safe_address: str, eoa_key: str,
                          to: str, value: int, data_hex: str):
    """Submit a Gnosis Safe execTransaction. 1-of-1 Safe only."""
    from eth_account import Account
    from eth_account.messages import encode_typed_data
    from web3 import Web3

    SAFE_ABI = [
        {"name": "nonce", "type": "function", "stateMutability": "view",
         "inputs": [], "outputs": [{"type": "uint256"}]},
        {"name": "getOwners", "type": "function", "stateMutability": "view",
         "inputs": [], "outputs": [{"type": "address[]"}]},
        {"name": "getThreshold", "type": "function", "stateMutability": "view",
         "inputs": [], "outputs": [{"type": "uint256"}]},
        {"name": "execTransaction", "type": "function", "stateMutability": "payable",
         "inputs": [
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
            {"name": "data", "type": "bytes"},
            {"name": "operation", "type": "uint8"},
            {"name": "safeTxGas", "type": "uint256"},
            {"name": "baseGas", "type": "uint256"},
            {"name": "gasPrice", "type": "uint256"},
            {"name": "gasToken", "type": "address"},
            {"name": "refundReceiver", "type": "address"},
            {"name": "signatures", "type": "bytes"},
         ],
         "outputs": [{"type": "bool"}]},
    ]
    safe = w3.eth.contract(address=Web3.to_checksum_address(safe_address), abi=SAFE_ABI)
    acct = Account.from_key(eoa_key)

    owners = safe.functions.getOwners().call()
    threshold = safe.functions.getThreshold().call()
    if acct.address.lower() not in [o.lower() for o in owners]:
        print(f"  ABORT: EOA {acct.address} is not a Safe owner")
        return None
    if threshold != 1:
        print(f"  ABORT: Safe threshold is {threshold}, only 1-of-1 supported")
        return None

    nonce = safe.functions.nonce().call()
    domain = {"verifyingContract": Web3.to_checksum_address(safe_address),
              "chainId": w3.eth.chain_id}
    types = {
        "EIP712Domain": [
            {"name": "chainId", "type": "uint256"},
            {"name": "verifyingContract", "type": "address"},
        ],
        "SafeTx": [
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
            {"name": "data", "type": "bytes"},
            {"name": "operation", "type": "uint8"},
            {"name": "safeTxGas", "type": "uint256"},
            {"name": "baseGas", "type": "uint256"},
            {"name": "gasPrice", "type": "uint256"},
            {"name": "gasToken", "type": "address"},
            {"name": "refundReceiver", "type": "address"},
            {"name": "nonce", "type": "uint256"},
        ],
    }
    message = {
        "to":             Web3.to_checksum_address(to),
        "value":          value,
        "data":           bytes.fromhex(data_hex.replace("0x", "")),
        "operation":      0,
        "safeTxGas":      0,
        "baseGas":        0,
        "gasPrice":       0,
        "gasToken":       "0x0000000000000000000000000000000000000000",
        "refundReceiver": "0x0000000000000000000000000000000000000000",
        "nonce":          nonce,
    }
    encoded = encode_typed_data(
        domain_data=domain,
        message_types={"SafeTx": types["SafeTx"]},
        message_data=message,
    )
    signed = acct.sign_message(encoded)
    sig = signed.signature.hex()

    fn = safe.functions.execTransaction(
        Web3.to_checksum_address(to), value,
        bytes.fromhex(data_hex.replace("0x", "")),
        0, 0, 0, 0,
        "0x0000000000000000000000000000000000000000",
        "0x0000000000000000000000000000000000000000",
        bytes.fromhex(sig.replace("0x", "")),
    )
    gas_estimate = fn.estimate_gas({"from": acct.address})
    tx = fn.build_transaction({
        "from":     acct.address,
        "nonce":    w3.eth.get_transaction_count(acct.address),
        "gas":      int(gas_estimate * 1.3),
        "gasPrice": w3.eth.gas_price,
    })
    signed_tx = acct.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction).hex()
    print(f"  tx sent: 0x{tx_hash}")
    # Wait for confirmation
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    print(f"  confirmed in block {receipt['blockNumber']}, status={receipt['status']}")
    return tx_hash if receipt['status'] == 1 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true", help="Actually send the txs (default: dry-run)")
    args = ap.parse_args()

    from web3 import Web3
    from eth_account import Account

    safe_addr = os.environ.get("POLYMARKET_PROXY_ADDRESS", "").strip()
    pk = os.environ.get("POLYMARKET_PRIVATE_KEY", "").strip()
    if not pk.startswith("0x"):
        pk = "0x" + pk
    if not safe_addr or not pk:
        print("ABORT: .env missing POLYMARKET_PROXY_ADDRESS or POLYMARKET_PRIVATE_KEY")
        sys.exit(1)
    eoa_addr = Account.from_key(pk).address

    print(f"Safe (proxy)  : {safe_addr}")
    print(f"EOA (signer)  : {eoa_addr}")
    print(f"CTF Exchange  : {CTF_EXCHANGE}")
    print()

    print("Connecting to Polygon...")
    w3 = _connect_polygon()
    if w3 is None:
        print("ABORT: no Polygon RPC available")
        sys.exit(1)

    # Check current allowance state
    usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC_ADDR), abi=ERC20_ABI)
    ctf  = w3.eth.contract(address=Web3.to_checksum_address(CTF_ADDR), abi=CTF_ABI_LOCAL)
    cur_usdc_allow = usdc.functions.allowance(
        Web3.to_checksum_address(safe_addr),
        Web3.to_checksum_address(CTF_EXCHANGE)
    ).call()
    cur_ctf_approved = ctf.functions.isApprovedForAll(
        Web3.to_checksum_address(safe_addr),
        Web3.to_checksum_address(CTF_EXCHANGE)
    ).call()
    print(f"\nCurrent state:")
    print(f"  USDC.allowance(Safe, CTF_Exchange)  : {cur_usdc_allow}")
    print(f"  CTF.isApprovedForAll(Safe, Exchange): {cur_ctf_approved}")

    need_usdc = cur_usdc_allow < 10**12  # less than $1M = needs approval
    need_ctf  = not cur_ctf_approved

    if not need_usdc and not need_ctf:
        print("\nBoth approvals already set. Nothing to do.")
        sys.exit(0)

    print(f"\nApprovals needed:")
    if need_usdc: print(f"  - USDC.approve(CTF_Exchange, max)")
    if need_ctf:  print(f"  - CTF.setApprovalForAll(CTF_Exchange, true)")

    if not args.confirm:
        print("\nDRY RUN. Re-run with --confirm to actually send the txs.")
        print("Each tx costs ~0.06 MATIC gas (~$0.05).")
        sys.exit(0)

    # Check EOA has MATIC
    matic = w3.eth.get_balance(eoa_addr) / 1e18
    print(f"\nEOA MATIC balance: {matic:.4f}")
    need_matic = 0.15 if (need_usdc and need_ctf) else 0.08
    if matic < need_matic:
        print(f"ABORT: need at least {need_matic} MATIC, have {matic:.4f}")
        print(f"  Send some MATIC to {eoa_addr} on Polygon (~$0.30 worth)")
        sys.exit(1)

    if need_usdc:
        print("\n--- Tx 1: USDC.approve(CTF_Exchange, max) ---")
        data = usdc.encode_abi("approve",
            args=[Web3.to_checksum_address(CTF_EXCHANGE), MAX_UINT256])
        tx_hash = safe_exec_transaction(w3, safe_addr, pk, USDC_ADDR, 0, data)
        if not tx_hash:
            print("  Failed — aborting before second tx")
            sys.exit(1)
        time.sleep(3)

    if need_ctf:
        print("\n--- Tx 2: CTF.setApprovalForAll(CTF_Exchange, true) ---")
        data = ctf.encode_abi("setApprovalForAll",
            args=[Web3.to_checksum_address(CTF_EXCHANGE), True])
        tx_hash = safe_exec_transaction(w3, safe_addr, pk, CTF_ADDR, 0, data)
        if not tx_hash:
            print("  Failed")
            sys.exit(1)

    # Verify
    print("\n--- Verifying ---")
    time.sleep(3)
    cur_usdc_allow = usdc.functions.allowance(
        Web3.to_checksum_address(safe_addr),
        Web3.to_checksum_address(CTF_EXCHANGE)
    ).call()
    cur_ctf_approved = ctf.functions.isApprovedForAll(
        Web3.to_checksum_address(safe_addr),
        Web3.to_checksum_address(CTF_EXCHANGE)
    ).call()
    print(f"  USDC.allowance  : {cur_usdc_allow} ({'OK' if cur_usdc_allow > 10**12 else 'FAILED'})")
    print(f"  CTF.isApprovedForAll: {cur_ctf_approved} ({'OK' if cur_ctf_approved else 'FAILED'})")
    print()
    if cur_usdc_allow > 10**12 and cur_ctf_approved:
        print("DONE. Bot can now place LIVE orders on standard markets.")
    else:
        print("Some approvals didn't take. Re-run --confirm.")


if __name__ == "__main__":
    main()
