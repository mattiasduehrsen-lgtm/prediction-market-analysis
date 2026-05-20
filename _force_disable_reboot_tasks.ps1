# Force-disable the TrustedInstaller-protected reboot tasks by taking
# ownership of their underlying XML files in C:\Windows\System32\Tasks first.

$ErrorActionPreference = 'Continue'
$base = 'C:\Windows\System32\Tasks\Microsoft\Windows\UpdateOrchestrator'

$dangerous = @(
    'Reboot_AC',
    'Reboot_Battery',
    'Reboot',
    'USO_UxBroker',
    'UpdateModelTask',
    'Schedule Scan',
    'Schedule Scan Static Task',
    'Start Oobe Expedite Work',
    'StartOobeAppsScan',
    'StartOobeAppsScan_LicenseAccepted',
    'StartOobeAppsScanAfterUpdate',
    'UUS Failover Task',
    'Report policies',
    'UIEOrchestrator'
)

foreach ($name in $dangerous) {
    $path = Join-Path $base $name
    if (-not (Test-Path $path)) {
        Write-Host "  [SKIP] $name not found"
        continue
    }
    Write-Host "Taking ownership of $name..." -ForegroundColor Cyan
    takeown /f $path /a 2>&1 | Out-Null
    icacls $path /grant Administrators:F 2>&1 | Out-Null
    try {
        Disable-ScheduledTask -TaskPath '\Microsoft\Windows\UpdateOrchestrator\' -TaskName $name -ErrorAction Stop | Out-Null
        Write-Host "  [OK] $name disabled" -ForegroundColor Green
    } catch {
        # Fallback: nuke the task by deleting its XML file
        try {
            Remove-Item $path -Force -ErrorAction Stop
            Write-Host "  [OK] $name file deleted (couldn't disable via API)" -ForegroundColor Yellow
        } catch {
            Write-Host "  [FAIL] $name : $($_.Exception.Message)" -ForegroundColor Red
        }
    }
}

Write-Host ""
Write-Host "--- Final state of UpdateOrchestrator tasks ---" -ForegroundColor Yellow
Get-ScheduledTask -TaskPath '\Microsoft\Windows\UpdateOrchestrator\' -ErrorAction SilentlyContinue |
    Select-Object TaskName, State | Format-Table -AutoSize

Write-Host ""
Write-Host "--- Service status ---" -ForegroundColor Yellow
foreach ($s in 'wuauserv','UsoSvc','WaaSMedicSvc','BITS') {
    $svc = Get-Service -Name $s -ErrorAction SilentlyContinue
    if ($svc) {
        Write-Host ("  {0,-15} {1,-10} (startup: {2})" -f $svc.Name, $svc.Status, $svc.StartType)
    }
}
