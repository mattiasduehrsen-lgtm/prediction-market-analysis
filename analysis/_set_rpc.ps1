param([Parameter(Mandatory=$true)][string]$Url)
$f = "C:\Users\matti\Desktop\prediction-market-analysis\.env"
# Drop any existing POLYGON_RPC_URL line, then append the new one
(Get-Content $f) | Where-Object { $_ -notmatch '^POLYGON_RPC_URL=' } | Set-Content $f
Add-Content $f "POLYGON_RPC_URL=$Url"
$masked = ($Url -split '/v2/')[0] + '/v2/****'
if (Select-String -Path $f -Pattern '^POLYGON_RPC_URL=' -Quiet) {
    Write-Output "POLYGON_RPC_URL set to $masked"
} else {
    Write-Output "FAILED to set POLYGON_RPC_URL"
}
