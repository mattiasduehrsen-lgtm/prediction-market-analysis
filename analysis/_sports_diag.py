import subprocess
out = subprocess.run(["powershell","-NoProfile","-Command",
  "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and ($_.CommandLine -match 'sports_fade_bot|watch_sports') } | ForEach-Object { \"$($_.ProcessId)|$($_.ParentProcessId)|$($_.Name)|$($_.CommandLine)\" }"],
  capture_output=True,text=True,timeout=40).stdout
for l in out.splitlines():
    if l.strip(): print(l[:130])
print("--- sports-launching tasks ---")
out2 = subprocess.run(["powershell","-NoProfile","-Command",
  "Get-ScheduledTask | Where-Object { ($_.Actions | ForEach-Object { $_.Arguments + ' ' + $_.Execute }) -match 'sports' } | ForEach-Object { $_.TaskName }"],
  capture_output=True,text=True,timeout=40).stdout
print(out2)
