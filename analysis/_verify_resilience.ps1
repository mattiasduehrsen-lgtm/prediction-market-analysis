# Verify the laptop will keep the bots running through idle, lid-close, and reboot.
# Read-only. Run on the laptop. Pairs with analysis\_harden_power.ps1.
$ErrorActionPreference = "SilentlyContinue"
Set-Location "C:\Users\matti\Desktop\prediction-market-analysis"

Write-Output "===== POWER ====="
$SUB_SLEEP="238c9fa8-0aad-41ed-83f4-97be242c8f20"
$SUB_BTN="4f971e89-eebd-4455-a8de-9e59040e7347"
function CurAC($sub,$set){ (powercfg /query SCHEME_CURRENT $sub $set | Select-String "Current AC").ToString().Trim() }
Write-Output ("sleep-after     " + (CurAC $SUB_SLEEP "29f6c1db-86da-48c5-9fdb-f2b67b1f44da"))
Write-Output ("hibernate-after " + (CurAC $SUB_SLEEP "9d7815a6-7ee4-497e-8888-515a05f02364"))
Write-Output ("lid-close       " + (CurAC $SUB_BTN  "5ca83367-6e45-459f-a27b-476b1d01c936"))
powercfg /a | Select-String "Hibernation is not available|Hibernation has not"

Write-Output "`n===== TASKS (runAs / state / triggers — AtStartup = survives reboot) ====="
$tasks = "PolyBotEsports","PolyBotSports","CS2ModelBot","CS2InplayBot","PolyBotTelegram","PolyDashboard","PolyBotHealthGuard"
foreach($t in $tasks){
    $k = Get-ScheduledTask -TaskName $t
    if(-not $k){ Write-Output ("{0,-20} MISSING" -f $t); continue }
    $tr = ($k.Triggers | ForEach-Object { $_.CimClass.CimClassName -replace 'MSFT_Task','' -replace 'Trigger','' }) -join ","
    $wake = $k.Settings.WakeToRun
    Write-Output ("{0,-20} runAs={1,-7} state={2,-7} wake={3,-5} triggers={4}" -f $t,$k.Principal.UserId,$k.State,$wake,$tr)
}

Write-Output "`n===== GUARD LAST RUN ====="
if(Test-Path "health_guard_lastrun.txt"){ Get-Content "health_guard_lastrun.txt" }

Write-Output "`n===== BOTS ALIVE NOW ====="
$cmds = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | ForEach-Object { $_.CommandLine }
foreach($b in "esports_fade_bot","sports_fade_bot","cs2_model_bot","cs2_inplay_bot","telegram_bot","main.py dashboard"){
    $pat = "(?<![A-Za-z])" + [regex]::Escape($b)
    $n = @($cmds | Where-Object { $_ -and ($_ -match $pat) }).Count
    Write-Output ("{0,-20} {1} proc {2}" -f $b,$n,$(if($n -eq 0){"<<< DOWN"}else{"OK"}))
}
