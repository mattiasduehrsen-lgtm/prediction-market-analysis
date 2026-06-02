param(
  [Parameter(Mandatory=$true)][string]$Name,
  [Parameter(Mandatory=$true)][string]$Value
)
$f = "C:\Users\matti\Desktop\prediction-market-analysis\.env"
(Get-Content $f) | Where-Object { $_ -notmatch "^$Name=" } | Set-Content $f
Add-Content $f "$Name=$Value"
if (Select-String -Path $f -Pattern "^$Name=" -Quiet) {
    $masked = if ($Value.Length -gt 8) { $Value.Substring(0,4) + "****" } else { "****" }
    Write-Output "$Name set ($masked)"
} else {
    Write-Output "FAILED to set $Name"
}
