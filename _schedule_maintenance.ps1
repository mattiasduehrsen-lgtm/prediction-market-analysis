# One-time scheduler for tomorrow's (2026-05-22) Polymarket maintenance pause.
# Run once on the laptop. After both tasks fire, you can delete them.
# Times in laptop local (CDT, UTC-5):
#   07:05 CDT = 12:05 UTC  -> auto-pause
#   08:10 CDT = 13:10 UTC  -> auto-resume

$root   = 'C:\Users\matti\Desktop\prediction-market-analysis'
$py     = "$root\.venv\Scripts\python.exe"
$script = "$root\maintenance_window.py"

# /tr accepts the whole command string as one argument — wrap each path in
# double-quotes inside the string, escaping them with the PowerShell backtick.
$startCmd = "`"$py`" `"$script`" --start `"Polymarket maintenance 12:10 UTC`""
$endCmd   = "`"$py`" `"$script`" --end `"Polymarket maintenance 12:10 UTC`""

Write-Host "Creating PolyMaintPauseStart for 05/22/2026 07:05 CDT..."
schtasks /create /tn PolyMaintPauseStart /tr $startCmd /sc once /sd 05/22/2026 /st 07:05 /ru "MSI\matti" /rp "Tiasdue123." /f

Write-Host ""
Write-Host "Creating PolyMaintPauseEnd for 05/22/2026 08:10 CDT..."
schtasks /create /tn PolyMaintPauseEnd /tr $endCmd /sc once /sd 05/22/2026 /st 08:10 /ru "MSI\matti" /rp "Tiasdue123." /f

Write-Host ""
Write-Host "--- Verification ---"
schtasks /query /tn PolyMaintPauseStart /v /fo LIST | Select-String 'TaskName|Next Run|Status|Task To Run'
schtasks /query /tn PolyMaintPauseEnd   /v /fo LIST | Select-String 'TaskName|Next Run|Status|Task To Run'
