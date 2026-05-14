# Installs BackupOutputs scheduled task: runs backup_outputs.ps1 daily at 00:30 local.
# Compresses output/ to backups/output-YYYY-MM-DD-HHMM.zip; keeps last 30 days.

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -File C:\Users\matti\Desktop\prediction-market-analysis\backup_outputs.ps1"

$trigger = New-ScheduledTaskTrigger -Daily -At "00:30"

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
        -TaskName "BackupOutputs" `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description "Daily zip backup of output/ to backups/. Keeps last 30 days." `
        -Force
    Write-Host "[install] BackupOutputs task created. Runs daily at 00:30."
} catch {
    Write-Host "[ERROR] $_" -ForegroundColor Red
    Write-Host "Try running this script as Administrator." -ForegroundColor Yellow
}
