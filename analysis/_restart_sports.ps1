# Clean-restart the sports paper bot to exactly one instance.
$root = "C:\Users\matti\Desktop\prediction-market-analysis"
schtasks /end /tn PolyBotSports 2>$null | Out-Null
Start-Sleep -Seconds 2
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -and $_.CommandLine.Contains('sports_fade_bot') } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2
if (Test-Path "$root\watchdog_sports.lock") { Remove-Item "$root\watchdog_sports.lock" -Force }
schtasks /run /tn PolyBotSports | Out-Null
Write-Output "sports clean-restarted"
