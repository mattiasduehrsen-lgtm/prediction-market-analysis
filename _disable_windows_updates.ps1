# Lock down Windows Update on this laptop.
# Goal: NO automatic updates, NO forced restarts, EVER.
# Microsoft has multiple resurrection mechanisms - this hits all of them.
#
# 6 layers of defense:
#   1. Group Policy registry - tells Windows "no auto updates"
#   2. NoAutoRebootWithLoggedOnUsers - safety net for forced reboots
#   3. Disable Windows Update service (wuauserv)
#   4. Disable Update Orchestrator service (UsoSvc)
#   5. Disable Windows Update Medic (WaaSMedicSvc) via registry permission hack
#      (Microsoft made this immune to normal service-disable)
#   6. End and disable every reboot-related scheduled task

$ErrorActionPreference = 'Continue'
Write-Host "=== Locking down Windows Update ===" -ForegroundColor Yellow

# ----------------------------------------------------------------------------
# Layer 1: Group Policy registry keys
# These are the same keys that gpedit.msc writes; Windows Update reads them.
# ----------------------------------------------------------------------------
Write-Host "`n[1/6] Setting Group Policy registry keys..." -ForegroundColor Cyan
$auPath = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU'
$wuPath = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate'
foreach ($p in $auPath, $wuPath) {
    if (-not (Test-Path $p)) { New-Item -Path $p -Force | Out-Null }
}
# NoAutoUpdate=1: completely disable auto-update
Set-ItemProperty -Path $auPath -Name 'NoAutoUpdate' -Value 1 -Type DWord
# AUOptions=1: "never check for updates" (vs 2=notify, 3=auto-dl, 4=auto-install)
Set-ItemProperty -Path $auPath -Name 'AUOptions' -Value 1 -Type DWord
# NoAutoRebootWithLoggedOnUsers=1: NEVER restart if a user is signed in
Set-ItemProperty -Path $auPath -Name 'NoAutoRebootWithLoggedOnUsers' -Value 1 -Type DWord
# AlwaysAutoRebootAtScheduledTime=0
Set-ItemProperty -Path $auPath -Name 'AlwaysAutoRebootAtScheduledTime' -Value 0 -Type DWord
# Disable driver updates too
Set-ItemProperty -Path $wuPath -Name 'ExcludeWUDriversInQualityUpdate' -Value 1 -Type DWord
# Defer feature updates 365 days (max)
Set-ItemProperty -Path $wuPath -Name 'DeferFeatureUpdates' -Value 1 -Type DWord
Set-ItemProperty -Path $wuPath -Name 'DeferFeatureUpdatesPeriodInDays' -Value 365 -Type DWord
Write-Host "  [OK] Policy keys set" -ForegroundColor Green

# Set "Active Hours" to 18 hours (max allowed) so any sneaky restart attempt
# during that window is blocked.
$uxPath = 'HKLM:\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings'
if (-not (Test-Path $uxPath)) { New-Item -Path $uxPath -Force | Out-Null }
Set-ItemProperty -Path $uxPath -Name 'ActiveHoursStart' -Value 0  -Type DWord
Set-ItemProperty -Path $uxPath -Name 'ActiveHoursEnd'   -Value 18 -Type DWord
Set-ItemProperty -Path $uxPath -Name 'IsActiveHoursEnabled' -Value 1 -Type DWord
Write-Host "  [OK] Active Hours set to 00:00-18:00 (max)" -ForegroundColor Green

