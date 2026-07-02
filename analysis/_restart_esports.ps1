# Clean-restart the trading bots. TARGETED kills only (2026-07-01 fix): the old
# `Stop-Process -Name python` killed EVERY python on the box — twice it murdered
# unrelated one-shot jobs (the dota2/valorant PandaScore backfills died mid-download;
# price_capture only survived via its watchdog). Now we /end the tasks, then kill
# ONLY pythons whose CommandLine matches the bots this script manages. One-shot
# analysis/download jobs and price_capture are never touched.
$botPat  = "esports_fade_bot|telegram_bot|main\.py dashboard|sports_fade_bot|cs2_model_bot|cs2_inplay_bot"
$watchPat = "watch_(esports_fade|telegram_bot|dashboard|sports_fade|cs2_model|cs2_inplay)"

schtasks /end /tn PolyBotEsports 2>$null
schtasks /end /tn PolyBotTelegram 2>$null
schtasks /end /tn PolyDashboard 2>$null
schtasks /end /tn PolyBotSports 2>$null
Start-Sleep -Seconds 3
# Targeted kill: bot pythons AND their watchdog cmd.exe wrappers (watch_*.bat), so
# an orphaned watchdog can't respawn a duplicate instance.
Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -and (
        ($_.Name -eq "python.exe" -and $_.CommandLine -match $botPat) -or
        ($_.Name -eq "cmd.exe"    -and $_.CommandLine -match $watchPat)
    ) } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2
foreach ($name in "watchdog_esports.lock","watchdog_telegram.lock","watchdog_dashboard.lock","watchdog_sports.lock") {
    $lock = "C:\Users\matti\Desktop\prediction-market-analysis\$name"
    if (Test-Path $lock) { Remove-Item $lock -Force }
}
schtasks /run /tn PolyBotEsports
schtasks /run /tn PolyBotTelegram
schtasks /run /tn PolyDashboard
schtasks /run /tn PolyBotSports
Start-Sleep -Seconds 12
Write-Output "---- python processes ----"
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Select-Object ProcessId, CommandLine |
    Format-List
Write-Output "---- last 8 lines of bot log ----"
Get-Content "C:\Users\matti\Desktop\prediction-market-analysis\watchdog_esports.log" -Tail 8
