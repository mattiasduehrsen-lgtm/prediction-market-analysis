"""Live trade execution for Polymarket via the CLOB API.

This module sends real orders to Polymarket using your wallet's private key.
It is only activated when LIVE_TRADING=true is set in your .env file.

Requirements:
  - POLYMARKET_PRIVATE_KEY  : your Polygon wallet private key (starts with 0x)
  - USDC balance on Polygon  : the collateral used to buy outcome tokens
  - py-clob-client installed : added automatically via pyproject.toml

How Polymarket trading works:
  - Every market has two outcome tokens (e.g. "Yes" and "No"), each with a token ID.
  - Buying "Yes" at 0.40 means you pay $0.40 per share; if Yes wins you receive $1.00.
  - Orders are placed on a Central Limit Order Book (CLOB) on Polygon.
  - All collateral is USDC; gas fees on Polygon are tiny (fractions of a cent).
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

CLOB_HOST = "https://clob.polymarket.com"


class LiveExecutor:
    """Sends buy and sell orders to Polymarket's CLOB API.

    Usage:
        executor = LiveExecutor()          # reads POLYMARKET_PRIVATE_KEY from env
        executor.buy("0xabc...", 0.40, 25) # buy $25 of token at 40 cents
        executor.sell("0xabc...", 0.55, 62.5) # sell 62.5 shares at 55 cents
    """

    def __init__(self) -> None:
        private_key = os.environ.get("POLYMARKET_PRIVATE_KEY", "").strip()
        if not private_key:
            raise RuntimeError(
                "POLYMARKET_PRIVATE_KEY is not set. "
                "Add it to your .env file to enable live trading."
            )

        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.constants import POLYGON
        except ImportError as exc:
            raise RuntimeError(
                "py-clob-client is not installed. Run: uv sync"
            ) from exc

        self._ClobClient = ClobClient
        self._chain_id = POLYGON
        self._private_key = private_key
        self._client: object | None = None
        self._connect()

    def _connect(self) -> None:
        """Create an authenticated CLOB client session."""
        client = self._ClobClient(CLOB_HOST, key=self._private_key, chain_id=self._chain_id)
        creds = client.create_or_derive_api_creds()
        client.set_api_creds(creds)
        self._client = client
        logger.info("LiveExecutor connected to Polymarket CLOB (%s)", CLOB_HOST)

    def buy(self, token_id: str, price: float, size_dollars: float) -> dict:
        """Place a buy (long) order for an outcome token.

        Args:
            token_id:     The CLOB token ID for the outcome (from market data).
            price:        Price per share in dollars, e.g. 0.40 for 40 cents.
            size_dollars: How many dollars to spend, e.g. 25.0 for $25.

        Returns:
            The API response dict containing orderID and status.

        Raises:
            RuntimeError: If the order is rejected by the exchange.
        """
        if not token_id:
            raise ValueError("token_id is empty — cannot place live buy order")
        if price <= 0 or price >= 1:
            raise ValueError(f"price {price} is out of valid range (0, 1)")
        if size_dollars < 1:
            raise ValueError(f"size_dollars {size_dollars} is too small (minimum $1)")

        try:
            from py_clob_client.clob_types import OrderArgs, OrderType
            from py_clob_client.order_builder.constants import BUY
        except ImportError as exc:
            raise RuntimeError("py-clob-client import failed") from exc

        # Number of shares = dollars / price per share
        size_shares = round(size_dollars / price, 2)
        # Polymarket prices must be in 1-cent increments
        rounded_price = round(price, 2)

        order_args = OrderArgs(token_id=token_id, price=rounded_price, size=size_shares, side=BUY)
        signed_order = self._client.create_order(order_args)  # type: ignore[union-attr]
        result = self._client.post_order(signed_order, OrderType.GTC)  # type: ignore[union-attr]

        if result is None:
            raise RuntimeError("CLOB returned None for buy order — check your USDC balance")

        order_id = result.get("orderID") or result.get("id") or "unknown"
        status = result.get("status") or result.get("errorMsg") or "unknown"
        logger.info(
            "LIVE BUY  token=%.8s price=%.2f shares=%.2f dollars=%.2f orderID=%s status=%s",
            token_id, rounded_price, size_shares, size_dollars, order_id, status,
        )
        return result

    def sell(self, token_id: str, price: float, size_shares: float) -> dict:
        """Place a sell order to exit an outcome token position.

        Args:
            token_id:    The CLOB token ID for the outcome (same as at entry).
            price:       Current price per share in dollars.
            size_shares: Number of shares to sell (matches the buy size).

        Returns:
            The API response dict containing orderID and status.

        Raises:
            RuntimeError: If the order is rejected by the exchange.
        """
        if not token_id:
            raise ValueError("token_id is empty — cannot place live sell order")
        if size_shares <= 0:
            raise ValueError(f"size_shares {size_shares} must be positive")

        try:
            from py_clob_client.clob_types import OrderArgs, OrderType
            from py_clob_client.order_builder.constants import SELL
        except ImportError as exc:
            raise RuntimeError("py-clob-client import failed") from exc

        rounded_price = round(price, 2)
        rounded_size = round(size_shares, 2)

        order_args = OrderArgs(token_id=token_id, price=rounded_price, size=rounded_size, side=SELL)
        signed_order = self._client.create_order(order_args)  # type: ignore[union-attr]
        result = self._client.post_order(signed_order, OrderType.GTC)  # type: ignore[union-attr]

        if result is None:
            raise RuntimeError("CLOB returned None for sell order")

        order_id = result.get("orderID") or result.get("id") or "unknown"
        status = result.get("status") or result.get("errorMsg") or "unknown"
        logger.info(
            "LIVE SELL token=%.8s price=%.2f shares=%.2f orderID=%s status=%s",
            token_id, rounded_price, rounded_size, order_id, status,
        )
        return result


def build_live_executor_if_enabled() -> LiveExecutor | None:
    """Return a LiveExecutor if LIVE_TRADING=true, otherwise None (paper mode).

    Call this once at startup. If it returns None, the bot runs in paper mode
    and no real orders are placed.
    """
    enabled = os.environ.get("LIVE_TRADING", "false").strip().lower()
    if enabled not in ("true", "1", "yes"):
        logger.info("LIVE_TRADING is not enabled — running in paper mode")
        return None

    logger.warning(
        "LIVE_TRADING=true — real orders will be placed on Polymarket using your wallet"
    )
    return LiveExecutor()
