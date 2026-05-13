$log = "C:\Users\matti\Desktop\prediction-market-analysis\bot.log"
$tail = Get-Content $log -Tail 6000
Write-Host "=== Brain inits in last 6000 lines ==="
$tail | Select-String -Pattern "BRAIN. Initialized" | ForEach-Object { $_.Line }
Write-Host ""
Write-Host "=== WR-FILTER messages in last 6000 lines ==="
$tail | Select-String -Pattern "WR-FILTER" | ForEach-Object { $_.Line }
Write-Host ""
Write-Host "=== Most recent BRAIN advise() calls (last 4) ==="
$tail | Select-String -Pattern "BRAIN. [A-Z][A-Z][A-Z] regime=" | Select-Object -Last 4 | ForEach-Object { $_.Line }
