# MLPD Ubuntu ဖြန့်ချိခြင်း လမ်းညွှန် (မြန်မာဘာသာ)

ဒီလမ်းညွှန်ကတော့ ကိုယ့်ရဲ့ Ubuntu ဆာဗာပေါ်မှာ project ကို တင်ပြီး chạy ဖို့ အသုံးပြုနိုင်ပါတယ်။

## စတင်မတိုင်မီ

အောက်က placeholder တွေကို သင့်ပတ်ဝန်းကျင်နှင့် ကိုက်ညီအောင် ပြင်ပါ —

- `YOUR_SERVER_IP`
- `YOUR_SERVER_USER`
- `YOUR_REMOTE_DIR`
- `YOUR_PUBLIC_HOST`
- `YOUR_SSL_CERTFILE`
- `YOUR_SSL_KEYFILE`

အကြံပြုထားတဲ့ remote ဖိုလ်ဒါ

```text
/home/ubuntu/MLPD_ubuntu
```

## Windows ကနေ Upload ချင်ရင်

helper script ကို အသုံးပြုရင် အလွယ်ဆုံးပါ —

```powershell
.\deploy_to_ubuntu.ps1
```

ဖိုင်တွေကို သင်မစေ့ဝင်ဘဲ ကိုယ့်ဆီမှာ manual ဖြင့် ကူးပို့ချင်ရင် placeholder တွေကို အစားထိုးပြီး ဒီလို run ပါ —

```powershell
ssh YOUR_SERVER_USER@YOUR_SERVER_IP "mkdir -p /home/ubuntu/MLPD_ubuntu"
scp -r .paddlex captures color_classifier data static *.py *.txt *.pt *.html *.sh *.ps1 requirements*.txt README*.md YOUR_SERVER_USER@YOUR_SERVER_IP:/home/ubuntu/MLPD_ubuntu/
```

## Ubuntu ပေါ်မှာ Setup ပြုလုပ်နည်း

ဆာဗာပေါ်သို့ဝင်ပြီး ဒီအတိုင်းလုပ်ပါ —

```bash
ssh YOUR_SERVER_USER@YOUR_SERVER_IP
cd /home/ubuntu/MLPD_ubuntu
chmod +x setup_ubuntu.sh start.sh stop.sh logs.sh
./setup_ubuntu.sh
```

dependency ပြောင်းလဲမှုတစ်ခုခုကြောင့် ဖန်တီးမှုကို အရင်တင်ထားခဲ့ပြီးသားဖြစ်ပါက local virtual environment ကို ပြန်လုပ်ရန် —

```bash
./stop.sh
rm -rf .venv
./setup_ubuntu.sh
```

## setup script က ဘာတွေလုပ်သလဲ

- OpenCV နဲ့ Tkinter များအတွက် လိုအပ်တဲ့ system packages များ install လုပ်သည်
- `uv` ကို လိုအပ်လျှင် install လုပ်သည်
- Python 3.12 အတွက် project-local `.venv` ဖန်တီးသည်
- PyTorch CPU wheel များ install လုပ်သည်
- project requirements များ install လုပ်သည်
- PaddleOCR နှင့် PaddlePaddle import စစ်ဆေးသည်

## Run (စတင်အသုံးပြုနည်း)

app ကို စတင်ရန် —

```bash
./start.sh
```

Default port —

```text
8000
```

အခြား port သုံးချင်ရင် —

```bash
PORT=8001 ./start.sh
```

browser URL မှာ public host ကိုပဲ ပြသချင်ရင် —

```bash
PUBLIC_HOST=YOUR_PUBLIC_HOST ./start.sh
```

TLS ကို အသုံးပြုချင်ရင် —

```bash
SSL_CERTFILE=/path/to/fullchain.pem SSL_KEYFILE=/path/to/privkey.pem ./start.sh
```

## Browser မှတဆင့် ဝင်ရောက်ကြည့်ရန်

local access စမ်းရန် —

```text
http://127.0.0.1:8000
```

public access အနေနဲ့ —

