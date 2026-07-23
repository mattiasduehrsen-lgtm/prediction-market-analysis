# Health guard: revive DEAD bots AND restart HUNG bots (process alive but frozen).
# Runs every 5 min as SYSTEM. Root-cause fixes for the June 2026 outages:
#  - onstart-only tasks don't recover a bot that dies without a reboot
#  - a stuck "running" task makes plain `schtasks /run` a no-op -> use /end then /run
#  - a process can HANG (alive but not heartbeating) -> detect via stale log, kill, restart
$root = "C:\Users\matti\Desktop\prediction-market-analysis"
Set-Location $root
$now = Get-Date
$log = "$root\health_guard.log"
function Log($m) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $m" | Out-File -Append -Encoding utf8 $log }

# key = command-line substring -> (task, lockfile, heartbeat-log or '', stale-minutes)
# heartbeat-log '' = event-driven bot (telegram/dashboard): only check it's alive, not fresh.
$map = [ordered]@{
    "esports_fade_bot"  = @("PolyBotEsports",  "watchdog_esports.lock",  "watchdog_esports.log",  30)
    "sports_fade_bot"   = @("PolyBotSports",   "watchdog_sports.lock",   "watchdog_sports.log",   45)
    "cs2_model_bot"     = @("CS2ModelBot",     "watchdog_cs2model.lock", "watchdog_cs2model.log", 30)
    "cs2_inplay_bot"    = @("CS2InplayBot",    "watchdog_cs2inplay.lock","watchdog_cs2inplay.log",30)
    "telegram_bot"      = @("PolyBotTelegram", "watchdog_telegram.lock", "", 0)
    "main.py dashboard" = @("PolyDashboard",   "watchdog_dashboard.lock","", 0)
    "price_capture"     = @("PriceCapture",    "watchdog_pricecap.lock", "watchdog_pricecap.log", 30)
    # capture loops added 2026-07-23 after twice being found dead from stray
    # console interrupts (^C in their logs, source unidentified) with nothing
    # reviving them. news_capture prints only on rosterish hits -> alive-check
    # only (no staleness), like telegram/dashboard.
    "updown_book_capture" = @("UpdownCapture", "watchdog_updowncap.lock", "watchdog_updowncap.log", 20)
    "odds_capture"        = @("OddsCapture",   "watchdog_oddscap.lock",   "watchdog_oddscap.log",   20)
    "news_capture"        = @("NewsCapture",   "watchdog_newscap.lock",   "", 0)
}
try {
    $procs = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction Stop)
} catch { Log "ERROR querying processes: $_"; exit 1 }
$cmds = $procs | ForEach-Object { $_.CommandLine }
# IMPORTANT: 'sports_fade_bot' is a substring of 'esports_fade_bot', so a plain
# Contains() would count esports's procs as sports' -> a dead sports bot would be
# masked by a live esports bot and never revived. Require no letter before the key.
function Matches-Bot($cmd, $key) { return $cmd -match ("(?<![A-Za-z])" + [regex]::Escape($key)) }

$acted = @()
foreach ($key in $map.Keys) {
    $task = $map[$key][0]; $lock = "$root\$($map[$key][1])"
    $hblog = $map[$key][2]; $staleMin = $map[$key][3]
    $n = @($cmds | Where-Object { $_ -and (Matches-Bot $_ $key) }).Count

    $reason = $null
    if ($n -eq 0) {
        $reason = "DEAD"
    } elseif ($hblog -ne "" -and (Test-Path "$root\$hblog")) {
        $age = ($now - (Get-Item "$root\$hblog").LastWriteTime).TotalMinutes
        if ($age -gt $staleMin) { $reason = "HUNG (log ${age:N0}m stale)" }
    }
    if ($reason) {
        # kill this bot's python (handles the HUNG-but-alive case) so restart isn't a dup
        $procs | Where-Object { $_.CommandLine -and (Matches-Bot $_.CommandLine $key) } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        schtasks /end /tn $task 2>$null | Out-Null      # clear stuck "running" state
        Start-Sleep -Milliseconds 800
        if (Test-Path $lock) { Remove-Item $lock -Force -ErrorAction SilentlyContinue }
        schtasks /run /tn $task 2>$null | Out-Null
        $acted += "$key($reason)"
        Log "RESTARTED $key [$reason] via $task"
    }
}
"$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  checked $($map.Keys.Count) bots, acted $($acted.Count): $($acted -join ', ')" |
    Out-File -Encoding utf8 "$root\health_guard_lastrun.txt"
exit 0
