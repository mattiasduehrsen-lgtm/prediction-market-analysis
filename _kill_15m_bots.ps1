# Hard-stop the 15m crypto bots (multi-live + multi-loop processes)
# without touching the esports/telegram/dashboard stack.

Write-Host "=== Disabling tasks ==="
foreach ($t in 'PolyBot','PolyBotPaper','PolyBotLive','RunBot') {
    schtasks /change /tn $t /disable 2>&1 | Out-Null
    Write-Host "  $t disabled"
}

Write-Host ""
Write-Host "=== Ending tasks ==="
foreach ($t in 'PolyBot','PolyBotPaper','PolyBotLive','RunBot') {
    schtasks /end /tn $t 2>&1 | Out-Null
    Write-Host "  $t ended"
}

Write-Host ""
Write-Host "=== Killing multi-live and multi-loop python processes ==="
$kill = Get-WmiObject Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -match 'multi-live|multi-loop' }
foreach ($p in $kill) {
    $cmd = $p.CommandLine
    if ($cmd.Length -gt 100) { $cmd = $cmd.Substring(0,100) + '...' }
    Write-Host "  Kill PID $($p.ProcessId): $cmd"
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "=== Killing watchdog cmd.exe parents ==="
$wd = Get-WmiObject Win32_Process -Filter "Name='cmd.exe'" |
      Where-Object { $_.CommandLine -match 'watch_bot|watch_paper' }
foreach ($p in $wd) {
    Write-Host "  Kill watchdog PID $($p.ProcessId)"
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}

Start-Sleep -Seconds 3
Write-Host ""
Write-Host "=== Final state ==="
Get-WmiObject Win32_Process -Filter "Name='python.exe'" |
    ForEach-Object {
        $cmd = $_.CommandLine
        if ($cmd.Length -gt 100) { $cmd = $cmd.Substring(0,100) + '...' }
        "  PID $($_.ProcessId): $cmd"
    }
