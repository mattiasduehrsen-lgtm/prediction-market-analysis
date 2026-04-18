"""
One-shot order placement test.
Places a GTC BUY limit at 0.01 on the BTC-15m UP token (will never fill),
prints the order ID, then immediately cancels it.
Run: .venv\Scripts\python.exe test_order.py
"""
import os, sys, time
from dotenv import load_dotenv
load_dotenv()

from src.bot.clob_auth import get_client
from src.bot.market_5m import fetch_market
from py_clob_client_v2 import OrderArgs, OrderType
from py_clob_client_v2.order_builder.constants import BUY

print("=" * 50)
print("LIVE ORDER FLOW TEST")
print("=" * 50)

# ── 1. Fetch current BTC-15m market ───────────────────────────────────────────
print("\n[1] Fetching BTC-15m market...")
market = fetch_market("BTC", "15m")
if market is None:
    print("ERROR: No active BTC-15m market found.")
    sys.exit(1)

print(f"    Market : {market.slug}")
print(f"    UP token: {market.token_id_up[:24]}...")
print(f"    UP price: {market.up_price:.3f}")
print(f"    Secs left: {market.seconds_remaining:.0f}s")

# ── 2. Auth ────────────────────────────────────────────────────────────────────
print("\n[2] Authenticating CLOB client...")
try:
    client = get_client()
    print("    Auth OK")
except Exception as e:
    print(f"    ERROR: {e}")
    sys.exit(1)

# ── 3. Place a GTC BUY at 0.01 — far below market, will never fill ─────────────
TEST_PRICE  = 0.01    # cents on the dollar — no one will sell this cheap
TEST_SHARES = 5.0     # minimum order size

print(f"\n[3] Placing GTC BUY: {TEST_SHARES} shares @ ${TEST_PRICE} (UP token, will not fill)...")
try:
    order_args = OrderArgs(
        price=TEST_PRICE,
        size=TEST_SHARES,
        side=BUY,
        token_id=market.token_id_up,
    )
    signed = client.create_order(order_args)
    resp   = client.post_order(signed, OrderType.GTC)
except Exception as e:
    print(f"    ERROR placing order: {e}")
    sys.exit(1)

order_id = resp.get("orderID", "")
if not order_id:
    print(f"    ERROR: No orderID in response: {resp}")
    sys.exit(1)

print(f"    SUCCESS — order placed!")
print(f"    orderID : {order_id}")
print(f"    response: {resp}")

# ── 4. Brief pause, then fetch to confirm it's live ───────────────────────────
print("\n[4] Waiting 2s then confirming order is live on book...")
time.sleep(2)
try:
    order_status = client.get_order(order_id)
    print(f"    status      : {order_status.get('status', 'unknown')}")
    print(f"    size_matched: {order_status.get('size_matched', 0)}")
    print(f"    price       : {order_status.get('price', '?')}")
except Exception as e:
    print(f"    WARNING: could not fetch order status: {e}")

# ── 5. Cancel ─────────────────────────────────────────────────────────────────
print(f"\n[5] Cancelling order {order_id[:16]}...")
try:
    cancel_resp = client.cancel(order_id)
    print(f"    Cancel response: {cancel_resp}")
except Exception as e:
    print(f"    ERROR cancelling: {e}")
    sys.exit(1)

# ── 6. Confirm cancelled ──────────────────────────────────────────────────────
print("\n[6] Confirming cancellation...")
time.sleep(2)
try:
    final_status = client.get_order(order_id)
    status = final_status.get("status", "unknown")
    print(f"    Final status: {status}")
    if status in ("cancelled", "canceled"):
        print("\n✅ FULL ORDER FLOW CONFIRMED")
        print("   Place → Live on book → Cancel → Confirmed cancelled")
        print("   The live engine can place and cancel real Polymarket orders.")
    else:
        print(f"\n⚠️  Order status is '{status}' — check Polymarket UI manually")
except Exception as e:
    print(f"    WARNING: could not fetch final status: {e}")

print("=" * 50)
