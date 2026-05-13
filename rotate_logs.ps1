# rotate_logs.ps1 - safely rotate bot.log and related logs.
#
# Strategy: stop schtasks (releases the open file handles), rename bot.log to
# bot.log.YYYY-MM-DD-HHMM, gzip old rotations, delete rotations older than 14
# days, then restart schtasks. Preserves paused.live.flag throughout.
#
# Trigger options:
#   1. Manual:                 powershell -ExecutionPolicy Bypass -File rotate_logs.ps1
#   2. Weekly scheduled task:  RotateBotLogs (created by install_rotate_task.ps1)
#   3. Size-trigger inline:    rotate_logs.ps1 -SizeMB 500   (only rotates if bot.log > 500 MB)

param(
    [int]$SizeMB = 0  # if >0, only rotate when bot.log exceeds this MB
)

$ErrorActionPreference = "Continue"
$root      = "C:\Users\matti\Desktop\prediction-market-analysis"
$logFile   = "$root\bot.log"
$dashLog   = "$root\dashboard.log"
$pauseFlag = "$root\output\5m_live\paused.live.flag"

Write-Host "=== rotate_logs.ps1 $(Get-Date) ===" -ForegroundColor Cyan

# Optional size gate
if ($SizeMB -gt 0) {
    if (-not (Test-Path $logFile)) {
        Write-Host "[skip] bot.log not present"
        exit 0
    }
    $sizeMb = (Get-Item $logFile).Length / 1MB
    if ($sizeMb -lt $SizeMB) {
        Write-Host ("[skip] bot.log is {0:N0} MB, below threshold {1} MB" -f $sizeMb, $SizeMB)
        exit 0
    }
    Write-Host ("[trigger] bot.log is {0:N0} MB >= {1} MB threshold" -f $sizeMb, $SizeMB)
}

# Capture pause state
$wasPaused = Test-Path $pauseFlag
Write-Host "LIVE pause flag was: $wasPaused"

# Stop processes (releases file locks)
Write-Host "`n--- Stopping tasks ---"
schtasks /end /tn PolyBotPaper 2>&1
schtasks /end /tn PolyBot 2>&1
schtasks /end /tn PolyDashboard 2>&1
Start-Sleep -Seconds 4    # let task trees finish exiting
Stop-Process -Name python -Force -ErrorAction SilentlyContinue
Stop-Process -Name powershell -Force -ErrorAction SilentlyContinue -InformationAction SilentlyContinue 2>$null   # watchdog ps1
# Belt-and-braces: kill any lingering cmd.exe instances running our watch_*.bat
Get-CimInstance Win32_Process -Filter "name='cmd.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "watch_paper\.bat|watch_bot" } |
    ForEach-Object {
        try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {}
    }

# Poll until no python.exe remains (max 30s)
Write-Host "[wait] polling for python.exe to fully exit..."
for ($i = 0; $i -lt 30; $i++) {
    $py = Get-Process -Name python -ErrorAction SilentlyContinue
    if (-not $py) {
        Write-Host ("[wait] python.exe is gone after {0}s" -f $i)
        break
    }
    Start-Sleep -Seconds 1
}
Start-Sleep -Seconds 2    # extra grace for OS to release handles

# Rotate logs with retry on file-locked errors
function Rotate-WithRetry {
    param([string]$Path, [string]$NewName, [int]$MaxRetries = 6, [int]$DelaySec = 2)
    for ($i = 0; $i -lt $MaxRetries; $i++) {
        try {
            Rename-Item -Path $Path -NewName $NewName -ErrorAction Stop
            return $true
        } catch {
            if ($i -eq $MaxRetries - 1) {
                Write-Host ("[ERROR] rotate {0} failed after {1} retries: {2}" -f $Path, $MaxRetries, $_) -ForegroundColor Red
                return $false
            }
            Write-Host ("[retry {0}/{1}] file still locked, waiting {2}s..." -f ($i+1), $MaxRetries, $DelaySec)
            Start-Sleep -Seconds $DelaySec
        }
    }
    return $false
}

$stamp = Get-Date -Format "yyyy-MM-dd-HHmm"
foreach ($f in @($logFile, $dashLog)) {
    if (Test-Path $f) {
        $sizeMb = (Get-Item $f).Length / 1MB
        $newName = (Split-Path $f -Leaf) + ".$stamp"
        if (Rotate-WithRetry -Path $f -NewName $newName) {
            Write-Host ("[rotated] {0} ({1:N1} MB) -> {2}" -f (Split-Path $f -Leaf), $sizeMb, $newName)
        }
    }
}

# Compress rotations older than 1 day, delete older than 14 days
$cutoffCompress = (Get-Date).AddDays(-1)
$cutoffDelete   = (Get-Date).AddDays(-14)

foreach ($pattern in @("bot.log.*", "dashboard.log.*")) {
    Get-ChildItem -Path $root -Filter $pattern -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.Name -match "\.gz$") {
            if ($_.LastWriteTime -lt $cutoffDelete) {
                Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
                Write-Host "[deleted] $($_.Name) (>14 days)"
            }
        } else {
            if ($_.LastWriteTime -lt $cutoffCompress) {
                $gz = "$($_.FullName).gz"
                try {
                    $src = [System.IO.File]::OpenRead($_.FullName)
                    $dst = [System.IO.File]::Create($gz)
                    $cmp = New-Object System.IO.Compression.GZipStream($dst, [System.IO.Compression.CompressionMode]::Compress)
                    $src.CopyTo($cmp)
                    $cmp.Close(); $dst.Close(); $src.Close()
                    Remove-Item $_.FullName -Force
                    Write-Host "[compressed] $($_.Name) -> $($_.Name).gz"
                } catch {
                    Write-Host "[ERROR] compress $($_.Name) failed: $_" -ForegroundColor Red
                }
            }
        }
    }
}

# Restart tasks
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
Write-Host "`nProcesses up: paper=$nLoop live=$nLive dash=$nDash (expect 2/2/2)"

$stillPaused = Test-Path $pauseFlag
Write-Host "Pause flag: was=$wasPaused now=$stillPaused"
if ($wasPaused -and -not $stillPaused) {
    Write-Host "[ALERT] pause flag was lost during rotation!" -ForegroundColor Red
}

Write-Host "`n=== Done ===" -ForegroundColor Cyan
