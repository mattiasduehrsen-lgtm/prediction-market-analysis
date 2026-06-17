# Close the last resilience gap: lid-close action -> Do Nothing.
# On this machine the lid setting is HIDDEN by attribute, so /query showed nothing
# and /setacvalueindex had nowhere to land. Reveal it first, then set + read back.
# Dashboard-on-unattended-reboot is NOT handled here: the health guard already
# force-starts PolyDashboard via `schtasks /run` within 5 min if it is down, which
# works regardless of the Logon trigger -- no need to risk editing a working task.
# Run on the laptop as admin/SYSTEM. Idempotent.
$SUB_BTN  = "4f971e89-eebd-4455-a8de-9e59040e7347"
$LIDACT   = "5ca83367-6e45-459f-a27b-476b1d01c936"

Write-Output "=== reveal hidden lid setting, then set Do Nothing (0) ==="
powercfg /attributes $SUB_BTN $LIDACT -ATTRIB_HIDE 2>$null   # un-hide
powercfg /setacvalueindex SCHEME_CURRENT $SUB_BTN $LIDACT 0
powercfg /setdcvalueindex SCHEME_CURRENT $SUB_BTN $LIDACT 0
powercfg /setactive SCHEME_CURRENT

$q  = powercfg /query SCHEME_CURRENT $SUB_BTN $LIDACT
$ac = ($q | Select-String "Current AC")
$dc = ($q | Select-String "Current DC")
Write-Output ("  lid AC: " + $(if($ac){$ac.ToString().Trim()}else{"still not present (system has no lid action setting)"}))
Write-Output ("  lid DC: " + $(if($dc){$dc.ToString().Trim()}else{"still not present"}))
Write-Output "DONE"
