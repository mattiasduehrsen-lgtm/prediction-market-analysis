# Stats only on post-v1.33 brain calls (after 2026-05-11 22:00).
# v1.32 had 48 calls cumulative; anything beyond is v1.33.

$log = "C:\Users\matti\Desktop\prediction-market-analysis\bot.log"
$all = Select-String -Path $log -Pattern "\[BRAIN\] [A-Z][A-Z][A-Z] regime="
$v133 = $all | Select-Object -Skip 48   # skip the first 48 (v1.32 calls)

Write-Host "Total all-time brain advise() calls: $($all.Count)"
Write-Host "Post-v1.33 brain advise() calls:     $($v133.Count)"
Write-Host ""

if ($v133.Count -eq 0) {
    Write-Host "(no v1.33 calls yet - nothing to analyze)"
    exit
}

$strong   = ($v133 | Where-Object { $_.Line -match "mr_edge=strong"   }).Count
$normal   = ($v133 | Where-Object { $_.Line -match "mr_edge=normal"   }).Count
$degraded = ($v133 | Where-Object { $_.Line -match "mr_edge=degraded" }).Count
Write-Host "mr_edge   : strong=$strong  normal=$normal  degraded=$degraded"

$ranging  = ($v133 | Where-Object { $_.Line -match "regime=ranging"   }).Count
$trending = ($v133 | Where-Object { $_.Line -match "regime=trending"  }).Count
$volatile = ($v133 | Where-Object { $_.Line -match "regime=volatile"  }).Count
$unclear  = ($v133 | Where-Object { $_.Line -match "regime=unclear"   }).Count
Write-Host "regime    : ranging=$ranging  trending=$trending  volatile=$volatile  unclear=$unclear"

$modifiers = $v133 | ForEach-Object {
    if ($_.Line -match "modifier=([+\-][0-9.]+)") { [double]$matches[1] }
}
if ($modifiers.Count -gt 0) {
    $mean = ($modifiers | Measure-Object -Average).Average
    $min  = ($modifiers | Measure-Object -Minimum).Minimum
    $max  = ($modifiers | Measure-Object -Maximum).Maximum
    $neg  = ($modifiers | Where-Object { $_ -lt 0 }).Count
    $zero = ($modifiers | Where-Object { $_ -eq 0 }).Count
    $pos  = ($modifiers | Where-Object { $_ -gt 0 }).Count
    Write-Host "modifier  : mean=$mean  min=$min  max=$max"
    Write-Host "modifier  : neg=$neg  zero=$zero  pos=$pos"
}

$btc = ($v133 | Where-Object { $_.Line -match "\[BRAIN\] BTC" }).Count
$eth = ($v133 | Where-Object { $_.Line -match "\[BRAIN\] ETH" }).Count
$sol = ($v133 | Where-Object { $_.Line -match "\[BRAIN\] SOL" }).Count
Write-Host "by asset  : BTC=$btc  ETH=$eth  SOL=$sol"

$skip = ($v133 | Where-Object { $_.Line -match "(?i)\bskip\b" }).Count
$zero_edge = ($v133 | Where-Object { $_.Line -match "(?i)zero edge|no edge" }).Count
$insuff = ($v133 | Where-Object { $_.Line -match "(?i)insufficient" }).Count
$fourh_conf = ($v133 | Where-Object { $_.Line -match "(?i)4h.*15(min|m)|15(min|m).*4h|window.*too long|too long.*window" }).Count
Write-Host "reasoning: 'skip'=$skip  'zero/no edge'=$zero_edge  'insufficient'=$insuff  4h-confusion=$fourh_conf"

Write-Host ""
Write-Host "=== Last 10 v1.33 brain calls (chronological) ==="
$v133 | Select-Object -Last 10 | ForEach-Object { $_.Line }
