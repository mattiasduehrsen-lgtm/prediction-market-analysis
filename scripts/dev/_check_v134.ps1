$log = "C:\Users\matti\Desktop\prediction-market-analysis\bot.log"
Write-Host "=== Recent MULTI thread starts ==="
Select-String -Path $log -Pattern "MULTI. Started" | Select-Object -Last 12 | ForEach-Object { $_.Line }
Write-Host ""
Write-Host "=== Recent BRAIN initializations ==="
Select-String -Path $log -Pattern "BRAIN. Initialized" | Select-Object -Last 5 | ForEach-Object { $_.Line }
Write-Host ""
Write-Host "=== Recent startup banners ==="
Select-String -Path $log -Pattern "Bot \[(PAPER|LIVE)" | Select-Object -Last 10 | ForEach-Object { $_.Line }
