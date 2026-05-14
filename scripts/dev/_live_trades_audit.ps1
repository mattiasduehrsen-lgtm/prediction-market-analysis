# Audit recent LIVE trades for missing/suspicious entries
$root = "C:\Users\matti\Desktop\prediction-market-analysis"

foreach ($asset in @("BTC", "ETH", "SOL")) {
    $f = "$root\output\5m_live\trades_$asset-15m.csv"
    if (-not (Test-Path $f)) {
        Write-Host "$asset : (no file)"
        continue
    }
    $lines = Get-Content $f
    $n = $lines.Count - 1   # minus header
    Write-Host "=== $asset-15m  total trades: $n  last write: $((Get-Item $f).LastWriteTime) ==="
    if ($n -gt 0) {
        Write-Host ($lines | Select-Object -Last 5)
    }
    Write-Host ""
}

Write-Host "=== Positions ==="
foreach ($asset in @("BTC", "ETH", "SOL")) {
    $f = "$root\output\5m_live\positions_$asset-15m.csv"
    if (Test-Path $f) {
        $lines = Get-Content $f
        Write-Host "$asset positions:"
        $lines | ForEach-Object { Write-Host "  $_" }
    }
    Write-Host ""
}
