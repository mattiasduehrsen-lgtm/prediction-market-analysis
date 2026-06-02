"""Run the feasibility analysis and post the verdict to Telegram.
Scheduled to fire after the data pipeline completes, so the result reaches
the user's phone. Idempotent — safe to run anytime; just re-reports.
"""
from __future__ import annotations
import os, subprocess
from pathlib import Path
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
PY = ROOT / ".venv" / "Scripts" / "python.exe"

def run(script):
    try:
        r = subprocess.run([str(PY), str(ROOT / "analysis" / script)],
                           capture_output=True, text=True, timeout=600, cwd=str(ROOT))
        return r.stdout + ("\n" + r.stderr if r.stderr else "")
    except Exception as e:
        return f"({script} failed: {e})"

def send(msg):
    if not TOKEN or not CHAT:
        print("no telegram creds"); print(msg); return
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      data={"chat_id": CHAT, "text": msg[:4000]}, timeout=15)
    except Exception as e:
        print(f"send failed: {e}")

def main():
    # Ensure latest model + join are built, then run feasibility
    run("build_elo.py")
    run("prematch_prices.py")
    out = run("feasibility.py")
    # Trim to the meaningful tail (joined count + accuracy + ROI sweep)
    lines = [l for l in out.splitlines() if l.strip()]
    tail = "\n".join(lines[-22:]) if len(lines) > 22 else out
    msg = ("CS2 MODEL FEASIBILITY — verdict\n"
           "(Elo model vs Polymarket price; does the model find mispricings?)\n\n"
           + tail +
           "\n\nIf ROI is positive at higher edge thresholds, the model beats the "
           "market and the pivot is worth building. If flat/negative, esports CS2 "
           "is efficiently priced and we rethink.")
    send(msg)
    print(msg)

if __name__ == "__main__":
    main()
