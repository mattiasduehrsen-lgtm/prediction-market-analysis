# audit which bots are alive (run on laptop)
import subprocess, json, re
ps = subprocess.run(["powershell","-Command",
  "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | ForEach-Object { $_.CommandLine }"],
  capture_output=True, text=True)
lines = [l for l in ps.stdout.splitlines() if l.strip()]
bots = ["esports_fade_bot","sports_fade_bot","cs2_model_bot","cs2_inplay_bot","telegram_bot","main.py dashboard","price_capture"]
print("RUNNING bots:")
for b in bots:
    # 'sports_fade_bot' is a substring of 'esports_fade_bot' -> require no letter before
    pat = re.compile(r"(?<![A-Za-z])" + re.escape(b))
    n = sum(1 for l in lines if pat.search(l))
    print(f"  {'OK ' if n else 'DOWN'} {b}: {n} proc")
