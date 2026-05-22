# One-time scheduler for tomorrow's (2026-05-22) Polymarket maintenance pause.
# Uses .bat wrapper files to avoid schtasks /tr quoting hell.
$root = 'C:\Users\matti\Desktop\prediction-market-analysis'

Write-Host "Creating PolyMaintPauseStart for 05/22/2026 07:05 CDT (12:05 UTC)..."
schtasks /create /tn PolyMaintPauseStart `
    /tr "$root\_maint_pause_start.bat" `
    /sc once /sd 05/22/2026 /st 07:05 `
    /ru "MSI\matti" /rp "Tiasdue123." /f

Write-Host ""
Write-Host "Creating PolyMaintPauseEnd for 05/22/2026 08:10 CDT (13:10 UTC)..."
schtasks /create /tn PolyMaintPauseEnd `
    /tr "$root\_maint_pause_end.bat" `
    /sc once /sd 05/22/2026 /st 08:10 `
    /ru "MSI\matti" /rp "Tiasdue123." /f

Write-Host ""
Write-Host "--- Verification ---"
foreach ($t in 'PolyMaintPauseStart','PolyMaintPauseEnd') {
    Write-Host "$t :"
    schtasks /query /tn $t /v /fo LIST | Select-String 'TaskName|Next Run|Status|Task To Run'
    Write-Host ""
}