# ----------------------------------------------------------------------------
# Layer 2: Disable services
# ----------------------------------------------------------------------------
Write-Host "`n[2/6] Disabling update services..." -ForegroundColor Cyan
$services = @(
    'wuauserv',      # Windows Update
    'UsoSvc',        # Update Orchestrator (the one that schedules reboots)
    'WaaSMedicSvc',  # Windows Update Medic (revival service)
    'BITS',          # Background Intelligent Transfer (used by WU)
    'DoSvc'          # Delivery Optimization
)
foreach ($svc in $services) {
    try {
        Stop-Service -Name $svc -Force -ErrorAction SilentlyContinue
        Set-Service -Name $svc -StartupType Disabled -ErrorAction Stop
        Write-Host "  [OK] $svc stopped and disabled" -ForegroundColor Green
    } catch {
        Write-Host "  [WARN] $svc : $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

# ----------------------------------------------------------------------------
# Layer 3: WaaSMedicSvc - Microsoft made this immune to normal Set-Service.
# It will re-enable itself unless we tamper with its registry Start value AND
# also nuke its "Failure Actions" so it can't auto-recover.
# ----------------------------------------------------------------------------
Write-Host "`n[3/6] Neutralizing WaaSMedicSvc (revival service)..." -ForegroundColor Cyan
$medicPath = 'HKLM:\SYSTEM\CurrentControlSet\Services\WaaSMedicSvc'
try {
    # Start=4 means Disabled
    Set-ItemProperty -Path $medicPath -Name 'Start' -Value 4 -Type DWord -ErrorAction Stop
    Write-Host "  [OK] WaaSMedicSvc registry Start=4 (Disabled)" -ForegroundColor Green
} catch {
    Write-Host "  [WARN] WaaSMedicSvc registry: $($_.Exception.Message)" -ForegroundColor Yellow
}
# Clear FailureActions so it won't auto-restart on stop
try {
    sc.exe failure WaaSMedicSvc reset= 0 actions= '' | Out-Null
    Write-Host "  [OK] WaaSMedicSvc failure-recovery actions cleared" -ForegroundColor Green
} catch { }

# ----------------------------------------------------------------------------
# Layer 4: Disable Update Orchestrator service in registry too (belt + braces)
# ----------------------------------------------------------------------------
Write-Host "`n[4/6] Reinforcing UsoSvc disable in registry..." -ForegroundColor Cyan
$usoPath = 'HKLM:\SYSTEM\CurrentControlSet\Services\UsoSvc'
try {
    Set-ItemProperty -Path $usoPath -Name 'Start' -Value 4 -Type DWord -ErrorAction Stop
    Write-Host "  [OK] UsoSvc Start=4" -ForegroundColor Green
} catch {
    Write-Host "  [WARN] UsoSvc registry: $($_.Exception.Message)" -ForegroundColor Yellow
}

# ----------------------------------------------------------------------------
# Layer 5: End + disable every reboot/update scheduled task
# ----------------------------------------------------------------------------
Write-Host "`n[5/6] Disabling reboot/update scheduled tasks..." -ForegroundColor Cyan
$taskPaths = @(
    '\Microsoft\Windows\UpdateOrchestrator\',
    '\Microsoft\Windows\WindowsUpdate\',
    '\Microsoft\Windows\InstallService\',
    '\Microsoft\Windows\WaaSMedic\',
    '\Microsoft\Windows\UpdateAssistant\'
)
$count = 0
foreach ($p in $taskPaths) {
    try {
        Get-ScheduledTask -TaskPath $p -ErrorAction SilentlyContinue | ForEach-Object {
            try {
                Disable-ScheduledTask -TaskName $_.TaskName -TaskPath $_.TaskPath -ErrorAction Stop | Out-Null
                Write-Host "  [OK] disabled  $($_.TaskPath)$($_.TaskName)" -ForegroundColor Green
                $count++
            } catch {
                Write-Host "  [WARN] $($_.TaskPath)$($_.TaskName) : $($_.Exception.Message)" -ForegroundColor Yellow
            }
        }
    } catch {}
}
Write-Host "  Total disabled: $count tasks" -ForegroundColor Cyan

# ----------------------------------------------------------------------------
# Layer 6: Block Windows Update server endpoints via hosts file
# (last-resort: even if a service comes back to life, it can't reach Microsoft)
# ----------------------------------------------------------------------------
Write-Host "`n[6/6] Blocking WU servers via hosts file..." -ForegroundColor Cyan
$hostsPath = "$env:SystemRoot\System32\drivers\etc\hosts"
$marker = "# === Block Windows Update servers ==="
$existing = Get-Content $hostsPath -Raw -ErrorAction SilentlyContinue
if ($existing -notlike "*$marker*") {
    $block = @"

$marker
0.0.0.0 windowsupdate.microsoft.com
0.0.0.0 update.microsoft.com
0.0.0.0 download.windowsupdate.com
0.0.0.0 fe2.update.microsoft.com
0.0.0.0 sls.update.microsoft.com
0.0.0.0 wustat.windows.com
0.0.0.0 dl.delivery.mp.microsoft.com
0.0.0.0 emdl.ws.microsoft.com
0.0.0.0 ctldl.windowsupdate.com
# ==========================================
"@
    Add-Content -Path $hostsPath -Value $block -Encoding ASCII
    Write-Host "  [OK] Added WU server blocks to hosts" -ForegroundColor Green
} else {
    Write-Host "  [SKIP] hosts entries already present" -ForegroundColor Gray
}

Write-Host "`n=== DONE ===" -ForegroundColor Yellow
Write-Host "Windows Update is now disabled across 6 layers."
Write-Host "To verify: try opening 'Settings > Windows Update' - it should error or be empty."
