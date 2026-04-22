$base = "C:\Users\matti\Desktop\prediction-market-analysis"
Set-Location $base
$python   = "$base\.venv\Scripts\python.exe"
$watchlog = "$base\watchdog_paper.log"

function Write-Log($msg) {
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content $watchlog "$ts [WATCHDOG-PAPER] $msg"
}

# Guard: exit if another watchdog instance is already running.
# Uses Get-CimInstance (not Get-WmiObject — removed in PS7+).
# Anchors on powershell/pwsh host + path separator to avoid false-positives
# from editors or search tools that have 'watch_paper.ps1' in their argv.
$self = $PID
$others = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -in 'powershell.exe','pwsh.exe' -and
    $_.CommandLine -like '*\watch_paper.ps1*' -and
    $_.ProcessId -ne $self
}
if ($others) {
    Write-Log "Duplicate watchdog (PIDs: $($others.ProcessId -join ',')) - exiting."
    exit 1
}

Write-Log "Watchdog started (PID $self)"

while ($true) {
    Write-Log "Starting multi-loop..."
    & $python -u "$base\main.py" multi-loop
    Write-Log "multi-loop exited (code $LASTEXITCODE) - restarting in 10s..."
    Start-Sleep -Seconds 10
}
