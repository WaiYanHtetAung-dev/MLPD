param(
    [switch]$Foreground,
    [switch]$OpenBrowser,
    [switch]$Install,
    [switch]$SkipInstall,
    [switch]$Restart
)

Set-Location -Path $PSScriptRoot

$runtimeTemp = Join-Path $PSScriptRoot ".runtime-temp"
New-Item -ItemType Directory -Path $runtimeTemp -Force | Out-Null
$env:TEMP = $runtimeTemp
$env:TMP = $runtimeTemp

$parentRoot = Split-Path $PSScriptRoot -Parent
$paddleVenvCandidates = @(
    (Join-Path $PSScriptRoot ".venv-paddle"),
    (Join-Path $parentRoot ".venv-paddle")
)
$runtimeVenvCandidates = @(
    (Join-Path $PSScriptRoot ".venv-runtime"),
    (Join-Path $parentRoot ".venv-runtime")
)
$paddleVenvPath = $paddleVenvCandidates | Where-Object { Test-Path (Join-Path $_ "Scripts\python.exe") } | Select-Object -First 1
$runtimeVenvPath = $runtimeVenvCandidates | Where-Object { Test-Path (Join-Path $_ "Scripts\python.exe") } | Select-Object -First 1
if (-not $runtimeVenvPath) {
    $runtimeVenvPath = Join-Path $PSScriptRoot ".venv-runtime"
}
$venvPath = if ($paddleVenvPath) { $paddleVenvPath } else { $runtimeVenvPath }
$venvPython = Join-Path $venvPath "Scripts\python.exe"
$venvPythonw = Join-Path $venvPath "Scripts\pythonw.exe"

function Get-SystemPython {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return @("py", "-3.13")
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return @("python")
    }
    throw "Python is not installed or is not available on PATH."
}

function Test-TcpPort {
    param([int]$Port)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $connect = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $connect.AsyncWaitHandle.WaitOne(250, $false)) {
            return $false
        }
        $client.EndConnect($connect)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Close()
    }
}

function Get-RunningMlpdPort {
    foreach ($candidatePort in 8000..8020) {
        if (-not (Test-TcpPort -Port $candidatePort)) {
            continue
        }
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$candidatePort/health" -TimeoutSec 2
            if ($health.status -eq "ok" -and $health.engine -eq "MLPD") {
                return $candidatePort
            }
        }
        catch {
        }
    }
    return $null
}

function Get-ListeningProcessId {
    param([int]$Port)
    $line = netstat -ano | Select-String -Pattern "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)" | Select-Object -First 1
    if ($line -and $line.Matches.Count -gt 0) {
        return [int]$line.Matches[0].Groups[1].Value
    }
    return $null
}

function Wait-ForMlpdReady {
    param([int]$Port, [int]$TimeoutSeconds = 150)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-TcpPort -Port $Port) {
            try {
                $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
                if ($health.status -eq "ok" -and $health.engine -eq "MLPD") {
                    return $true
                }
            }
            catch {
            }
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

$runningPort = Get-RunningMlpdPort
if ($runningPort) {
    $runningUrl = "http://localhost:$runningPort"
    if ($Restart) {
        $runningPid = Get-ListeningProcessId -Port $runningPort
        if ($runningPid) {
            Write-Output "Stopping existing MLPD server on port $runningPort (PID $runningPid)..."
            Stop-Process -Id $runningPid -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 1
        }
    } else {
        Write-Output "MLPD server is already running."
        Write-Output "URL: $runningUrl"
        Write-Output "Logs: .\logs.ps1 -Follow"
        if ($OpenBrowser) {
            Start-Process $runningUrl
        }
        return
    }
}

$systemPython = Get-SystemPython
$systemPythonExe = $systemPython[0]
$systemPythonArgs = @($systemPython | Select-Object -Skip 1)
$venvIsHealthy = $false
if (Test-Path $venvPython) {
    & $venvPython -c "import sys" 2>$null
    $venvIsHealthy = $LASTEXITCODE -eq 0
}

if (-not $venvIsHealthy) {
    Write-Output "Creating or repairing virtual environment (.venv-runtime)..."
    & $systemPythonExe @systemPythonArgs -m venv --clear $venvPath
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to create the virtual environment."
    }
}

if ($Install -and -not $SkipInstall) {
    Write-Output "Upgrading pip..."
    & $venvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to upgrade pip."
    }

    Write-Output "Installing requirements..."
    & $venvPython -m pip install --no-cache-dir -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to install requirements."
    }
} else {
    Write-Output "Skipping dependency install. Use -Install when requirements change."
}

$port = 8000
while (Test-TcpPort -Port $port) {
    Write-Output "Port $port is already in use. Trying next port..."
    $port++
}

Write-Output "Starting FastAPI app with uvicorn on port $port..."
$serverUrl = "http://localhost:$port"

if ($Foreground) {
    $browserJob = $null
    if ($OpenBrowser) {
        $browserJob = Start-Job -ScriptBlock {
            param($Url, $Port)
            for ($attempt = 0; $attempt -lt 60; $attempt++) {
                $client = New-Object System.Net.Sockets.TcpClient
                try {
                    $connect = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
                    if ($connect.AsyncWaitHandle.WaitOne(250, $false)) {
                        $client.EndConnect($connect)
                        Start-Process $Url
                        return
                    }
                }
                catch {
                }
                finally {
                    $client.Close()
                }
                Start-Sleep -Milliseconds 500
            }
        } -ArgumentList $serverUrl, $port
    }
    try {
        & $venvPython -m uvicorn server:app --host 0.0.0.0 --port $port
    }
    finally {
        if ($browserJob) {
            Remove-Job $browserJob -Force -ErrorAction SilentlyContinue
        }
    }
    return
}

$stdoutLog = Join-Path $PSScriptRoot "server.log"
$stderrLog = Join-Path $PSScriptRoot "server-error.log"
$pidFile = Join-Path $PSScriptRoot "server.pid"
$launcherPidFile = Join-Path $PSScriptRoot "server-launcher.pid"
$daemonPython = if (Test-Path $venvPythonw) { $venvPythonw } else { $venvPython }
$daemonScript = Join-Path $PSScriptRoot "server_daemon.py"
$daemonArgs = @(
    $daemonScript,
    "--root", $PSScriptRoot,
    "--port", $port,
    "--stdout-log", $stdoutLog,
    "--stderr-log", $stderrLog,
    "--pid-file", $pidFile
)
$serverProcess = Start-Process `
    -FilePath $daemonPython `
    -ArgumentList $daemonArgs `
    -WorkingDirectory $PSScriptRoot `
    -WindowStyle Hidden `
    -PassThru

$serverProcess.Id | Out-File -FilePath $launcherPidFile -Encoding ascii -Force
Write-Output "Waiting for MLPD server to finish startup..."
$ready = Wait-ForMlpdReady -Port $port
if ($ready) {
    Write-Output "Server is running in the background."
} else {
    Write-Output "Server was started, but it did not become ready yet. PaddleOCR may still be loading."
}
Write-Output "Launcher PID: $($serverProcess.Id)"
Write-Output "URL: $serverUrl"
Write-Output "Logs: $stdoutLog"
Write-Output "Errors: $stderrLog"
Write-Output "Live logs: .\logs.ps1 -Follow"

if ($OpenBrowser) {
    Start-Process $serverUrl
}
