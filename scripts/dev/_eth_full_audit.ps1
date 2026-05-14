$f = "C:\Users\matti\Desktop\prediction-market-analysis\output\5m_live\trades_ETH-15m.csv"
$rows = Import-Csv $f
Write-Host "Total ETH-15m trades: $($rows.Count)"
Write-Host ""
Write-Host "All ETH trades sorted by opened_at:"
Write-Host "{0,-9} {1,-8} {2,-5} {3,-6} {4,-6} {5,-20} {6,-15}" -f "ID","side","entry","exit","pnl","opened_at","exit_reason"
foreach ($r in ($rows | Sort-Object { [double]$_.opened_at })) {
    $id = $r.position_id.Substring(0, [Math]::Min(8, $r.position_id.Length))
    $dt = [DateTimeOffset]::FromUnixTimeSeconds([int][double]$r.opened_at).ToString("MM-dd HH:mm UTC")
    "{0,-9} {1,-8} {2,-6} {3,-6} {4,-7} {5,-20} {6,-15}" -f $id, $r.side, $r.entry_price, $r.exit_price, $r.pnl_usd, $dt, $r.exit_reason
}
Write-Host ""
Write-Host "=== Open positions in positions_ETH-15m.csv ==="
$pos = Import-Csv "C:\Users\matti\Desktop\prediction-market-analysis\output\5m_live\positions_ETH-15m.csv"
Write-Host "Count: $($pos.Count)"
foreach ($p in $pos) {
    Write-Host "  $($p.position_id.Substring(0,8)) state=$($p.state) entry=$($p.entry_price) opened_at=$($p.opened_at)"
}
