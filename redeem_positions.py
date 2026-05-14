"""
Auto-redeem resolved Polymarket positions.

Phase A — discovery + calldata (default):
  Identifies redeemable positions via Polymarket's data-api, builds the exact
  CTF `redeemPositions(collateralToken, parentCollectionId, conditionId, indexSets)`
  calldata for each, writes a JSON report.

Phase B — execute (require --execute flag, capped at MAX_PER_RUN):
  Sends a Gnosis Safe execTransaction to redeem each position. Requires the
  signing EOA (POLYMARKET_PRIVATE_KEY) to be an owner of the Safe.

Usage:
  .venv\\Scripts\\python.exe redeem_positions.py             # dry-run (default)
  .venv\\Scripts\\python.exe redeem_positions.py --execute   # actually broadcast

Safety rails:
  - MAX_PER_RUN cap (5) — refuses to execute more than 5 redemptions per call
  - Each redemption verified via /positions['redeemable']=True before tx
  - Detailed per-tx logging
  - Failed tx does not block subsequent ones
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
load_dotenv()

ROOT = Path(__file__).resolve().parent

# ── Constants ─────────────────────────────────────────────────────────────────
# RPC fallback chain. polygon-rpc.com rate-limits aggressively; try alternatives.
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
            # Force a real network call to verify
            cid = w3.eth.chain_id
            if cid == 137:
                print(f"  Connected via {url} (chain {cid})")
                return w3
        except Exception as e:
            print(f"  {url} failed: {type(e).__name__}")
    return None
USDC_ADDR   = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"   # USDC on Polygon
CTF_ADDR    = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"   # Polymarket CTF (Conditional Tokens)
NEG_RISK_CTF_ADDR = "0xC5d563A36AE78145C45a50134d48A1215220f80a"  # neg-risk CTF (newer markets)

MAX_PER_RUN  = 5             # cap on broadcast count per --execute invocation
INDEX_SETS   = [1, 2]        # binary outcome — redeem both YES and NO partitions
PARENT_COLL  = "0x" + "00" * 32   # bytes32(0) — top-level positions only


# Minimal CTF ABI: just the redeemPositions function
CTF_ABI = [
    {
        "name": "redeemPositions",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "collateralToken",    "type": "address"},
            {"name": "parentCollectionId", "type": "bytes32"},
            {"name": "conditionId",        "type": "bytes32"},
            {"name": "indexSets",          "type": "uint256[]"},
        ],
        "outputs": [],
    }
]


def fetch_redeemable_positions(address: str) -> list[dict]:
    r = requests.get(
        "https://data-api.polymarket.com/positions",
        params={"user": address, "limit": 200},
        timeout=15,
    )
    r.raise_for_status()
    positions = r.json()
    return [p for p in positions if p.get("redeemable")]


def encode_redeem_calldata(condition_id_hex: str, neg_risk: bool = False) -> tuple[str, dict]:
    """
    Build calldata for CTF.redeemPositions(USDC, 0x00..., conditionId, [1, 2]).
    Returns (calldata_hex, plan_dict) where plan_dict is JSON-safe for the report.
    """
    from web3 import Web3
    w3 = Web3()
    target = NEG_RISK_CTF_ADDR if neg_risk else CTF_ADDR
    ctf = w3.eth.contract(address=Web3.to_checksum_address(target), abi=CTF_ABI)

    # conditionId must be exactly 0x + 64 hex chars (bytes32)
    cid_clean = condition_id_hex.lower().replace("0x", "")
    if len(cid_clean) != 64:
        raise ValueError(f"conditionId not 32 bytes: got {len(cid_clean)//2}")
    cid_bytes = bytes.fromhex(cid_clean)
    parent_bytes = bytes.fromhex("00" * 32)

    data = ctf.encode_abi(
        "redeemPositions",
        args=[
            Web3.to_checksum_address(USDC_ADDR),
            parent_bytes,
            cid_bytes,
            INDEX_SETS,
        ],
    )
    plan = {
        "target":        target,
        "function":      "redeemPositions(address,bytes32,bytes32,uint256[])",
        "collateral":    USDC_ADDR,
        "condition_id":  "0x" + cid_clean,
        "index_sets":    INDEX_SETS,
        "calldata":      data,
    }
    return data, plan


def safe_exec_transaction(
    w3, safe_address: str, eoa_key: str,
    to: str, value: int, data_hex: str,
):
    """
    Submit a Gnosis Safe execTransaction.

    Assumes the Safe is 1-of-1 with the EOA as the only owner (typical for
    Polymarket's auto-generated proxy Safes). For multi-owner Safes this would
    need to collect multiple signatures.
    """
    from eth_account import Account
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
    from web3 import Web3
    safe = w3.eth.contract(address=Web3.to_checksum_address(safe_address), abi=SAFE_ABI)
    acct = Account.from_key(eoa_key)
    print(f"  EOA signer: {acct.address}")

    # Pre-flight: who owns the Safe and what's the threshold?
    try:
        owners = safe.functions.getOwners().call()
        threshold = safe.functions.getThreshold().call()
        print(f"  Safe owners ({len(owners)}, threshold={threshold}): {owners}")
        if acct.address.lower() not in [o.lower() for o in owners]:
            print(f"  ABORT: EOA is not a Safe owner")
            return None
        if threshold != 1:
            print(f"  ABORT: Safe threshold is {threshold}, only 1-of-1 supported in this script")
            return None
    except Exception as e:
        print(f"  ERROR: Safe pre-flight failed: {e}")
        return None

    # For threshold=1, a single owner signature with a special "pre-validated"
    # format works: signature = owner_address_padded + 0x00 + r=0 + v=1
    # Specifically: 32-byte zero r, 32-byte (owner_address as uint256), v=1
    # This is the "approved hash" / "msg.sender" signature.
    # Easier: collect actual ECDSA signature.

    nonce = safe.functions.nonce().call()
    print(f"  Safe nonce: {nonce}")

    # Build Safe transaction hash per EIP-712
    domain = {
        "verifyingContract": Web3.to_checksum_address(safe_address),
        "chainId": w3.eth.chain_id,
    }
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
        "to":              Web3.to_checksum_address(to),
        "value":           value,
        "data":            bytes.fromhex(data_hex.replace("0x", "")),
        "operation":       0,   # CALL
        "safeTxGas":       0,
        "baseGas":         0,
        "gasPrice":        0,
        "gasToken":        "0x0000000000000000000000000000000000000000",
        "refundReceiver":  "0x0000000000000000000000000000000000000000",
        "nonce":           nonce,
    }

    from eth_account.messages import encode_typed_data
    encoded = encode_typed_data(
        domain_data=domain,
        message_types={"SafeTx": types["SafeTx"]},
        message_data=message,
    )
    signed = acct.sign_message(encoded)
    sig = signed.signature.hex()
    print(f"  Signed Safe tx, sig={sig[:20]}...{sig[-8:]}")

    # Now call execTransaction
    fn = safe.functions.execTransaction(
        Web3.to_checksum_address(to),
        value,
        bytes.fromhex(data_hex.replace("0x", "")),
        0, 0, 0, 0,
        "0x0000000000000000000000000000000000000000",
        "0x0000000000000000000000000000000000000000",
        bytes.fromhex(sig.replace("0x", "")),
    )
    gas_estimate = fn.estimate_gas({"from": acct.address})
    print(f"  Gas estimate: {gas_estimate}")

    tx = fn.build_transaction({
        "from":     acct.address,
        "nonce":    w3.eth.get_transaction_count(acct.address),
        "gas":      int(gas_estimate * 1.3),
        "gasPrice": w3.eth.gas_price,
    })
    signed_tx = acct.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction).hex()
    print(f"  Tx sent: 0x{tx_hash}")
    return tx_hash


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true",
                    help="Actually broadcast Safe transactions (default: report only)")
    ap.add_argument("--limit", type=int, default=MAX_PER_RUN,
                    help=f"Cap on positions to redeem this run (default {MAX_PER_RUN}). Use 1 as a canary.")
    args = ap.parse_args()

    addr = os.environ.get("POLYMARKET_PROXY_ADDRESS", "").strip()
    if not addr:
        print("FAIL: POLYMARKET_PROXY_ADDRESS not in .env")
        return 1
    print(f"Safe (proxy): {addr}")
    print(f"Mode: {'EXECUTE' if args.execute else 'DRY-RUN'}\n")

    redeemable = fetch_redeemable_positions(addr)
    print(f"Found {len(redeemable)} redeemable position(s)\n")
    if not redeemable:
        print("(nothing to do)")
        return 0

    plans = []
    for p in redeemable:
        cid = p.get("conditionId") or p.get("condition_id") or ""
        slug = p.get("slug", "")
        size = p.get("size", 0)
        avg  = p.get("avgPrice", p.get("avg_price", 0))
        neg_risk = bool(p.get("negRisk") or p.get("neg_risk"))
        if not cid:
            print(f"  SKIP {slug} — no condition_id")
            continue
        try:
            data, plan = encode_redeem_calldata(cid, neg_risk=neg_risk)
        except Exception as e:
            print(f"  SKIP {slug} — calldata build failed: {e}")
            continue
        plan["slug"]      = slug
        plan["size"]      = size
        plan["avg_price"] = avg
        plan["neg_risk"]  = neg_risk
        plans.append(plan)
        print(f"  PLAN: {slug[:40]}  cond={cid[:14]}...  shares={size}  "
              f"target={'NEG_RISK_CTF' if neg_risk else 'CTF'}")

    # Always write the plan
    out_path = ROOT / "output" / "redeem_pending.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(plans, indent=2), encoding="utf-8")
    print(f"\nReport written: {out_path}")

    if not args.execute:
        print("\nDry-run complete. Pass --execute to actually broadcast.")
        return 0

    # ── Execute path ────────────────────────────────────────────────────────
    limit = min(args.limit, MAX_PER_RUN)
    if len(plans) > limit:
        print(f"\n[INFO] Capping execution to first {limit} of {len(plans)} plans (--limit / MAX_PER_RUN).")
        plans = plans[:limit]

    pk = os.environ.get("POLYMARKET_PRIVATE_KEY", "").strip()
    if not pk:
        print("ABORT: POLYMARKET_PRIVATE_KEY not in .env")
        return 3
    if not pk.startswith("0x"):
        pk = "0x" + pk

    w3 = _connect_polygon()
    if w3 is None:
        print(f"ABORT: no Polygon RPC available (tried {len(POLYGON_RPCS)})")
        return 4

    results = []
    for plan in plans:
        print(f"\n--- Executing redeem: {plan['slug'][:40]} ---")
        try:
            tx_hash = safe_exec_transaction(
                w3, addr, pk,
                to=plan["target"], value=0, data_hex=plan["calldata"],
            )
            results.append({"slug": plan["slug"], "tx": tx_hash, "ok": tx_hash is not None})
        except Exception as e:
            print(f"  FAILED: {e}")
            results.append({"slug": plan["slug"], "tx": None, "ok": False, "error": str(e)})
        time.sleep(2)   # avoid same-block conflicts

    log_path = ROOT / "output" / f"redeem_log_{int(time.time())}.json"
    log_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nExecution log: {log_path}")
    print(f"Succeeded: {sum(1 for r in results if r['ok'])}/{len(results)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
