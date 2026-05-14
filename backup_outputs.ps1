# Daily backup of output/ directory to a gzipped archive in backups/.
# Keeps the last 30 days; older archives deleted.
#
# Designed for the BackupOutputs scheduled task. Doesn't touch bot processes.

$ErrorActionPreference = "Continue"
$root      = "C:\Users\matti\Desktop\prediction-market-analysis"
$srcDir    = "$root\output"
$bkpDir    = "$root\backups"

if (-not (Test-Path $srcDir)) {
    Write-Host "[backup] source $srcDir not found - nothing to do"
    exit 0
}
New-Item -ItemType Directory -Path $bkpDir -Force | Out-Null

$stamp   = Get-Date -Format "yyyy-MM-dd-HHmm"
$archive = "$bkpDir\output-$stamp.zip"

try {
    # Compress-Archive is the simplest Windows-native option, no external deps.
    # output/ is small (mostly CSV + JSON), so compression is cheap.
    Compress-Archive -Path "$srcDir\*" -DestinationPath $archive -Force
    $size = (Get-Item $archive).Length / 1MB
    Write-Host ("[backup] wrote {0} ({1:N1} MB)" -f $archive, $size)
} catch {
    Write-Host "[backup] ERROR: $_" -ForegroundColor Red
    exit 1
}

# Prune archives older than 30 days
$cutoff = (Get-Date).AddDays(-30)
$pruned = 0
Get-ChildItem -Path $bkpDir -Filter "output-*.zip" -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt $cutoff } |
    ForEach-Object {
        Remove-Item $_.FullName -Force
        $pruned++
    }
if ($pruned -gt 0) {
    Write-Host "[backup] pruned $pruned archive(s) older than 30 days"
}
