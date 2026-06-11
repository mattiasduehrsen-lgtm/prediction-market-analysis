# Health guard: revive any dead bot. Runs every 5 min as SYSTEM (regardless of
# logon). Fixes the root cause of the 2026-06-08 outage: onstart-only tasks don't
# recover a bot that dies WITHOUT a reboot (sleep/crash/logoff) -> days of silence.
$root = "C:\Users\matti\Desktop\prediction-market-analysis"
Set-Location $root
# bot command-line substring -> (scheduled task name, lock file)
$map = [ordered]@{
    "esports_fade_bot"  = @("PolyBotEsports",  "watchdog_esports.lock")
    "sports_fade_bot"   = @("PolyBotSports",   "watchdog_sports.lock")
    "cs2_model_bot"     = @("CS2ModelBot",     "watchdog_cs2model.lock")
    "cs2_inplay_bot"    = @("CS2InplayBot",    "watchdog_cs2inplay.lock")
    "telegram_bot"      = @("PolyBotTelegram", "watchdog_telegram.lock")
    "main.py dashboard" = @("PolyDashboard",   "watchdog_dashboard.lock")
}
$cmds = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | ForEach-Object { $_.CommandLine }
foreach ($key in $map.Keys) {
    $n = @($cmds | Where-Object { $_ -like "*$key*" }).Count
    if ($n -eq 0) {
        $task = $map[$key][0]; $lock = $map[$key][1]
        if (Test-Path $lock) { Remove-Item $lock -Force -ErrorAction SilentlyContinue }
        schtasks /run /tn $task | Out-Null
        "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  REVIVED $key via $task" |
            Out-File -Append -Encoding utf8 "$root\health_guard.log"
    }
}
exit 0
