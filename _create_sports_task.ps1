# Create PolyBotSports scheduled task — logon-proof from the start.
schtasks /create /tn PolyBotSports `
    /tr "C:\Users\matti\Desktop\prediction-market-analysis\watch_sports_fade.bat" `
    /sc onstart `
    /ru "MSI\matti" /rp "Tiasdue123." `
    /rl HIGHEST /f

Write-Host ""
Write-Host "--- Starting now ---"
Remove-Item "C:\Users\matti\Desktop\prediction-market-analysis\watchdog_sports.lock" -Force -ErrorAction SilentlyContinue
schtasks /run /tn PolyBotSports

Write-Host ""
Write-Host "--- Verification (after 8s) ---"
Start-Sleep -Seconds 8
schtasks /query /tn PolyBotSports /v /fo LIST | Select-String 'Status|Logon Mode|Next Run|Last Run|Last Result'
