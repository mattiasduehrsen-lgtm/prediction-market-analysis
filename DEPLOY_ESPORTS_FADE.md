# Deploying the Esports Fade Bot to the Laptop

**Read first:** this is a NEW scheduled task. It does **not** touch the existing
`PolyBot` / `PolyBotPaper` / `PolyDashboard` tasks. The fade bot has its own
process, logs, and output directory.

Mode at deploy: **PAPER** (no real orders). LIVE is enabled separately by
flipping the command in `watch_esports_fade.bat` to add `--live`.

## Prereq

- Code pushed to git (this dev PC) and pulled on laptop:
  ```
  ssh matti@192.168.2.212 "cd C:\Users\matti\Desktop\prediction-market-analysis && git pull"
  ```
- `cowork_snapshot/esports/fade_targets.json` must exist on the laptop. Either
  pull it from git (it's a small JSON) or regenerate via:
  ```
  .venv\Scripts\python.exe analysis\identify_active_targets.py
  ```
  Note: identify_active_targets needs the shards parquet which is multi-GB —
  easier to just transfer fade_targets.json itself.

## Create the scheduled task (one-time)

Over SSH on the laptop:

```powershell
schtasks /create /tn PolyBotEsports `
  /tr "C:\Users\matti\Desktop\prediction-market-analysis\watch_esports_fade.bat" `
  /sc onstart `
  /ru matti `
  /rl HIGHEST `
  /f
```

Then start it immediately:

```powershell
schtasks /run /tn PolyBotEsports
```

Verify it's alive:

```powershell
Start-Sleep -Seconds 10
wmic process where name='python.exe' get ProcessId,CommandLine /format:list | findstr esports_fade
Get-Content "C:\Users\matti\Desktop\prediction-market-analysis\output\esports_fade\bot.log" -Tail 20
```

## Stop the task

```powershell
schtasks /end /tn PolyBotEsports
Remove-Item "C:\Users\matti\Desktop\prediction-market-analysis\watchdog_esports.lock" -ErrorAction SilentlyContinue
```

## Going LIVE

After PAPER has validated for ≥1 week with ≥200 resolved signals and ROI in
the +50% to +150% range (i.e. consistent with the +110% backtest):

1. Edit `watch_esports_fade.bat`, change the python line to:
   ```
   .venv\Scripts\python.exe -u esports_fade_bot.py --live >> watchdog_esports.log 2>&1
   ```
2. Verify `.env` has on the laptop:
   - `POLYMARKET_PRIVATE_KEY=...`
   - `POLYMARKET_API_KEY=...`, `_SECRET=...`, `_PASSPHRASE=...`
   - `POLYMARKET_PROXY_ADDRESS=...`
   - `POLYMARKET_SIGNATURE_TYPE=2`
3. Verify the funding wallet has the expected USDC balance.
4. `schtasks /end /tn PolyBotEsports` then `schtasks /run /tn PolyBotEsports`.
5. Watch `output\esports_fade\bot.log` for `LIVE order posted: ...` lines.
6. If anything looks wrong: revert step 1 (remove `--live`) and restart.

## Independence from the 15m bot

This task is **fully separate**. It:
- Does not read or write the 15m bot's files
- Does not share a process or thread with PolyBot / PolyBotPaper
- Does not use `paused.live.flag` — it has no pause flag (yet)
- Writes only to `output\esports_fade\` and `watchdog_esports.log`

Restarting / stopping `PolyBotEsports` has **zero effect** on the 15m bot.
