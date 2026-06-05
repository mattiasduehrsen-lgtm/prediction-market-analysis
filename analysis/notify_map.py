"""Post the Phase-1 map-model verdict (gate + market backtest) to Telegram."""
from __future__ import annotations
import os
from pathlib import Path
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

log = ROOT / "bo3_pipeline.log"
text = log.read_text(encoding="utf-8", errors="ignore") if log.exists() else "(no log)"
# keep from the last 'usable CS2 games' marker onward (the model+backtest output)
idx = text.rfind("usable CS2 games")
tail = text[idx:][:3500] if idx >= 0 else text[-3500:]
msg = ("CS2 MAP MODEL — Phase 1 verdict\n"
       "(does a per-map model beat Polymarket map-winner prices?)\n\n" + tail +
       "\n\nKey Qs: (1) does map-AWARE beat map-AGNOSTIC? (2) does EITHER beat the "
       "market at higher edge thresholds? Positive ROI = worth Phase 2.")
if TOKEN and CHAT:
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      data={"chat_id": CHAT, "text": msg[:4000]}, timeout=15)
    except Exception as e:
        print("send failed", e)
print(msg)
