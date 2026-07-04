"""Boot notifier — runs at system start; Telegrams that the laptop booted and
whether the previous shutdown was UNEXPECTED (kernel-power 41 / event 6008).
Added 2026-07-04 after a hard crash at 12:29 PM went unannounced (discovered only
because a session happened to be mid-health-check)."""
import subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from notify import notify  # telegram helper

ps = ("Get-WinEvent -FilterHashtable @{LogName='System'; Id=6008} -MaxEvents 1 "
      "-ErrorAction SilentlyContinue | ForEach-Object { $_.TimeCreated }")
out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                     capture_output=True, text=True, timeout=60).stdout.strip()

msg = "🔌 <b>Laptop booted</b> — bots auto-starting (boot triggers + guard)."
if out:
    msg += f"\nLast <b>unexpected</b> shutdown: {out}"
notify(msg, kind="boot", cooldown=300)
print("boot notice sent;", out or "no unexpected-shutdown record")
