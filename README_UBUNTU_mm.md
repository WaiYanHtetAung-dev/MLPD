# MLPD Ubuntu ဖြန့်ချိခြင်း လမ်းညွှန် (မြန်မာ)

ဒီလမ်းညွှန်ကို Ubuntu ဆာဗာပေါ်မှာ MLPD project ကို စတင်အသုံးပြုရန် အသေးစိတ် ရေးသားထားတာပါ။

## ၁။ စတင်မတိုင်မီ

မိမိဆာဗာပတ်ဝန်းကျင်အတွက် အောက်ပါ placeholder တွေကို ပြင်ဆင်ပါ။

- `YOUR_SERVER_IP` — ဆာဗာ IP
- `YOUR_SERVER_USER` — ဆာဗာ user name
- `YOUR_REMOTE_DIR` — remote ဒိုင်ရက်ထရီ
- `YOUR_PUBLIC_HOST` — public browser URL အတွက် host
- `YOUR_SSL_CERTFILE` — SSL certificate ဖိုင်လမ်းကြောင်း
- `YOUR_SSL_KEYFILE` — SSL private key ဖိုင်လမ်းကြောင်း

အကြံပြု remote ဖိုလ်ဒါ

```text
/home/ubuntu/MLPD_ubuntu
```

## ၂။ Windows ကနေ Ubuntu သို့ Upload လုပ်ခြင်း

အရင်ဆုံး repo ကို Windows မှာ sync လုပ်ချင်ရင် helper script ကို အသုံးပြုပါ။

```powershell
.\deploy_to_ubuntu.ps1
```

manual copy လုပ်ချင်ရင် placeholder တွေကို အစားထိုးပြီး ဒီ command ကို သုံးပါ။

```powershell
ssh YOUR_SERVER_USER@YOUR_SERVER_IP "mkdir -p /home/ubuntu/MLPD_ubuntu"
scp -r .paddlex captures color_classifier data static *.py *.txt *.pt *.html *.sh *.ps1 requirements*.txt README*.md YOUR_SERVER_USER@YOUR_SERVER_IP:/home/ubuntu/MLPD_ubuntu/
```

## ၃။ Ubuntu ပေါ်တွင် Setup ပြုလုပ်ခြင်း

ဆာဗာထဲ ဝင်ပြီး အောက်ပါ commands ကို run ပါ။

```bash
ssh YOUR_SERVER_USER@YOUR_SERVER_IP
cd /home/ubuntu/MLPD_ubuntu
chmod +x setup_ubuntu.sh start.sh stop.sh logs.sh
./setup_ubuntu.sh
```

### အရေးကြီး

- တစ်ခါတည်း setup ပြီးပြီဆို `.venv` ဖိုလ်ဒါလည်း ဖန်တီးပြီးသားဖြစ်ပါတယ်။
- dependency ပြောင်းလဲမှုများ ရှိလျှင် အောက်ပါအတိုင်း `.venv` ကို ပြန်လုပ်ပါ။

```bash
./stop.sh
rm -rf .venv
./setup_ubuntu.sh
```

## ၄။ setup script က ဘာလုပ်သလဲ

- OpenCV နဲ့ Tkinter လို system packages များ install လုပ်သည်
- `uv` command လိုအပ်လျှင် install လုပ်သည်
- Python 3.12 အတွက် project-local `.venv` ဖန်တီးသည်
- PyTorch CPU wheel များ install လုပ်သည်
- project requirements များ install လုပ်သည်
- PaddleOCR နဲ့ PaddlePaddle imports ကို စစ်ဆေးသည်

## ၅။ app ကို စတင်ရန်

```bash
./start.sh
```

### ပေါ့(Port) ဖြေရှင်းနည်း

- default port: `8000`
- အခြား port သုံးရန်:

```bash
PORT=8001 ./start.sh
```

### Browser URL ကို public host ဖြင့် ပြရန်

```bash
PUBLIC_HOST=YOUR_PUBLIC_HOST ./start.sh
```

### TLS ကို ဖွင့်ရန်

```bash
SSL_CERTFILE=/path/to/fullchain.pem SSL_KEYFILE=/path/to/privkey.pem ./start.sh
```

## ၆။ browser ဖြင့် ဝင်ရောက်ကြည့်ရန်

- local access:

```text
http://127.0.0.1:8000
```

- LAN/Public access (server IP or host ကို သုံးပါ):

```text
http://YOUR_SERVER_IP:8000
```

- HTTPS သုံးချင်လျှင်:

```text
https://YOUR_SERVER_IP:8000
```

## ၇။ helper scripts များ

- `open_browser.ps1` — browser မှာ dashboard URL ကို ဖွင့်ပေးသည်
- `deploy_to_ubuntu.ps1` — project ကို remote သို့ sync လုပ်ပြီး server ကို စတင်ပေးသည်
- `logs.sh` — log output များကို ကြည့်ရန်
- `stop.sh` — server ရပ်ရန်

browser URL ကို အောက်ပါအတိုင်း သတ်မှတ်နိုင်သည်။

```powershell
$env:MLPD_URL = "http://YOUR_SERVER_IP:8000"
.\open_browser.ps1
```

## ၈။ Paddle OCR များအတွက် speed tuning

app က PaddleOCR ကို နောက်ဆုံး အနေဖြင့် အသုံးပြုပါတယ်။

```bash
MLPD_USE_PADDLE_OCR=1
MLPD_PADDLE_FAST_MODE=1
MLPD_PADDLE_DET_MODEL_NAME=PP-OCRv5_server_det
MLPD_PADDLE_REC_MODEL_NAME=en_PP-OCRv5_mobile_rec
```

### မှတ်ချက်များ

- CPU-only ဆာဗာများတွင် `MLPD_PADDLE_FAST_MODE=1` အထူးသင့်တော်သည်
- `.paddlex/official_models/` ထဲသို့ lighter detector model တစ်ခု ထည့်လိုလျှင် `MLPD_PADDLE_DET_MODEL_NAME` ကို ထို folder နာမည်ဖြင့် ပြင်ပါ
- Paddle import မအောင်မြင်ပါက app က EasyOCR သို့ fallback လုပ်ပါသည်

## ၉။ logs နှင့် data ဖိုင်များ

- `captures/` — plate crop image များ သိမ်းဆည်းသည်
- `data/` — SQLite database သိမ်းဆည်းသည်
- `detection_log.txt` — text log များ သိမ်းဆည်းသည်
- `server.log`, `server-error.log` — runtime output များ သိမ်းဆည်းသည်

## ၁၀။ ပြဿနာဖြေရှင်းခြင်း

- app မစတင်နိုင်ပါက `server-error.log` ကို စစ်ပါ
- OCR နှေးနေပါက logs မှ Paddle သုံးနေကြောင်း စစ်ပါ
- browser access မရပါက firewall သို့ port ကို ဖွင့်ထားကြောင်း စစ်ပါ
- Python version ပြောင်းလဲပါက `.venv` ကို ဖျက်ပြီး ပြန်တည်ဆောက်ပါ

## ၁၁။ optional systemd service

```bash
sudo cp mlpd.service /etc/systemd/system/mlpd.service
sudo systemctl daemon-reload
sudo systemctl enable --now mlpd
sudo systemctl status mlpd
```

## ၁၂။ ဆက်စပ် ဖိုင်များ

- `README.md`
- `setup_ubuntu.sh`
- `start.sh`
- `deploy_to_ubuntu.ps1`
