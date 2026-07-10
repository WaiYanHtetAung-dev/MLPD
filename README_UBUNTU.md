# MLPD Ubuntu Deployment Guide

This guide is for running the project on your own Ubuntu server.

## Before You Start

Update these placeholders to match your environment:

- `YOUR_SERVER_IP`
- `YOUR_SERVER_USER`
- `YOUR_REMOTE_DIR`
- `YOUR_PUBLIC_HOST`
- `YOUR_SSL_CERTFILE`
- `YOUR_SSL_KEYFILE`

Recommended remote folder:

```text
/home/ubuntu/MLPD_ubuntu
```

## Upload From Windows

The helper script is the easiest way to sync the project:

```powershell
.\deploy_to_ubuntu.ps1
```

If you want to run it manually, replace the placeholders first:

```powershell
ssh YOUR_SERVER_USER@YOUR_SERVER_IP "mkdir -p /home/ubuntu/MLPD_ubuntu"
scp -r .paddlex captures color_classifier data static *.py *.txt *.pt *.html *.sh *.ps1 requirements*.txt README*.md YOUR_SERVER_USER@YOUR_SERVER_IP:/home/ubuntu/MLPD_ubuntu/
```

## Ubuntu Setup

On the server:

```bash
ssh YOUR_SERVER_USER@YOUR_SERVER_IP
cd /home/ubuntu/MLPD_ubuntu
chmod +x setup_ubuntu.sh start.sh stop.sh logs.sh
./setup_ubuntu.sh
```

If you already tried setup before a dependency change, rebuild the local
virtual environment:

```bash
./stop.sh
rm -rf .venv
./setup_ubuntu.sh
```

## What The Setup Script Does

- Installs system packages needed by OpenCV and Tkinter
- Installs `uv` if needed
- Creates a project-local Python 3.12 `.venv`
- Installs PyTorch CPU wheels
- Installs the project requirements
- Verifies PaddleOCR and PaddlePaddle imports

## Run

Start the app:

```bash
./start.sh
```

Default port:

```text
8000
```

Use another port:

```bash
PORT=8001 ./start.sh
```

If you want the browser URL to show your public host, override it:

```bash
PUBLIC_HOST=YOUR_PUBLIC_HOST ./start.sh
```

## Browser Access

Local access:

```text
http://127.0.0.1:8000
```

Public access example:

```text
http://YOUR_SERVER_IP:8000
```

If you enable TLS:

```bash
SSL_CERTFILE=/path/to/fullchain.pem SSL_KEYFILE=/path/to/privkey.pem ./start.sh
```

## Helper Scripts

- `open_browser.ps1` opens the dashboard URL
- `deploy_to_ubuntu.ps1` syncs the repo and starts the server remotely
- `logs.sh` and `stop.sh` manage the service on Ubuntu

Set your browser URL like this:

```powershell
$env:MLPD_URL = "http://YOUR_SERVER_IP:8000"
.\open_browser.ps1
```

## Paddle OCR Speed Tuning

The app prefers PaddleOCR when available.

Useful overrides:

```bash
MLPD_USE_PADDLE_OCR=1
MLPD_PADDLE_FAST_MODE=1
MLPD_PADDLE_DET_MODEL_NAME=PP-OCRv5_server_det
MLPD_PADDLE_REC_MODEL_NAME=en_PP-OCRv5_mobile_rec
```

Notes:

- CPU-only servers benefit most from `MLPD_PADDLE_FAST_MODE=1`
- If you later add a lighter detector model under `.paddlex/official_models/`,
  set `MLPD_PADDLE_DET_MODEL_NAME` to that folder name
- If Paddle fails to import, the app falls back to EasyOCR

## Logs And Data

- `captures/` stores plate crops
- `data/` stores the SQLite database
- `detection_log.txt` stores text logs
- `server.log` and `server-error.log` store runtime output

## Troubleshooting

- If the app does not start, check `server-error.log`
- If OCR is slow, confirm Paddle is being used in the logs
- If browser access fails, make sure the port is open in your firewall
- If you change Python versions, rebuild `.venv`

## Systemd

Optional service install:

```bash
sudo cp mlpd.service /etc/systemd/system/mlpd.service
sudo systemctl daemon-reload
sudo systemctl enable --now mlpd
sudo systemctl status mlpd
```

## Related Files

- [README.md](README.md)
- [setup_ubuntu.sh](setup_ubuntu.sh)
- [start.sh](start.sh)
- [deploy_to_ubuntu.ps1](deploy_to_ubuntu.ps1)
