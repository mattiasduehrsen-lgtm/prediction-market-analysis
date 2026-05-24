schtasks /end /tn PolyBotEsports
Start-Sleep -Seconds 3
Stop-Process -Name python -ErrorAction SilentlyContinue -Force
Start-Sleep -Seconds 2
# Also clear watchdog lock in case it was left behind by the kill
$lock = "C:\Users\matti\Desktop\prediction-market-analysis\watchdog_esports.lock"
if (Test-Path $lock) { Remove-Item $lock -Force }
schtasks /run /tn PolyBotEsports
Start-Sleep -Seconds 10
Write-Output "---- python processes ----"
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Select-Object ProcessId, CommandLine |
    Format-List
Write-Output "---- last 8 lines of bot log ----"
Get-Content "C:\Users\matti\Desktop\prediction-market-analysis\watchdog_esports.log" -Tail 8
