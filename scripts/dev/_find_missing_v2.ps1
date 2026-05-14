# Smarter search for the missing 18:30 UTC May 13 ETH trade.
# Look for any eth-updown-15m slug in the 17:30-20:30 UTC May 13 range.
$log = "C:\Users\matti\Desktop\prediction-market-analysis\bot.log"

# Computed epoch boundaries for May 13 2026 17:30-20:30 UTC
# Need a known epoch anchor. From our records: ea52b7f7 at 05-13 22:00 UTC has
# window_end_ts=1778710500. So 22:00 UTC = 1778710500. We want 18:30 UTC =
# 1778710500 - (3.5 * 3600) = 1778710500 - 12600 = 1778697900 (rough).
# Actually 22:00 - 18:30 = 3.5h. 1778710500 - 12600 = 1778697900.
# That's window_END=18:45 UTC, so window_START = 1778697000.

$candidates = @()
for ($t = 1778693400; $t -le 1778704200; $t += 900) {
    $candidates += "eth-updown-15m-$t"
}
Write-Host "Searching $($candidates.Count) candidate ETH 15m window slugs around 18:30 UTC May 13..."

foreach ($slug in $candidates) {
    $hits = Select-String -Path $log -Pattern $slug -SimpleMatch -ErrorAction SilentlyContinue
    if ($hits) {
        Write-Host ""
        Write-Host "FOUND: $slug ($(($hits | Measure-Object).Count) hits)" -ForegroundColor Yellow
        $hits | Select-Object -First 5 | ForEach-Object { Write-Host "  $($_.Line)" }
    }
}

Write-Host ""
Write-Host "=== Any ENTRY/OPEN/BUY for ETH UP @ 0.40 in last 6000 lines ==="
Get-Content $log -Tail 200000 |
    Select-String -Pattern "ETH.*UP.*0\.40|ETH.*UP.*\$5\.0[56]|place_entry.*ETH|ENTRY.*ETH" |
    Select-Object -Last 20 |
    ForEach-Object { Write-Host $_.Line }
