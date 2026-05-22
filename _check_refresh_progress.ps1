# Check refresh progress
$root = 'C:\Users\matti\Desktop\prediction-market-analysis'
$json = "$root\cowork_snapshot\esports\fade_targets.json"
$log = "$root\output\esports_fade\refresh.log"

Write-Host "--- fade_targets.json ---"
$j = Get-Content $json -Raw | ConvertFrom-Json
Write-Host "  LIVE wallets:  $($j.target_wallets.Count)"
Write-Host "  Generated:     $($j.generated_at)"
Write-Host "  Games:         $($j.games -join ', ')"

Write-Host ""
Write-Host "--- Last 8 lines of refresh log ---"
Get-Content $log -Tail 8
