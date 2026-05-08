# restart_safe.ps1 - clean restart of all three bot tasks on the laptop
#
# Run on the laptop (or via SSH) to restart PolyBotPaper + PolyBot + PolyDashboard
# WITHOUT orphaning cmd.exe watchdogs (the bug that caused PAPER to die silently
# for 24h after the v1.28 deploy on 2026-05-06).
#
# Usage (laptop local):  .\restart_safe.ps1
# Usage (over SSH):
#   ssh matti@192.168.2.212 "powershell -File C:\Users\matti\Desktop\prediction-market-analysis\restart_safe.ps1"

$ErrorActionPreference = "Continue"
$pauseFlag = "C:\Users\matti\Desktop\prediction-market-analysis\output\5m_live\paused.live.flag"

Write-Host "=== restart_safe.ps1 - $(Get-Date) ===" -ForegroundColor Cyan

# 1. Capture LIVE pause state so we can verify it's preserved
$wasPaused = Test-Path $pauseFlag
Write-Host "LIVE pause flag exists: $wasPaused" -ForegroundColor Yellow

# 2. END scheduled tasks cleanly (kills cmd.exe watchdog + python child as a tree)
Write-Host "`n--- Ending scheduled tasks ---"
schtasks /end /tn PolyBotPaper 2>&1
schtasks /end /tn PolyBot 2>&1
schtasks /end /tn PolyDashboard 2>&1

# 3. Belt-and-braces: kill any orphaned python processes
Write-Host "`n--- Killing any orphaned python processes ---"
Stop-Process -Name python -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3

# 4. Restart all three tasks
Write-Host "`n--- Starting scheduled tasks ---"
schtasks /run /tn PolyBotPaper 2>&1
schtasks /run /tn PolyBot 2>&1
schtasks /run /tn PolyDashboard 2>&1

# 5. Wait, then verify processes
Write-Host "`n--- Waiting 15s for processes to come up ---"
Start-Sleep -Seconds 15

Write-Host "`n--- Running python.exe processes ---"
$procs = Get-CimInstance Win32_Process -Filter "name='python.exe'"
$procs | Select-Object ProcessId, CommandLine | Format-Table -AutoSize -Wrap

# Count by command type
$nLoop = ($procs | Where-Object { $_.CommandLine -like '*multi-loop*' }).Count
$nLive = ($procs | Where-Object { $_.CommandLine -like '*multi-live*' }).Count
$nDash = ($procs | Where-Object { $_.CommandLine -like '*dashboard*' }).Count

Write-Host "`n=== Process count check ===" -ForegroundColor Cyan
Write-Host "multi-loop  : $nLoop  (expected 2)"
Write-Host "multi-live  : $nLive  (expected 2)"
Write-Host "dashboard   : $nDash  (expected 2)"

if ($nLoop -lt 2) { Write-Host "WARN: PAPER may not have started" -ForegroundColor Red }
if ($nLive -lt 2) { Write-Host "WARN: LIVE may not have started" -ForegroundColor Red }
if ($nDash -lt 2) { Write-Host "WARN: Dashboard may not have started" -ForegroundColor Red }

# 6. Verify pause flag intact
$stillPaused = Test-Path $pauseFlag
Write-Host "`n=== Pause flag check ===" -ForegroundColor Cyan
Write-Host "Was paused: $wasPaused"
Write-Host "Now paused: $stillPaused"
if ($wasPaused -and -not $stillPaused) {
    Write-Host "ALERT: pause flag was lost during restart!" -ForegroundColor Red
}

Write-Host "`n=== Done ===" -ForegroundColor Cyan
