"""Authoritative balance check via Polymarket CLOB SDK (the same call the
bot makes internally). Use this when on-chain USDC.e queries return $0
but the UI shows cash — Polymarket migrated to pUSD wrapper, so USDC.e
queries are no longer the source of truth.
"""
import os
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BalanceAllowanceParams, AssetType

load_dotenv()

client = ClobClient(
    'https://clob.polymarket.com',
    key=os.getenv('POLYMARKET_PRIVATE_KEY'),
    chain_id=137,
    signature_type=2,
    funder=os.getenv('POLYMARKET_PROXY_ADDRESS'),
)
client.set_api_creds(client.create_or_derive_api_creds())

b = client.get_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
print('CLOB COLLATERAL response:')
print(f'  balance   = {b}')
try:
    bal_raw = int(b.get('balance', 0))
    allow_raw = int(b.get('allowance', 0))
    print()
    print(f'  USDC balance  : ${bal_raw / 1e6:.4f}')
    print(f'  USDC allowance: ${allow_raw / 1e6:.4f}')
except Exception as e:
    print(f'  (parse error: {e})')
