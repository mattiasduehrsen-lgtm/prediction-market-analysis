# install_rotate_task.ps1 - one-time setup. Creates a weekly scheduled task
# that runs rotate_logs.ps1 every Sunday at 04:30 local time. Run as admin.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File install_rotate_task.ps1

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -File C:\Users\matti\Desktop\prediction-market-analysis\rotate_logs.ps1 -SizeMB 200"

$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "04:30"

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RunOnlyIfNetworkAvailable:$false

$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERNAME" `
    -LogonType S4U `
    -RunLevel Highest

try {
    Register-ScheduledTask `
        -TaskName "RotateBotLogs" `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description "Weekly rotation of bot.log and dashboard.log. Runs only if bot.log > 200 MB." `
        -Force
    Write-Host "[install] RotateBotLogs scheduled task installed."
    Write-Host "[install] Trigger: every Sunday at 04:30."
    Write-Host "[install] Action:  rotate_logs.ps1 -SizeMB 200"
} catch {
    Write-Host "[ERROR] $_" -ForegroundColor Red
    Write-Host "Try running this script as Administrator." -ForegroundColor Yellow
}
