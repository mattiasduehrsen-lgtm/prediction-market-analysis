# truncate_bot_log.ps1 — one-shot. Stops the bot, truncates bot.log in place
# (preserves the file inode and any open file handles), restarts the bot.
#
# Use when the rotate-rename path fails because Windows Defender keeps a lock
# on the file. Set-Content -Value '' uses different sharing semantics and can
# sometimes win where Rename-Item can't.
#
# Run as: powershell -ExecutionPolicy Bypass -File truncate_bot_log.ps1

$ErrorActionPreference = "Continue"
$root      = "C:\Users\matti\Desktop\prediction-market-analysis"
$logFile   = "$root\bot.log"
$pauseFlag = "$root\output\5m_live\paused.live.flag"

Write-Host "=== truncate_bot_log.ps1 $(Get-Date) ===" -ForegroundColor Cyan

if (-not (Test-Path $logFile)) {
    Write-Host "[skip] bot.log not present"
    exit 0
}
$sizeMb = (Get-Item $logFile).Length / 1MB
Write-Host ("Current bot.log size: {0:N1} MB" -f $sizeMb)

$wasPaused = Test-Path $pauseFlag
Write-Host "LIVE pause flag: $wasPaused"

# Stop tasks cleanly
$myPid = $PID
Write-Host "`n--- Stopping tasks ---"
schtasks /end /tn PolyBotPaper 2>&1
schtasks /end /tn PolyBot 2>&1
schtasks /end /tn PolyDashboard 2>&1
Start-Sleep -Seconds 4

# Kill watchdog cmd.exe + watchdog powershell (NOT our own session)
Get-CimInstance Win32_Process -Filter "name='cmd.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "watch_paper\.bat|watch_bot" } |
    ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }
Get-CimInstance Win32_Process -Filter "name='powershell.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "watch_bot\.ps1" -and $_.ProcessId -ne $myPid } |
    ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }

Stop-Process -Name python -Force -ErrorAction SilentlyContinue

# Poll until python is gone
for ($i = 0; $i -lt 30; $i++) {
    if (-not (Get-Process -Name python -ErrorAction SilentlyContinue)) {
        Write-Host "[wait] python gone after $i s"
        break
    }
    Start-Sleep -Seconds 1
}
Start-Sleep -Seconds 3

# Try multiple truncation strategies. None require renaming — just emptying.
$truncated = $false
$strategies = @(
    @{ name = "Clear-Content"; action = { Clear-Content -Path $logFile -Force -ErrorAction Stop } },
    @{ name = "Set-Content (empty)"; action = { Set-Content -Path $logFile -Value $null -Force -ErrorAction Stop } },
    @{ name = ".NET FileStream SetLength(0)"; action = {
        $fs = [System.IO.File]::Open($logFile, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Write, [System.IO.FileShare]::ReadWrite)
        $fs.SetLength(0)
        $fs.Close()
    } },
    @{ name = "Remove-Item + recreate"; action = {
        Remove-Item -Path $logFile -Force -ErrorAction Stop
        New-Item -Path $logFile -ItemType File -Force | Out-Null
    } }
)

foreach ($s in $strategies) {
    try {
        & $s.action
        Start-Sleep -Seconds 1
        $newSize = (Get-Item $logFile -ErrorAction SilentlyContinue).Length
        if ($newSize -lt 10000) {
            Write-Host "[ok] truncated via '$($s.name)' - new size $newSize bytes" -ForegroundColor Green
            $truncated = $true
            break
        }
    } catch {
        Write-Host "[try] '$($s.name)' failed: $($_.Exception.Message.Substring(0, [Math]::Min(80, $_.Exception.Message.Length)))"
    }
}

if (-not $truncated) {
    Write-Host "[FAIL] could not truncate bot.log. Restarting bot anyway." -ForegroundColor Red
}

# Restart
Write-Host "`n--- Restarting tasks ---"
schtasks /run /tn PolyBotPaper 2>&1
schtasks /run /tn PolyBot 2>&1
schtasks /run /tn PolyDashboard 2>&1
Start-Sleep -Seconds 15

# Verify
$procs = Get-CimInstance Win32_Process -Filter "name='python.exe'"
$nLoop = ($procs | Where-Object { $_.CommandLine -like '*multi-loop*' }).Count
$nLive = ($procs | Where-Object { $_.CommandLine -like '*multi-live*' }).Count
$nDash = ($procs | Where-Object { $_.CommandLine -like '*dashboard*' }).Count
Write-Host "Processes: paper=$nLoop live=$nLive dash=$nDash"

$stillPaused = Test-Path $pauseFlag
Write-Host "Pause flag preserved: was=$wasPaused now=$stillPaused"
if ($wasPaused -and -not $stillPaused) {
    Write-Host "[ALERT] pause flag was lost!" -ForegroundColor Red
}
Write-Host "Done." -ForegroundColor Cyan
