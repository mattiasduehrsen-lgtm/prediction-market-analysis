$tasks = @("PolyBotEsports","PolyBotTelegram","PolyDashboard","PolyBotSports","PolyBotSportsEval")
Write-Output "---- BEFORE ----"
foreach ($t in $tasks) {
    try {
        $info = schtasks /query /tn $t /fo CSV /nh 2>$null
        Write-Output "$t : $info"
    } catch { Write-Output "$t : MISSING" }
}

Write-Output ""
Write-Output "---- python processes BEFORE ----"
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Select-Object ProcessId, CommandLine | Format-List

Write-Output ""
Write-Output "---- starting any non-running tasks ----"
foreach ($t in $tasks) {
    $line = schtasks /query /tn $t /fo CSV /nh 2>$null
    if ($line -notmatch "Running") {
        # Clear any stale lock
        $logname = switch ($t) {
            "PolyBotEsports"   { "watchdog_esports.lock" }
            "PolyBotTelegram"  { "watchdog_telegram.lock" }
            "PolyDashboard"    { "watchdog_dashboard.lock" }
            "PolyBotSports"    { "watchdog_sports.lock" }
            default            { $null }
        }
        if ($logname) {
            $lock = "C:\Users\matti\Desktop\prediction-market-analysis\$logname"
            if (Test-Path $lock) { Remove-Item $lock -Force; Write-Output "  cleared $logname" }
        }
        Write-Output "  starting $t..."
        schtasks /run /tn $t 2>&1 | Out-String | ForEach-Object { "    $_" }
    } else {
        Write-Output "  $t already running"
    }
}

Start-Sleep -Seconds 12

Write-Output ""
Write-Output "---- python processes AFTER ----"
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Select-Object ProcessId, CommandLine | Format-List
