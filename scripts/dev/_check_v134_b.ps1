$log = "C:\Users\matti\Desktop\prediction-market-analysis\bot.log"
Write-Host "=== Brain inits in last 500 lines of bot.log ==="
Get-Content $log -Tail 500 | Select-String -Pattern "BRAIN. Initialized" | ForEach-Object { $_.Line }
Write-Host ""
Write-Host "=== ETH-15m LIVE entries / WR-FILTER messages in last 500 lines ==="
Get-Content $log -Tail 500 | Select-String -Pattern "WR-FILTER" | ForEach-Object { $_.Line }
