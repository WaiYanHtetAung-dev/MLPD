$Url = $env:MLPD_URL
if ([string]::IsNullOrWhiteSpace($Url)) {
    $Url = "http://127.0.0.1:8000"
}

Write-Host "Opening $Url ..."
Start-Process $Url
