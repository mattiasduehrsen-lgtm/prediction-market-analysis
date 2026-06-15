# Clean-restart the sports paper bot to exactly one instance.
$root = "C:\Users\matti\Desktop\prediction-market-analysis"
schtasks /end /tn PolyBotSports 2>$null | Out-Null
Start-Sleep -Seconds 2
# kill BOTH the orphan watchdog cmd.exe (watch_sports_fade.bat) AND the python,
# else a stray watchdog respawns a second instance (the 4-proc duplicate).
Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -and ($_.CommandLine -match 'watch_sports_fade|sports_fade_bot') } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 3
if (Test-Path "$root\watchdog_sports.lock") { Remove-Item "$root\watchdog_sports.lock" -Force }
schtasks /run /tn PolyBotSports | Out-Null
Write-Output "sports clean-restarted"
