# health_check.ps1 — quick bot health summary
#
# Runs on the laptop to summarize:
#   - Are PAPER, LIVE, Dashboard processes alive?
#   - Watchdog last activity
#   - Recent skipped_windows.csv writes (PAPER alive proof)
#   - LIVE pause flag state
#   - Last bot.log line
#
# Usage:
#   ssh matti@192.168.2.212 "powershell -File C:\Users\matti\Desktop\prediction-market-analysis\health_check.ps1"

$ErrorActionPreference = "Continue"
$root = "C:\Users\matti\Desktop\prediction-market-analysis"

Write-Host "=== bot health — $(Get-Date) ===" -ForegroundColor Cyan

# 1. Process check
$procs = Get-CimInstance Win32_Process -Filter "name='python.exe'"
$nLoop = ($procs | Where-Object { $_.CommandLine -like '*multi-loop*' }).Count
$nLive = ($procs | Where-Object { $_.CommandLine -like '*multi-live*' }).Count
$nDash = ($procs | Where-Object { $_.CommandLine -like '*dashboard*' }).Count

function Status($n, $expected) {
    if ($n -ge $expected) { return "OK ($n)" } else { return "FAIL ($n/$expected)" }
}
Write-Host "`n--- Processes ---"
Write-Host "PAPER (multi-loop) : $(Status $nLoop 2)"
Write-Host "LIVE  (multi-live) : $(Status $nLive 2)"
Write-Host "Dashboard          : $(Status $nDash 2)"

# 2. Watchdog last activity
$wlog = "$root\watchdog_paper.log"
if (Test-Path $wlog) {
    $age = (Get-Date) - (Get-Item $wlog).LastWriteTime
    Write-Host "`n--- Watchdog ---"
    Write-Host "watchdog_paper.log last write: $((Get-Item $wlog).LastWriteTime) ($([int]$age.TotalMinutes) min ago)"
    if ($age.TotalMinutes -gt 60 -and $nLoop -lt 2) {
        Write-Host "ALERT: watchdog stale AND PAPER not running!" -ForegroundColor Red
    }
}

# 3. PAPER alive proof — skipped_windows.csv recently written
$sw = "$root\output\5m_trading\skipped_windows.csv"
if (Test-Path $sw) {
    $age = (Get-Date) - (Get-Item $sw).LastWriteTime
    Write-Host "`n--- PAPER data writes ---"
    Write-Host "skipped_windows.csv last write: $((Get-Item $sw).LastWriteTime) ($([int]$age.TotalMinutes) min ago)"
    if ($age.TotalMinutes -gt 30) {
        Write-Host "WARN: skipped_windows.csv hasn't been touched in over 30 min — PAPER may be stuck" -ForegroundColor Yellow
    }
}

# 4. LIVE pause state
$pauseFlag = "$root\output\5m_live\paused.live.flag"
$paused = Test-Path $pauseFlag
Write-Host "`n--- LIVE pause state ---"
Write-Host "paused.live.flag: $paused"

# 5. Recent LIVE trades
foreach ($asset in @("BTC", "ETH", "SOL")) {
    $f = "$root\output\5m_live\trades_$asset-15m.csv"
    if (Test-Path $f) {
        $age = (Get-Date) - (Get-Item $f).LastWriteTime
        $ageStr = if ($age.TotalDays -gt 1) { "{0:N1}d" -f $age.TotalDays } else { "{0:N0}m" -f $age.TotalMinutes }
        Write-Host "trades_$asset-15m.csv last write: $ageStr ago"
    }
}

# 6. Last bot.log line
$blog = "$root\bot.log"
if (Test-Path $blog) {
    $last = Get-Content $blog -Tail 1
    $age = (Get-Date) - (Get-Item $blog).LastWriteTime
    Write-Host "`n--- bot.log ---"
    Write-Host "last write: $([int]$age.TotalSeconds)s ago"
    Write-Host "last line: $last"
}

# 7. Current version
$v = Get-Content "$root\src\bot\version.py" | Select-String "PATCH\s*="
Write-Host "`n--- Version ---"
Write-Host $v

Write-Host "`n=== Done ===" -ForegroundColor Cyan
