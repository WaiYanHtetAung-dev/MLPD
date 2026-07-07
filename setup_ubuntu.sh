#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y curl ca-certificates python3 python3-venv python3-pip python3-tk ffmpeg libglib2.0-0 libgomp1 libgl1 libsm6 libxext6
fi

PYTHON_TARGET="${PYTHON_TARGET:-3.12}"
UV_BIN="${UV_BIN:-$HOME/.local/bin/uv}"

if [[ ! -x "$UV_BIN" ]] && ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv so this Ubuntu 26.04 server can use Python ${PYTHON_TARGET}..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi

if command -v uv >/dev/null 2>&1; then
  UV_BIN="$(command -v uv)"
fi

if [[ ! -x "$UV_BIN" ]]; then
  echo "uv was not installed. Check network access and rerun setup."
  exit 1
fi

"$UV_BIN" python install "$PYTHON_TARGET"

if [[ -x ".venv/bin/python" ]]; then
  CURRENT_VERSION="$(".venv/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  if [[ "$CURRENT_VERSION" != "$PYTHON_TARGET" ]]; then
    echo "Rebuilding .venv: found Python ${CURRENT_VERSION}, need Python ${PYTHON_TARGET} for PaddleOCR."
    rm -rf .venv
  fi
fi

"$UV_BIN" venv --python "$PYTHON_TARGET" --seed .venv
source .venv/bin/activate
python -c 'import sys; print("Using Python", sys.version)'
if ! python -m pip --version >/dev/null 2>&1; then
  echo "pip is missing from .venv; installing pip with ensurepip..."
  python -m ensurepip --upgrade
fi
python -m pip install --upgrade pip setuptools wheel
python -m pip cache purge || true
python -m pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchvision
python -m pip install --no-cache-dir -r requirements-ubuntu.txt

mkdir -p captures data .runtime-temp .cache .paddle .easyocr .paddlex

echo "Running a lightweight import smoke test..."
python - <<'PY'
import importlib.util
import sys
required_modules = ["fastapi", "uvicorn", "cv2", "numpy", "PIL", "ultralytics"]
missing = [name for name in required_modules if importlib.util.find_spec(name) is None]
if missing:
    raise SystemExit(f"Missing modules after setup: {', '.join(missing)}")
import lpr_engine
print("Python executable:", sys.executable)
print("PaddleOCR installed:", importlib.util.find_spec("paddleocr") is not None)
print("PaddlePaddle installed:", importlib.util.find_spec("paddle") is not None)
print("lpr_engine import smoke test: OK")
PY

echo "Ubuntu setup complete."
echo "Start with: ./start.sh"
