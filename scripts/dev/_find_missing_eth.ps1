# Search bot.log for ETH 15m market activity at the missing-trade epoch.
# Window 14:30-14:45 PM ET = 18:30-18:45 UTC May 13 ≈ epoch 1778705100..1778706000

$log = "C:\Users\matti\Desktop\prediction-market-analysis\bot.log"

Write-Host "=== Lines mentioning the missing ETH market (window starts 18:30 UTC May 13) ==="
# Search for the window_start epoch in the slug
$patterns = @("eth-updown-15m-1778705100", "eth-updown-15m-1778704200", "eth-updown-15m-1778706000", "eth-updown-15m-1778706900")
foreach ($p in $patterns) {
    $hits = Select-String -Path $log -Pattern $p -SimpleMatch -ErrorAction SilentlyContinue
    if ($hits) {
        Write-Host ""
        Write-Host "[matches for $p]"
        $hits | Select-Object -First 20 | ForEach-Object { $_.Line }
    }
}

Write-Host ""
Write-Host "=== ENTRY/EXIT/CLOSE events for ETH around 18:30 UTC ==="
# Look for ENTRY/EXIT/CLOSE log lines that include ETH
$hits = Select-String -Path $log -Pattern "LIVE.*ETH.*(ENTRY|EXIT|CLOSE|OPEN|TP_ORDER|FOK)" -ErrorAction SilentlyContinue
if ($hits) {
    $hits | Select-Object -Last 40 | ForEach-Object { $_.Line }
} else {
    Write-Host "(none found)"
}
