$base = "C:\Users\matti\Desktop\prediction-market-analysis"
Set-Location $base

$python  = "$base\.venv\Scripts\python.exe"
$watchlog = "$base\watchdog.log"

while ($true) {
    # Kill any orphaned python processes before starting fresh
    taskkill /F /IM python.exe 2>&1 | Out-Null
    Start-Sleep -Seconds 1

    $ts = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
    Add-Content $watchlog "$ts [WATCHDOG] Starting btc-5m-loop..."
    & $python -u "$base\main.py" btc-5m-loop
    $code = $LASTEXITCODE
    $ts2 = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
    Add-Content $watchlog "$ts2 [WATCHDOG] Bot exited (code $code) - restarting in 10s..."
    Start-Sleep -Seconds 10
}
