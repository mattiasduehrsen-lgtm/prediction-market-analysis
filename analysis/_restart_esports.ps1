# End all related scheduled tasks first so Stop-Process below doesn't orphan watchdogs.
schtasks /end /tn PolyBotEsports 2>$null
schtasks /end /tn PolyBotTelegram 2>$null
Start-Sleep -Seconds 3
Stop-Process -Name python -ErrorAction SilentlyContinue -Force
Start-Sleep -Seconds 2
# Clear all watchdog locks (Stop-Process leaves them stale)
foreach ($name in "watchdog_esports.lock", "watchdog_telegram.lock") {
    $lock = "C:\Users\matti\Desktop\prediction-market-analysis\$name"
    if (Test-Path $lock) { Remove-Item $lock -Force }
}
# Restart all related tasks (NEVER omit telegram - killing python kills it too)
schtasks /run /tn PolyBotEsports
schtasks /run /tn PolyBotTelegram
Start-Sleep -Seconds 10
Write-Output "---- python processes ----"
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Select-Object ProcessId, CommandLine |
    Format-List
Write-Output "---- last 8 lines of bot log ----"
Get-Content "C:\Users\matti\Desktop\prediction-market-analysis\watchdog_esports.log" -Tail 8
