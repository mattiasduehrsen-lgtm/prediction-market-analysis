# Installs DailySummary scheduled task: runs daily_summary.py every day at 23:55 local.
# Output: output/daily_summary/YYYY-MM-DD.json + .md

$python = "C:\Users\matti\Desktop\prediction-market-analysis\.venv\Scripts\python.exe"
$script = "C:\Users\matti\Desktop\prediction-market-analysis\daily_summary.py"

$action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument $script `
    -WorkingDirectory "C:\Users\matti\Desktop\prediction-market-analysis"

$trigger = New-ScheduledTaskTrigger -Daily -At "23:55"

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
        -TaskName "DailySummary" `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description "Writes output/daily_summary/YYYY-MM-DD.{json,md} every day at 23:55." `
        -Force
    Write-Host "[install] DailySummary task created. First run: today 23:55."
} catch {
    Write-Host "[ERROR] $_" -ForegroundColor Red
    Write-Host "Try running this script as Administrator." -ForegroundColor Yellow
}
