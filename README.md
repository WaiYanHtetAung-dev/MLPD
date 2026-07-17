# MLPD Ubuntu
#Read this first then readme-mm.md
MLPD Ubuntu is a license plate detection and OCR web app built for local use
and Ubuntu server deployment. It combines:

- YOLO-based plate detection
- PaddleOCR or EasyOCR text reading
- plate color and vehicle-type classification
- FastAPI dashboard and JSON endpoints
- capture history and event logs

## What This Repo Contains

- `server.py` and `server_daemon.py` for the web app
- `lpr_engine.py` for detection, OCR, and matching logic
- `lpr_service.py` for data persistence and API support
- `static/` and `dashboard.html` for the UI
- `setup_ubuntu.sh` and `start.sh` for Ubuntu deployment
- `deploy_to_ubuntu.ps1` and `open_browser.ps1` for Windows helpers

## Before You Publish

This project is ready to use, but a few values are machine-specific and should
be reviewed before you push to GitHub or deploy to your own server:

- Replace placeholder IP/host values in the helper scripts
- Set your own public URL when opening the browser
- Confirm the Ubuntu target path before running deployment helpers
- Rebuild the virtual environment if the server Python version changes

The repo now uses generic placeholders in the deployment docs and helper
scripts, so you should only need to set your own values once.

## Quick Start

### Local / Development

If you already have a working Python environment:

```bash
python server.py
```

Open:

```text
http://127.0.0.1:8000
```

### Ubuntu Server Setup

1. Copy the project to your Ubuntu server.
2. SSH into the server.
3. Run `./setup_ubuntu.sh` once.
4. Start the app with `./start.sh`.

For full deployment notes, 
read [README_UBUNTU.md(English)](README_UBUNTU.md) & [README_UBUNTU_mm.md(Myanmar)](README_UBUNTU_mm.md).

## Deployment Placeholders

Update these values for your own environment:

- `YOUR_SERVER_IP`
- `YOUR_SERVER_USER`
- `YOUR_SERVER_PORT`
- `YOUR_REMOTE_DIR`
- `YOUR_PUBLIC_HOST`

Examples:

```powershell
$env:MLPD_URL = "http://YOUR_SERVER_IP:8000"
.\open_browser.ps1
```

```powershell
.\deploy_to_ubuntu.ps1 -HostName "ubuntu@YOUR_SERVER_IP" -RemoteDir "/home/ubuntu/MLPD_ubuntu"
```

```bash
PUBLIC_HOST=YOUR_SERVER_IP ./start.sh
```

## Recommended Folder Layout On Ubuntu

```text
/home/ubuntu/MLPD_ubuntu
```

## Port

Default port:

```text
8000
```

If you want another port:

```bash
PORT=8001 ./start.sh
```

## OCR / Performance Notes

PaddleOCR is preferred when available. The app also supports a faster Paddle
mode that reduces repeated OCR passes on CPU-only machines.

Useful environment variables:

```bash
MLPD_USE_PADDLE_OCR=1
MLPD_PADDLE_FAST_MODE=1
MLPD_PADDLE_DET_MODEL_NAME=PP-OCRv5_server_det
MLPD_PADDLE_REC_MODEL_NAME=en_PP-OCRv5_mobile_rec
```

If you add a lighter Paddle detector model later, place it under
`.paddlex/official_models/` and set `MLPD_PADDLE_DET_MODEL_NAME` to that
folder name.

## Logs And Data

- `captures/` stores detected plate crops
- `data/` stores the SQLite event database
- `detection_log.txt` stores text logs
- `server.log` and `server-error.log` store runtime output

## Notes

- The Ubuntu setup script installs Python 3.12 locally because Paddle wheels
  are not available for every system Python version.
- Browser live camera access needs localhost or HTTPS.
- If you are deploying publicly, use trusted TLS certs and a proper public
  host name.

## Related Guide

- [README_UBUNTU.md](README_UBUNTU.md)
- [README_UBUNTU_mm.md](README_UBUNTU_mm.md)
