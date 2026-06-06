# Restart the CS2 in-play PAPER bot (paper — safe). Kills the process; the
# watchdog .bat relaunches it with the latest code within ~10s.
$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*cs2_inplay_bot*' }
if (-not $procs) {
    Write-Output "no cs2_inplay_bot process (watchdog will start it)"
} else {
    foreach ($p in $procs) {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Output ("killed PID " + $p.ProcessId)
    }
}
