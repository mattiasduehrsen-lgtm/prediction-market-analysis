$log = "C:\Users\matti\Desktop\prediction-market-analysis\bot.log"
Write-Host "=== Last 5 BRAIN Initialized ==="
Select-String -Path $log -Pattern "BRAIN. Initialized" | Select-Object -Last 5 | ForEach-Object { $_.Line }
Write-Host ""
Write-Host "=== Last 8 brain advise() calls ==="
Select-String -Path $log -Pattern "BRAIN. [A-Z][A-Z][A-Z] regime=" | Select-Object -Last 8 | ForEach-Object { $_.Line }
