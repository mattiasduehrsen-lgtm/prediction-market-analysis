# Truth-check: is the wallet refresh actually happening?
$f = 'C:\Users\matti\Desktop\prediction-market-analysis\cowork_snapshot\esports\fade_targets.json'
if (Test-Path $f) {
    $m = (Get-Item $f).LastWriteTime
    $days = ((Get-Date) - $m).TotalDays
    Write-Host "fade_targets.json"
    Write-Host "  last modified: $m"
    Write-Host "  age: $([math]::Round($days,1)) days"
} else {
    Write-Host "fade_targets.json: NOT FOUND"
}

Write-Host ""
Write-Host "--- All Poly* scheduled tasks ---"
schtasks /query /fo LIST | Select-String 'TaskName.*Poly' | ForEach-Object { $_.Line.Trim() }

Write-Host ""
Write-Host "--- Search for any task that runs identify_active_targets or refresh ---"
$tasks = schtasks /query /fo LIST /v 2>&1
$tasks -split "`r?`n" | Select-String 'identify_active|refresh.*target|fade_targets' | ForEach-Object { $_.Line.Trim() }
