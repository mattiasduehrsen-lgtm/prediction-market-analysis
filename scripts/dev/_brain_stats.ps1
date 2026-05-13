$lines = Select-String -Path "C:\Users\matti\Desktop\prediction-market-analysis\bot.log" -Pattern "\[BRAIN\] [A-Z][A-Z]"
Write-Host "Total brain advise() calls: $($lines.Count)"
Write-Host ""
$strong   = ($lines | Where-Object { $_.Line -match "mr_edge=strong"   }).Count
$normal   = ($lines | Where-Object { $_.Line -match "mr_edge=normal"   }).Count
$degraded = ($lines | Where-Object { $_.Line -match "mr_edge=degraded" }).Count
Write-Host "mr_edge   : strong=$strong  normal=$normal  degraded=$degraded"
$ranging  = ($lines | Where-Object { $_.Line -match "regime=ranging"   }).Count
$trending = ($lines | Where-Object { $_.Line -match "regime=trending"  }).Count
$volatile = ($lines | Where-Object { $_.Line -match "regime=volatile"  }).Count
$unclear  = ($lines | Where-Object { $_.Line -match "regime=unclear"   }).Count
Write-Host "regime    : ranging=$ranging  trending=$trending  volatile=$volatile  unclear=$unclear"
$modifiers = $lines | ForEach-Object {
    if ($_.Line -match "modifier=([+\-][0-9.]+)") { [double]$matches[1] }
}
$mean = ($modifiers | Measure-Object -Average).Average
$min  = ($modifiers | Measure-Object -Minimum).Minimum
$max  = ($modifiers | Measure-Object -Maximum).Maximum
$neg  = ($modifiers | Where-Object { $_ -lt 0 }).Count
$zero = ($modifiers | Where-Object { $_ -eq 0 }).Count
$pos  = ($modifiers | Where-Object { $_ -gt 0 }).Count
Write-Host "modifier  : mean=$mean  min=$min  max=$max"
Write-Host "modifier  : neg=$neg  zero=$zero  pos=$pos"
$btc = ($lines | Where-Object { $_.Line -match "\[BRAIN\] BTC" }).Count
$eth = ($lines | Where-Object { $_.Line -match "\[BRAIN\] ETH" }).Count
$sol = ($lines | Where-Object { $_.Line -match "\[BRAIN\] SOL" }).Count
Write-Host "by asset  : BTC=$btc  ETH=$eth  SOL=$sol"
$skip_mentions = ($lines | Where-Object { $_.Line -match "(?i)\bskip\b" }).Count
Write-Host "calls with 'skip' in reasoning: $skip_mentions"
$zero_edge_mentions = ($lines | Where-Object { $_.Line -match "(?i)zero edge" }).Count
Write-Host "calls mentioning 'zero edge': $zero_edge_mentions"
$fourh_confusion = ($lines | Where-Object { $_.Line -match "(?i)4h.*15(min|m)|15(min|m).*4h" }).Count
Write-Host "calls with 4h vs 15m confusion: $fourh_confusion"
