# Bot Commands Reference

## SSH into Laptop (from PC)
```
ssh matti@100.84.44.122
```
Password: your Microsoft account password

---

## Start Dashboard (from SSH - survives disconnect)
```
cd C:\Users\matti\Desktop\prediction-market-analysis
schtasks /run /tn "PolyDashboard"
```
Then open http://100.84.44.122:5000 in browser and press Start Bot.

---

## Stop All Python Processes on Laptop (from SSH)
```
taskkill /F /IM python.exe
```

---

## Restart Dashboard After Stopping (from SSH)
```
schtasks /run /tn "PolyDashboard"
```

---

## Pull Latest Code on Laptop (from SSH)
```
cd C:\Users\matti\Desktop\prediction-market-analysis
git pull
```

---

## Push Code Changes from PC
```
cd "c:/Users/home user/Desktop/prediction-market-analysis"
git add -A
git commit -m "describe your change"
git push
```

---

## Check Bot Status (from SSH)
```
type C:\Users\matti\Desktop\prediction-market-analysis\output\paper_trading\polymarket\summary.json
```

---

## Check Bot Log (from SSH)
```
type C:\Users\matti\Desktop\prediction-market-analysis\bot.log
```

---

## Edit .env on Laptop (from SSH)
```
powershell -Command "Get-Content C:\Users\matti\Desktop\prediction-market-analysis\.env"
```
To change a value:
```
powershell -Command "(Get-Content C:\Users\matti\Desktop\prediction-market-analysis\.env) -replace 'OLD_VALUE', 'NEW_VALUE' | Set-Content C:\Users\matti\Desktop\prediction-market-analysis\.env"
```

---

## Dashboard URLs
- Dashboard: http://100.84.44.122:5000
- Summary: http://100.84.44.122:5000/api/summary
- Positions: http://100.84.44.122:5000/api/positions
- Closed Trades: http://100.84.44.122:5000/api/closed_trades
- Signals: http://100.84.44.122:5000/api/signals
- Debug: http://100.84.44.122:5000/api/debug

---

## After Windows Restart (laptop)
1. SSH in: `ssh matti@100.84.44.122`
2. Start dashboard: `schtasks /run /tn "PolyDashboard"`
3. Open http://100.84.44.122:5000 and press Start Bot