```text
http://YOUR_SERVER_IP:8000
```

TLS ဖွင့်ထားလျှင် —

```text
https://YOUR_SERVER_IP:8000
```

## Helper Scripts

- `open_browser.ps1` — dashboard URL ကို browser မှာဖွင့်ပေးတာ
- `deploy_to_ubuntu.ps1` — repo ကို sync လုပ်ပြီး remote က server ကို စတင်ပေးတယ်
- `logs.sh` နဲ့ `stop.sh` — Ubuntu မှာ service ကို စီမံခန့်ခွဲဖို့

browser URL ကို 이렇게 သတ်မှတ်နိုင်သည် —

```powershell
$env:MLPD_URL = "http://YOUR_SERVER_IP:8000"
.\open_browser.ps1
```

## Paddle OCR ရဲ့ ပမာဏ/အရမ်းမြန်အောင် စီစစ်ခြင်း (Speed Tuning)

app က PaddleOCR ကို ဦးစားပေးသုံးပါတယ်။

အသုံးဝင်တဲ့ override များ —

```bash
MLPD_USE_PADDLE_OCR=1
MLPD_PADDLE_FAST_MODE=1
MLPD_PADDLE_DET_MODEL_NAME=PP-OCRv5_server_det
MLPD_PADDLE_REC_MODEL_NAME=en_PP-OCRv5_mobile_rec
```

မှတ်ချက်များ —

- CPU-only ဆာဗာများအတွက် `MLPD_PADDLE_FAST_MODE=1` က အတော်ဆိုးကျေနပ်စေသည်
- အနာဂတ်တွင် `.paddlex/official_models/` အောက်တွင် ပိုဖေါ့ပါးတဲ့ detector model တစ်ခုထည့်မယ်ဆိုရင် `MLPD_PADDLE_DET_MODEL_NAME` ကို အဲဒီ folder နာမည်အတိုင်း ပြင်ပါ
- Paddle import ပြဿနာဖြစ်လာရင် app က EasyOCR သို့ fallback လုပ်ပါလိမ့်မယ်

## မွတ်တမ်းများ (Logs) နှင့် Data

- `captures/` — plate crops များကို သိမ်းဆည်းထားသည်
- `data/` — SQLite database ကို သိမ်းဆည်းထားသည်
- `detection_log.txt` — စာသား log များကို သိမ်းဆည်းထားသည်
- `server.log` နှင့် `server-error.log` — runtime output များကို သိမ်းဆည်းထားသည်

## ပြဿနာဖြေရှင်းခြင်း (Troubleshooting)

- app မစတင်နိုင်လျှင် `server-error.log` ကို စစ်ပါ
- OCR မြန်ပျော့မလာပါက logs တွင် Paddle သုံးနေရတာကို စစ်ပါ
- Browser access မရပါက firewall မှာ ပေါ့(ports) သူ့ကို ဖွင့်ထားကြောင်း စစ်ပါ
- Python version ပြောင်းလဲလိုက်ရင် `.venv` ကို ပြန်ဖျက်ပြီး ပြန်တည်ဆောက်ပါ

## Systemd

optional service install နမူနာ —

```bash
sudo cp mlpd.service /etc/systemd/system/mlpd.service
sudo systemctl daemon-reload
sudo systemctl enable --now mlpd
sudo systemctl status mlpd
```

## ဆက်စပ်ဖိုင်များ

- [README.md](README.md)
- [setup_ubuntu.sh](setup_ubuntu.sh)
- [start.sh](start.sh)

---

ဒီဖိုင်ကို workspace အောက် `MLPD_ubuntu` ဖိုလ်ဒါထဲမှာ `README_UBUNTU_mm.md` အဖြစ် ထည့်လိုက်ပါတယ်။

သင်လိုချင်ရင် original `README_UBUNTU.md` ကိုလည်း အစားထိုးပေးနိုင်ပါတယ်၊ ဒါမှမဟုတ် `.sh` ဖိုင်တွေ LF ပြင်ပေးဖို့ ကူညီပေးပါမယ်။
