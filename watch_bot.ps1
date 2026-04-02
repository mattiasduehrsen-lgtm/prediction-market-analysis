Set-Location "C:\Users\matti\Desktop\prediction-market-analysis"

while ($true) {
    Write-Host "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [WATCHDOG] Starting bot..."
    & ".\.venv\Scripts\python.exe" -u main.py paper-loop
    $code = $LASTEXITCODE
    Write-Host "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [WATCHDOG] Bot exited (code $code) — restarting in 10s..."
    Start-Sleep -Seconds 10
}
