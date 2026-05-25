# End ALL related scheduled tasks first so Stop-Process below doesn't orphan watchdogs.
# Stop-Process -Name python kills every python on the box; we must restart every
# task that owns a python child, not just PolyBotEsports.
schtasks /end /tn PolyBotEsports 2>$null
schtasks /end /tn PolyBotTelegram 2>$null
schtasks /end /tn PolyDashboard 2>$null
schtasks /end /tn PolyBotSports 2>$null
Start-Sleep -Seconds 3
Stop-Process -Name python -ErrorAction SilentlyContinue -Force
Start-Sleep -Seconds 2
foreach ($name in "watchdog_esports.lock","watchdog_telegram.lock","watchdog_dashboard.lock","watchdog_sports.lock") {
    $lock = "C:\Users\matti\Desktop\prediction-market-analysis\$name"
    if (Test-Path $lock) { Remove-Item $lock -Force }
}
schtasks /run /tn PolyBotEsports
schtasks /run /tn PolyBotTelegram
schtasks /run /tn PolyDashboard
schtasks /run /tn PolyBotSports
Start-Sleep -Seconds 12
Write-Output "---- python processes ----"
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Select-Object ProcessId, CommandLine |
    Format-List
Write-Output "---- last 8 lines of bot log ----"
Get-Content "C:\Users\matti\Desktop\prediction-market-analysis\watchdog_esports.log" -Tail 8
