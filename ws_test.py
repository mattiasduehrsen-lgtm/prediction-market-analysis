"""Quick test: can we connect to Binance WebSocket from this machine?"""
import threading, time, json, websocket

result = {"connected": False, "price": None, "error": None}

def on_message(ws, msg):
    d = json.loads(msg)
    result["price"] = float(d.get("p", 0))
    result["connected"] = True
    ws.close()

def on_error(ws, err):
    result["error"] = str(err)

def on_open(ws):
    print("WebSocket connected!")

ws = websocket.WebSocketApp(
    "wss://stream.binance.com:9443/ws/btcusdt@trade",
    on_message=on_message,
    on_error=on_error,
    on_open=on_open,
)
t = threading.Thread(target=ws.run_forever, kwargs={"ping_interval": 5})
t.daemon = True
t.start()

for i in range(15):
    time.sleep(1)
    if result["connected"]:
        print(f"SUCCESS — BTC price: ${result['price']:,.2f}")
        break
else:
    print(f"FAILED — error: {result['error']}")
