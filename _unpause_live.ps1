# Removes paused.live.flag and verifies. Run on laptop.
$f = "C:\Users\matti\Desktop\prediction-market-analysis\output\5m_live\paused.live.flag"
if (Test-Path $f) {
    Remove-Item $f -Force
    Write-Host "[unpause] removed paused.live.flag"
} else {
    Write-Host "[unpause] flag was not present"
}
$still = Test-Path $f
Write-Host "[unpause] flag exists now: $still"
if (-not $still) {
    Write-Host "[unpause] LIVE trading is now ENABLED for ETH-15m (WR-gated) + SOL-15m (unconditional)"
}
