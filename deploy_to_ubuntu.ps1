param(
    [string]$HostName = "ubuntu@YOUR_SERVER_IP",
    [string]$RemoteDir = "/home/ubuntu/MLPD_ubuntu",
    [string]$SshKey = "$HOME/.ssh/id_rsa"
)

Set-Location -Path $PSScriptRoot

Write-Output "Syncing MLPD_ubuntu to ${HostName}:$RemoteDir ..."

# Use rsync for more efficient file transfer.
# It only copies changed files and allows for easy exclusion.
# Note: rsync needs to be installed on your Windows machine.
# You can install it via WSL, Cygwin, or Git Bash.
rsync -avz -e "ssh -i '$SshKey'" --delete `
    --exclude '.git' `
    --exclude '.idea' `
    --exclude '__pycache__' `
    --exclude '*.pyc' `
    --exclude 'deploy_to_ubuntu.ps1' `
    --exclude 'open_browser.ps1' `
    --exclude 'README.md' `
    . "${HostName}:$RemoteDir/"

Write-Output "Sync complete."
Write-Output "Running setup and starting the service on the server..."

# Execute remote commands in a single SSH session
ssh -i $SshKey $HostName "
    cd '$RemoteDir'
    chmod +x setup_ubuntu.sh start.sh stop.sh logs.sh
    ./setup_ubuntu.sh
    ./start.sh
"

Write-Output "Deployment and startup process finished."
