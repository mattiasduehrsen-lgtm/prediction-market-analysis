"""Pause/unpause the esports bot for a scheduled Polymarket maintenance window.

Invoked by Windows scheduled tasks before and after maintenance. Writes or
removes output/esports_fade/paused.flag and sends a Telegram alert so the
user knows what happened.

Usage:
    python maintenance_window.py --start "Polymarket maintenance"
    python maintenance_window.py --end "Polymarket maintenance"
"""
import argparse
import json
import time
from pathlib import Path

from notify import notify

ROOT = Path(__file__).resolve().parent
PAUSE_FLAG = ROOT / "output" / "esports_fade" / "paused.flag"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", metavar="REASON", help="Begin a maintenance pause")
    p.add_argument("--end",   metavar="REASON", help="End a maintenance pause")
    args = p.parse_args()

    if args.start:
        PAUSE_FLAG.parent.mkdir(parents=True, exist_ok=True)
        PAUSE_FLAG.write_text(json.dumps({
            "paused_at": time.time(),
            "via":       "maintenance_window",
            "reason":    args.start,
        }), encoding="utf-8")
        print(f"[maint] Paused. Reason: {args.start}")
        notify(
            f"🟡 <b>Bot paused for scheduled maintenance</b>\n"
            f"Reason: {args.start}\n"
            f"Auto-resumes after the window closes. Existing positions held.",
            kind="maint_start", cooldown=0,
        )
    elif args.end:
        if PAUSE_FLAG.exists():
            try: PAUSE_FLAG.unlink()
            except Exception: pass
        print(f"[maint] Resumed. Reason: {args.end}")
        notify(
            f"🟢 <b>Maintenance pause cleared</b>\n"
            f"Bot is trading again.\n"
            f"If Polymarket's data-api is still lagging (like yesterday's "
            f"11h drought), the stale-trade filter will handle it. "
            f"Run /diagnose to check.",
            kind="maint_end", cooldown=0,
        )
    else:
        p.print_help()


if __name__ == "__main__":
    main()
