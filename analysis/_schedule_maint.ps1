# Schedule one-shot maintenance pause for Polymarket maintenance on May 27 12:10 UTC.
# Local time on laptop is CDT (UTC-5) → 07:10 CDT.
# Pause starts 5 min before (07:05) and ends 15 min after window opens (07:25)
# since the announced window is "10 minutes" but we want margin on both sides.

$base = "C:\Users\matti\Desktop\prediction-market-analysis"

# Clean up any prior maintenance task with the same name (idempotent)
schtasks /delete /tn "PolyMaintPauseStart_2026_05_27" /f 2>$null | Out-Null
schtasks /delete /tn "PolyMaintPauseEnd_2026_05_27"   /f 2>$null | Out-Null

# Start pause at 07:05 CDT (12:05 UTC)
schtasks /create /tn "PolyMaintPauseStart_2026_05_27" `
    /tr "$base\_maint_pause_start.bat" `
    /sc once /sd "05/27/2026" /st "07:05" `
    /ru "matti" /rl HIGHEST /f

# End pause at 07:25 CDT (12:25 UTC)
schtasks /create /tn "PolyMaintPauseEnd_2026_05_27" `
    /tr "$base\_maint_pause_end.bat" `
    /sc once /sd "05/27/2026" /st "07:25" `
    /ru "matti" /rl HIGHEST /f

Write-Output "---- scheduled ----"
schtasks /query /tn "PolyMaintPauseStart_2026_05_27" /fo LIST | Select-Object -First 6
schtasks /query /tn "PolyMaintPauseEnd_2026_05_27"   /fo LIST | Select-Object -First 6
