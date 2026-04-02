$base = "C:\Users\matti\Desktop\prediction-market-analysis"
Set-Location $base

$python  = "$base\.venv\Scripts\python.exe"
$watchlog = "$base\watchdog.log"

while ($true) {
    $ts = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
    Add-Content $watchlog "$ts [WATCHDOG] Starting bot..."
    & $python -u "$base\main.py" paper-loop
    $code = $LASTEXITCODE
    $ts2 = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
    Add-Content $watchlog "$ts2 [WATCHDOG] Bot exited (code $code) - restarting in 10s..."
    Start-Sleep -Seconds 10
}
