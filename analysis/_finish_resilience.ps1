# Close the last two resilience gaps, with read-back verification.
#  (1) lid-close action -> Do Nothing (0) on AC and DC
#  (2) PolyDashboard -> add an AtStartup trigger so it survives an unattended reboot
#      (keep its existing Logon trigger too)
# Run on the laptop as admin/SYSTEM. Idempotent.
$ErrorActionPreference = "Stop"
$SUB_BTN  = "4f971e89-eebd-4455-a8de-9e59040e7347"
$LIDACT   = "5ca83367-6e45-459f-a27b-476b1d01c936"

Write-Output "=== (1) lid-close = Do Nothing ==="
powercfg /setacvalueindex SCHEME_CURRENT $SUB_BTN $LIDACT 0
powercfg /setdcvalueindex SCHEME_CURRENT $SUB_BTN $LIDACT 0
powercfg /setactive SCHEME_CURRENT
# read back the whole buttons subgroup so we SEE the lid line regardless of format
$q = powercfg /query SCHEME_CURRENT $SUB_BTN $LIDACT
$ac = ($q | Select-String "Current AC")
$dc = ($q | Select-String "Current DC")
Write-Output ("  lid AC: " + ($(if($ac){$ac.ToString().Trim()}else{"<<< NOT PRESENT (no lid setting on this scheme)"})))
Write-Output ("  lid DC: " + ($(if($dc){$dc.ToString().Trim()}else{"<<< NOT PRESENT"})))

Write-Output "=== (2) PolyDashboard AtStartup trigger ==="
$t = Get-ScheduledTask -TaskName "PolyDashboard"
$kinds = $t.Triggers | ForEach-Object { $_.CimClass.CimClassName }
if ($kinds -match "BootTrigger") {
    Write-Output "  already has a Boot trigger - no change"
} else {
    $newTriggers = @($t.Triggers) + (New-ScheduledTaskTrigger -AtStartup)
    Set-ScheduledTask -TaskName "PolyDashboard" -Trigger $newTriggers | Out-Null
    Write-Output "  added AtStartup trigger"
}
$after = (Get-ScheduledTask -TaskName "PolyDashboard").Triggers |
         ForEach-Object { $_.CimClass.CimClassName -replace 'MSFT_Task','' -replace 'Trigger','' }
Write-Output ("  PolyDashboard triggers now: " + ($after -join ","))
Write-Output "DONE"
