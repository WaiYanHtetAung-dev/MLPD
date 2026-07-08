Set-Location -Path $PSScriptRoot

$listeners = netstat -ano | Select-String -Pattern "^\s*TCP\s+\S+:80(00|01|02)\s+\S+\s+LISTENING\s+(\d+)"
$pids = @()
foreach ($line in $listeners) {
    if ($line.Matches.Count -gt 0) {
        $pids += [int]$line.Matches[0].Groups[2].Value
    }
}

$pidFile = Join-Path $PSScriptRoot "server.pid"
$launcherPidFile = Join-Path $PSScriptRoot "server-launcher.pid"
foreach ($knownPidFile in @($pidFile, $launcherPidFile)) {
    if (-not (Test-Path $knownPidFile)) {
        continue
    }
    $pidText = (Get-Content -Path $knownPidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($pidText -match "^\d+$") {
        $pids += [int]$pidText
    }
}

$pids = $pids | Sort-Object -Unique
if (-not $pids.Count) {
    Write-Output "No MLPD server is listening on ports 8000-8002."
    Remove-Item -Path $pidFile -Force -ErrorAction SilentlyContinue
    Remove-Item -Path $launcherPidFile -Force -ErrorAction SilentlyContinue
    return
}

foreach ($pidValue in $pids) {
    Write-Output "Stopping MLPD server PID $pidValue..."
    Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
}

Start-Sleep -Seconds 1
Remove-Item -Path $pidFile -Force -ErrorAction SilentlyContinue
Remove-Item -Path $launcherPidFile -Force -ErrorAction SilentlyContinue
Write-Output "Stopped."
