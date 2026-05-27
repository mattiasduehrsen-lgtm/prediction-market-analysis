# Schedule the sports LIVE evaluator (every 10 min). Idempotent.
$base = "C:\Users\matti\Desktop\prediction-market-analysis"

schtasks /delete /tn "PolyBotSportsLiveEval" /f 2>$null | Out-Null
schtasks /create /tn "PolyBotSportsLiveEval" `
    /tr "$base\run_sports_eval_live.bat" `
    /sc minute /mo 10 `
    /ru "matti" /rl HIGHEST /f

# Run once immediately so live_daily_pnl.json has a fresh snapshot for the bot
schtasks /run /tn "PolyBotSportsLiveEval"

Write-Output "---- scheduled ----"
schtasks /query /tn "PolyBotSportsLiveEval" /fo LIST | Select-Object -First 6
