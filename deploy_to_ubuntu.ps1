param(
    [string]$HostName = "ubuntu@52.76.141.146",
    [string]$RemoteDir = "/home/ubuntu/MLPD_ubuntu"
)

Set-Location -Path $PSScriptRoot

Write-Output "Uploading MLPD_ubuntu to ${HostName}:$RemoteDir ..."
ssh $HostName "mkdir -p '$RemoteDir'"
scp -r `
    .paddlex `
    captures `
    color_classifier `
    data `
    static `
    car_models.txt `
    dashboard.html `
    detection_log.txt `
    lpr_engine.py `
    lpr_service.py `
    plate_detector.pt `
    plate_rules.txt `
    requirements.txt `
    requirements-ubuntu.txt `
    server.py `
    server_daemon.py `
    setup_ubuntu.sh `
    start.sh `
    stop.sh `
    logs.sh `
    open_browser.ps1 `
    README_UBUNTU.md `
    "${HostName}:$RemoteDir/"

Write-Output "Upload complete."
Write-Output "On the server:"
Write-Output "  ssh $HostName"
Write-Output "  cd $RemoteDir"
Write-Output "  chmod +x setup_ubuntu.sh start.sh stop.sh logs.sh"
Write-Output "  ./setup_ubuntu.sh"
Write-Output "  ./start.sh"
