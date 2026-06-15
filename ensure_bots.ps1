# Health guard: revive any dead bot. Runs every 5 min as SYSTEM (regardless of
# logon). Root-cause fix for the 2026-06-08 multi-day outage: onstart-only tasks
# don't recover a bot that dies without a reboot.
#
# IMPORTANT: a dead bot often leaves its task STUCK in a "running" state (the
# watchdog cmd died but Task Scheduler still thinks it's running), so plain
# `schtasks /run` is a no-op. We must /end THEN /run (the project's documented
# restart requirement). Earlier guard versions only did /run -> never revived.
$root = "C:\Users\matti\Desktop\prediction-market-analysis"
Set-Location $root
$log = "$root\health_guard.log"
function Log($m) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $m" | Out-File -Append -Encoding utf8 $log }

$map = [ordered]@{
    "esports_fade_bot"  = @("PolyBotEsports",  "watchdog_esports.lock")
    "sports_fade_bot"   = @("PolyBotSports",   "watchdog_sports.lock")
    "cs2_model_bot"     = @("CS2ModelBot",     "watchdog_cs2model.lock")
    "cs2_inplay_bot"    = @("CS2InplayBot",    "watchdog_cs2inplay.lock")
    "telegram_bot"      = @("PolyBotTelegram", "watchdog_telegram.lock")
    "main.py dashboard" = @("PolyDashboard",   "watchdog_dashboard.lock")
}
try {
    $cmds = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction Stop |
              ForEach-Object { $_.CommandLine })
} catch {
    Log "ERROR querying processes: $_"; exit 1
}

$revived = @()
foreach ($key in $map.Keys) {
    $n = @($cmds | Where-Object { $_ -and $_.Contains($key) }).Count
    if ($n -eq 0) {
        $task = $map[$key][0]; $lock = "$root\$($map[$key][1])"
        schtasks /end /tn $task 2>$null | Out-Null      # clear stuck "running" state
        Start-Sleep -Milliseconds 500
        if (Test-Path $lock) { Remove-Item $lock -Force -ErrorAction SilentlyContinue }
        schtasks /run /tn $task 2>$null | Out-Null
        $revived += $key
        Log "REVIVED $key via $task"
    }
}
# overwrite a heartbeat file so liveness is verifiable without bloating the log
"$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  checked 6 bots, revived $($revived.Count): $($revived -join ',')" |
    Out-File -Encoding utf8 "$root\health_guard_lastrun.txt"
exit 0
