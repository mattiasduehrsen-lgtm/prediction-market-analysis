# Restart just the CS2 model paper bot (paper — safe to restart freely).
# Kills the cs2_model_bot.py python process; the watchdog .bat relaunches it
# with the latest code within ~10s.
$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*cs2_model_bot*' }
if (-not $procs) {
    Write-Output "no cs2_model_bot process found (watchdog will start it)"
} else {
    foreach ($p in $procs) {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Output ("killed PID " + $p.ProcessId)
    }
}
