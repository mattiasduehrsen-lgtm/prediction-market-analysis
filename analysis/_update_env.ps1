$f = "C:\Users\matti\Desktop\prediction-market-analysis\.env"
(Get-Content $f) -replace "LIVE_MAX_DAILY_LOSS_USD=50.0", "LIVE_MAX_DAILY_LOSS_USD=75.0" | Set-Content $f
if (-not (Select-String -Path $f -Pattern "ESPORTS_STARTING_DEPOSIT_USD" -Quiet)) {
    Add-Content $f "ESPORTS_STARTING_DEPOSIT_USD=749"
}
Get-Content $f | Select-String "LIVE_MAX_DAILY_LOSS|ESPORTS_STARTING|LIVE_POSITION_SIZE"
