# Bot Commands Reference

## SSH into Laptop
```
ssh matti@<LAPTOP_IP>
```
Password: stored locally — do not commit.

---

## Dashboard URL
```
http://<LAPTOP_IP>:5000
```
- Summary: http://<LAPTOP_IP>:5000/api/summary
- Positions: http://<LAPTOP_IP>:5000/api/positions
- Closed Trades: http://<LAPTOP_IP>:5000/api/closed_trades
- Signals: http://<LAPTOP_IP>:5000/api/signals
- Debug: http://<LAPTOP_IP>:5000/api/debug

---

## Start Bot manually (from laptop SSH/PowerShell)
```powershell
schtasks /run /tn PolyBot
```

## Stop Bot (from laptop SSH/PowerShell)
```powershell
Stop-Process -Name python -Force
```

## Restart Bot (from laptop SSH/PowerShell)
```powershell
Stop-Process -Name python -Force
schtasks /run /tn PolyBot
```

---

## Start Dashboard manually (from laptop SSH/PowerShell)
```powershell
schtasks /run /tn PolyDashboard
```

---

## Auto-start on reboot (run once from elevated PowerShell — right-click PowerShell > Run as Administrator)
```powershell
$a = New-ScheduledTaskAction -Execute "C:\Users\matti\Desktop\prediction-market-analysis\.venv\Scripts\python.exe" -Argument "-u main.py paper-loop" -WorkingDirectory "C:\Users\matti\Desktop\prediction-market-analysis"
$t = New-ScheduledTaskTrigger -AtLogOn
$s = New-ScheduledTaskSettingsSet -ExecutionTimeLimit 0
Register-ScheduledTask -TaskName "PolyBot" -Action $a -Trigger $t -Settings $s -RunLevel Highest -Force
```

## If something isn't running after reboot
```powershell
Stop-Process -Name python -Force
schtasks /run /tn PolyBot
schtasks /run /tn PolyDashboard
```

---

## Pull Latest Code (from laptop PowerShell)
```powershell
cd "C:\Users\matti\Desktop\prediction-market-analysis"
git pull
```

## Check Bot Log (from laptop PowerShell)
```powershell
Get-Content "C:\Users\matti\Desktop\prediction-market-analysis\bot.log" -Tail 50
```

## Check Bot Errors (from laptop PowerShell)
```powershell
Get-Content "C:\Users\matti\Desktop\prediction-market-analysis\bot_err.log" -Tail 20
```

## Check Bot Status (from laptop PowerShell)
```powershell
Get-Content "C:\Users\matti\Desktop\prediction-market-analysis\output\paper_trading\polymarket\summary.json"
```

---

## Edit .env on Laptop
View:
```powershell
Get-Content "C:\Users\matti\Desktop\prediction-market-analysis\.env"
```
Change a value:
```powershell
(Get-Content "C:\Users\matti\Desktop\prediction-market-analysis\.env") -replace 'OLD_VALUE', 'NEW_VALUE' | Set-Content "C:\Users\matti\Desktop\prediction-market-analysis\.env"
```
