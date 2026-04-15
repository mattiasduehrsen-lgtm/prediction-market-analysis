"""
Polymarket CLOB authentication.

L1 auth: private key (read-only endpoints)
L2 auth: API key derived from private key (required for order placement)

Two wallet setups are supported:

  signature_type=0  EOA direct — MetaMask key holds funds directly.
                    POLYMARKET_PROXY_ADDRESS not set.

  signature_type=1  Poly Proxy — MetaMask key signs, but funds sit in a
                    separate Polymarket proxy wallet.
                    Set POLYMARKET_PROXY_ADDRESS=0x... in .env.

Most users who connected MetaMask to Polymarket and deposited funds will
need signature_type=1 because Polymarket creates a proxy wallet controlled
by the MetaMask EOA.

L2 credentials are derived once and stored in .env. To generate them:
  python main.py setup-clob-auth

Then add the printed values to .env on both machines.
"""
from __future__ import annotations

import os

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds
from py_clob_client.constants import POLYGON

CLOB_HOST = "https://clob.polymarket.com"


def get_client() -> ClobClient:
    """Return a fully authenticated ClobClient (L1 + L2)."""
    key = os.environ.get("POLYMARKET_PRIVATE_KEY", "").strip()
    if not key:
        raise RuntimeError("POLYMARKET_PRIVATE_KEY not set in .env")

    api_key        = os.environ.get("POLYMARKET_API_KEY", "").strip()
    api_secret     = os.environ.get("POLYMARKET_API_SECRET", "").strip()
    api_passphrase = os.environ.get("POLYMARKET_API_PASSPHRASE", "").strip()

    if not all([api_key, api_secret, api_passphrase]):
        raise RuntimeError(
            "L2 credentials missing from .env.\n"
            "Run:  python main.py setup-clob-auth\n"
            "Then add POLYMARKET_API_KEY / _SECRET / _PASSPHRASE to .env."
        )

    proxy = os.environ.get("POLYMARKET_PROXY_ADDRESS", "").strip()

    if proxy:
        # signature_type=1: MetaMask EOA signs, proxy wallet holds funds
        return ClobClient(
            host=CLOB_HOST,
            chain_id=POLYGON,
            key=key,
            signature_type=1,
            funder=proxy,
            creds=ApiCreds(
                api_key=api_key,
                api_secret=api_secret,
                api_passphrase=api_passphrase,
            ),
        )
    else:
        # signature_type=0: EOA direct — wallet signs and holds funds
        return ClobClient(
            host=CLOB_HOST,
            chain_id=POLYGON,
            key=key,
            signature_type=0,
            creds=ApiCreds(
                api_key=api_key,
                api_secret=api_secret,
                api_passphrase=api_passphrase,
            ),
        )


def get_l1_client() -> ClobClient:
    """Return an L1-only client (no API key needed — for read endpoints)."""
    key = os.environ.get("POLYMARKET_PRIVATE_KEY", "").strip()
    if not key:
        raise RuntimeError("POLYMARKET_PRIVATE_KEY not set in .env")
    proxy = os.environ.get("POLYMARKET_PROXY_ADDRESS", "").strip()
    if proxy:
        return ClobClient(host=CLOB_HOST, chain_id=POLYGON, key=key,
                          signature_type=1, funder=proxy)
    return ClobClient(host=CLOB_HOST, chain_id=POLYGON, key=key, signature_type=0)


def setup_credentials() -> None:
    """
    One-time setup: derive L2 API credentials from the private key.
    Prints the three values to add to .env.
    """
    print("Deriving L2 API credentials from private key...")
    client = get_l1_client()
    try:
        creds = client.derive_api_key()
    except Exception as exc:
        raise RuntimeError(f"Failed to derive API key: {exc}") from exc

    print("\nAdd these to your .env on BOTH machines:\n")
    print(f"POLYMARKET_API_KEY={creds.api_key}")
    print(f"POLYMARKET_API_SECRET={creds.api_secret}")
    print(f"POLYMARKET_API_PASSPHRASE={creds.api_passphrase}")
    print()
