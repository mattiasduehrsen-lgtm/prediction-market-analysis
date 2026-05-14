# Installs ReconcileBackfill scheduled task.
# Runs backfill_missing_trades.py every 4 hours to catch any new orphan
# losses (positions that the bot opened, the market resolved, but the bot
# never recorded a closure).

$python = "C:\Users\matti\Desktop\prediction-market-analysis\.venv\Scripts\python.exe"
$script = "C:\Users\matti\Desktop\prediction-market-analysis\backfill_missing_trades.py"

$action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument $script `
    -WorkingDirectory "C:\Users\matti\Desktop\prediction-market-analysis"

# Every 4 hours
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddHours(2) -RepetitionInterval (New-TimeSpan -Hours 4)

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERNAME" `
    -LogonType S4U `
    -RunLevel Limited

try {
    Register-ScheduledTask `
        -TaskName "ReconcileBackfill" `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description "Every 4 hours: query Polymarket for orphan positions, append missing-loss rows to trades_*.csv" `
        -Force
    Write-Host "[install] ReconcileBackfill task created. Runs every 4 hours."
} catch {
    Write-Host "[ERROR] $_" -ForegroundColor Red
    Write-Host "Try running this script as Administrator." -ForegroundColor Yellow
}
