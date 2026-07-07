$Url = $env:MLPD_URL
if ([string]::IsNullOrWhiteSpace($Url)) {
    $Url = "http://52.76.141.146:8000"
}

Write-Host "Opening $Url ..."
Start-Process $Url
