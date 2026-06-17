# Power hardening for the 24/7 trading laptop.
# ROOT CAUSE of the recurring "laptop locked, bot not running" outages:
# the AC hibernate timeout was 15 min (HIBERNATEIDLE AC=0x384). Lock the
# screen + walk away -> 15 min later the machine HIBERNATES (full power-off
# to disk) -> every process dies AND no scheduled task runs (not even the
# health guard) until someone physically wakes it. The guard can't revive
# anything because the guard is powered off too.
#
# This makes the laptop NEVER sleep/hibernate on idle, ignore the lid, and
# lets the health guard wake the box as a last-resort backstop.
# Idempotent — safe to re-run any time. Requires admin (run as SYSTEM/elevated).

$ErrorActionPreference = "Stop"
Write-Output "=== power hardening ==="

# 1) Never sleep / never hibernate on idle, AC and battery.
powercfg /change standby-timeout-ac 0
powercfg /change standby-timeout-dc 0
powercfg /change hibernate-timeout-ac 0
powercfg /change hibernate-timeout-dc 0

# 2) Disable hibernation entirely (also kills Fast Startup, which is fine for 24/7).
powercfg /hibernate off

# 3) Lid close = Do Nothing (0), AC and battery.
$SUB_BUTTONS = "4f971e89-eebd-4455-a8de-9e59040e7347"
$LIDACTION   = "5ca83367-6e45-459f-a27b-476b1d01c936"
powercfg /setacvalueindex SCHEME_CURRENT $SUB_BUTTONS $LIDACTION 0
powercfg /setdcvalueindex SCHEME_CURRENT $SUB_BUTTONS $LIDACTION 0

# 4) Allow wake timers (so a scheduled task CAN wake the box if it ever sleeps).
$SUB_SLEEP  = "238c9fa8-0aad-41ed-83f4-97be242c8f20"
$ALLOWWAKE  = "bd3b718a-0680-4d9d-8ab2-e1d2b4ac806d"
powercfg /setacvalueindex SCHEME_CURRENT $SUB_SLEEP $ALLOWWAKE 1
powercfg /setdcvalueindex SCHEME_CURRENT $SUB_SLEEP $ALLOWWAKE 1
powercfg /setactive SCHEME_CURRENT

# 5) Health guard backstop: let it WAKE the machine when its 5-min trigger fires.
try {
    $s = (Get-ScheduledTask -TaskName "PolyBotHealthGuard").Settings
    $s.WakeToRun = $true
    Set-ScheduledTask -TaskName "PolyBotHealthGuard" -Settings $s | Out-Null
    Write-Output "guard WakeToRun = $((Get-ScheduledTask -TaskName 'PolyBotHealthGuard').Settings.WakeToRun)"
} catch { Write-Output "guard WakeToRun FAILED: $_" }

# ---- verification ----
Write-Output "=== verify ==="
function Idx($alias,$setting){
    $o = powercfg /query SCHEME_CURRENT $alias $setting
    ($o | Select-String "Current AC Power Setting Index").ToString().Trim()
}
powercfg /a | Select-String "Hibernation"
Write-Output ("hibernate-after: " + (Idx $SUB_SLEEP "29f6c1db-86da-48c5-9fdb-f2b67b1f44da"))  # sleep-after (sanity)
Write-Output "DONE"
