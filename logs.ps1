param(
    [switch]$ErrorLog,
    [switch]$Follow
)

Set-Location -Path $PSScriptRoot

$logPath = if ($ErrorLog) {
    Join-Path $PSScriptRoot "server-error.log"
} else {
    Join-Path $PSScriptRoot "server.log"
}

if (-not (Test-Path $logPath)) {
    New-Item -ItemType File -Path $logPath -Force | Out-Null
}

Write-Output "Showing $logPath"
if ($Follow) {
    Get-Content -Path $logPath -Tail 80 -Wait | ForEach-Object { $_ -replace "`0", "" }
} else {
    Get-Content -Path $logPath -Tail 120 | ForEach-Object { $_ -replace "`0", "" }
}
