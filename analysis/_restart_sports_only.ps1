# Restart ONLY the sports bot (leave esports/telegram/dashboard alone).
$base = "C:\Users\matti\Desktop\prediction-market-analysis"

schtasks /end /tn PolyBotSports 2>$null
Start-Sleep -Seconds 2
# Kill ONLY sports_fade_bot processes — surgical, don't touch esports
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match "sports_fade_bot" } |
    ForEach-Object {
        Write-Output "  killing sports PID $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
Start-Sleep -Seconds 2
$lock = "$base\watchdog_sports.lock"
if (Test-Path $lock) { Remove-Item $lock -Force }
schtasks /run /tn PolyBotSports
Start-Sleep -Seconds 10
Write-Output "---- sports startup ----"
Get-Content "$base\watchdog_sports.log" -Tail 8
