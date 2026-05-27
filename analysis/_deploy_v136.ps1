# v1.36 deployment — restart sports bot in LIVE mode + schedule sports live eval.
# Esports bot, telegram, dashboard are left running.

$base = "C:\Users\matti\Desktop\prediction-market-analysis"

Write-Output "==== verify wallet separation ===="
$es = "$base\cowork_snapshot\esports\fade_targets.json"
$sp = "$base\cowork_snapshot\sports\fade_targets.json"
if (Test-Path $es) {
    $n = (Get-Content $es -Raw | ConvertFrom-Json).target_wallets.Count
    Write-Output "  Esports fade wallets: $n"
}
if (Test-Path $sp) {
    $n = (Get-Content $sp -Raw | ConvertFrom-Json).target_wallets.Count
    Write-Output "  Sports  fade wallets: $n"
}

Write-Output ""
Write-Output "==== schedule PolyBotSportsLiveEval ===="
schtasks /delete /tn "PolyBotSportsLiveEval" /f 2>$null | Out-Null
schtasks /create /tn "PolyBotSportsLiveEval" `
    /tr "$base\run_sports_eval_live.bat" `
    /sc minute /mo 10 `
    /ru "matti" /rl HIGHEST /f
schtasks /run /tn "PolyBotSportsLiveEval"

Write-Output ""
Write-Output "==== restart PolyBotSports in --live mode ===="
schtasks /end /tn PolyBotSports 2>$null
Start-Sleep -Seconds 3
# Selectively kill ONLY sports_fade_bot processes (not esports/telegram/dashboard)
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match "sports_fade_bot" } |
    ForEach-Object {
        Write-Output "  killing sports PID $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
Start-Sleep -Seconds 2
$lock = "$base\watchdog_sports.lock"
if (Test-Path $lock) { Remove-Item $lock -Force; Write-Output "  cleared watchdog_sports.lock" }
schtasks /run /tn PolyBotSports
Start-Sleep -Seconds 12

Write-Output ""
Write-Output "==== verify all python processes ===="
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Select-Object ProcessId, CommandLine | Format-List

Write-Output ""
Write-Output "==== sports bot startup log ===="
Get-Content "$base\watchdog_sports.log" -Tail 10
