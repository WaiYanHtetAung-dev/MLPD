# MLPD Ubuntu Deployment

Target server:

```text
ubuntu@52.76.141.146
```

Remote project folder:

```text
/home/ubuntu/MLPD_ubuntu
```

## Upload From Windows

From PowerShell in this folder:

```powershell
.\deploy_to_ubuntu.ps1
```

Or manually:

```powershell
ssh ubuntu@52.76.141.146 "mkdir -p /home/ubuntu/MLPD_ubuntu"
scp -r .paddlex captures color_classifier data static *.py *.txt *.pt *.html *.sh *.ps1 requirements*.txt README_UBUNTU.md ubuntu@52.76.141.146:/home/ubuntu/MLPD_ubuntu/
```

## Setup On Ubuntu

```bash
ssh ubuntu@52.76.141.146
cd /home/ubuntu/MLPD_ubuntu
chmod +x setup_ubuntu.sh start.sh stop.sh logs.sh
./setup_ubuntu.sh
```

If setup was attempted before this package update, rebuild the virtualenv:

```bash
./stop.sh
rm -rf .venv
./setup_ubuntu.sh
```

Note: Ubuntu 26.04 uses Python 3.14 by default, but `paddlepaddle` wheels are
not available for Python 3.14. `setup_ubuntu.sh` installs `uv`, creates a
project-local Python 3.12 `.venv`, then installs PaddleOCR/PaddlePaddle there.
It also installs CPU-only PyTorch to avoid downloading large CUDA packages on
small Ubuntu servers.
It also installs Ubuntu system libraries required by OpenCV and the legacy
Tkinter UI imports used by the shared LPR engine.

## Run

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

## Logs

```bash
./logs.sh -f
./logs.sh -e -f
```

## Stop

```bash
./stop.sh
```

## Optional: Run as a systemd Service

After the first setup, you can install the service file:

```bash
sudo cp mlpd.service /etc/systemd/system/mlpd.service
sudo systemctl daemon-reload
sudo systemctl enable --now mlpd
sudo systemctl status mlpd
```

## Open In Browser

```text
http://52.76.141.146:8000
```

Make sure the Ubuntu server firewall/security group allows inbound TCP `8000`.

From Windows PowerShell:

```powershell
.\open_browser.ps1
```
