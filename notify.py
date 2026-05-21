"""Telegram notifications for the bots.

Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from .env. Silently no-ops if
either is missing — the bots can run without notifications configured.

Usage:
    from notify import notify
    notify("Bot just hit -$50 today")

Throttling: each unique message kind can only fire once per cooldown window
(default 1 hour) to avoid spam during stall conditions.
"""
from __future__ import annotations
import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
API_URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage" if TOKEN else None

# Per-kind cooldown so we don't spam during a stall.
_COOLDOWN_FILE = Path(__file__).resolve().parent / "output" / ".notify_cooldown.json"
DEFAULT_COOLDOWN_SECONDS = 3600  # 1 hour


def _load_cooldowns() -> dict:
    if not _COOLDOWN_FILE.exists():
        return {}
    try:
        return json.loads(_COOLDOWN_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cooldowns(d: dict) -> None:
    try:
        _COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
        _COOLDOWN_FILE.write_text(json.dumps(d), encoding="utf-8")
    except Exception:
        pass


def notify(text: str, kind: str = "general", cooldown: int = DEFAULT_COOLDOWN_SECONDS) -> bool:
    """Send `text` to the configured Telegram chat.

    `kind` is a tag for throttling — repeated alerts of the same kind within
    `cooldown` seconds are suppressed. Pass `cooldown=0` to disable throttling.

    Returns True if a message was actually sent, False if no-op (missing creds,
    on cooldown, or HTTP error).
    """
    if not TOKEN or not CHAT_ID or not API_URL:
        return False

    now = time.time()
    if cooldown > 0:
        cd = _load_cooldowns()
        last = float(cd.get(kind, 0))
        if now - last < cooldown:
            return False
        cd[kind] = now
        _save_cooldowns(cd)

    try:
        r = requests.post(API_URL, data={
            "chat_id": CHAT_ID,
            "text":    text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=10)
        return r.status_code == 200
    except Exception:
        return False


if __name__ == "__main__":
    import sys
    msg = " ".join(sys.argv[1:]) or "Test message from notify.py"
    ok = notify(msg, kind="manual_test", cooldown=0)
    print("Sent." if ok else "Failed — check TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID in .env")
