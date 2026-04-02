Set-Location "C:\Users\matti\Desktop\prediction-market-analysis"

$watchlog = "C:\Users\matti\Desktop\prediction-market-analysis\watchdog.log"

while ($true) {
    $ts = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
    Add-Content $watchlog "$ts [WATCHDOG] Starting bot (paper-loop)..."
    # Capture any output that leaks through before the Python logging redirect
    & ".\.venv\Scripts\python.exe" -u main.py paper-loop 2>>"$watchlog"
    $code = $LASTEXITCODE
    $ts2 = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
    Add-Content $watchlog "$ts2 [WATCHDOG] Bot exited (code $code) — restarting in 10s..."
    Start-Sleep -Seconds 10
}
