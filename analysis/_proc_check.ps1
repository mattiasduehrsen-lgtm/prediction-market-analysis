Write-Output "---- python processes ----"
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Select-Object ProcessId, CommandLine | Format-List
Write-Output "---- telegram log tail ----"
Get-Content "C:\Users\matti\Desktop\prediction-market-analysis\watchdog_telegram.log" -Tail 10
Write-Output "---- esports log tail ----"
Get-Content "C:\Users\matti\Desktop\prediction-market-analysis\watchdog_esports.log" -Tail 5
