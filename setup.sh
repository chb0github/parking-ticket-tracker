#!/usr/bin/env bash
# One-time environment setup for parking-ticket-tracker.
#
# Works on hosts where system pip / ensurepip / python3-venv are missing and
# sudo is unavailable (e.g. snowball): creates a venv WITHOUT pip, then
# bootstraps pip into it via get-pip.py, then installs requirements.
#
# Idempotent: safe to re-run. Invoke from anywhere:  bash setup.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$REPO_DIR/.venv"
PY="$VENV/bin/python3"

echo "[setup] repo: $REPO_DIR"

if [ ! -x "$PY" ]; then
  echo "[setup] creating venv (without pip) ..."
  python3 -m venv --without-pip "$VENV"
fi

if ! "$PY" -m pip --version >/dev/null 2>&1; then
  echo "[setup] bootstrapping pip via get-pip.py ..."
  GETPIP="$REPO_DIR/get-pip.py"
  if [ ! -f "$GETPIP" ]; then
    # Try curl, then wget, then python urllib as a last resort.
    if command -v curl >/dev/null 2>&1; then
      curl -fsSL https://bootstrap.pypa.io/get-pip.py -o "$GETPIP"
    elif command -v wget >/dev/null 2>&1; then
      wget -qO "$GETPIP" https://bootstrap.pypa.io/get-pip.py
    else
      "$PY" -c "import urllib.request; urllib.request.urlretrieve('https://bootstrap.pypa.io/get-pip.py', '$GETPIP')"
    fi
  fi
  "$PY" "$GETPIP"
fi

echo "[setup] installing requirements ..."
"$PY" -m pip install --upgrade pip >/dev/null
"$PY" -m pip install -r "$REPO_DIR/requirements.txt"

echo "[setup] verifying OCR stack imports ..."
"$PY" -c "import pypdfium2, pytesseract, PIL; print('[setup] pypdfium2 + pytesseract + Pillow OK')"
"$PY" -c "import pytesseract; print('[setup] tesseract', pytesseract.get_tesseract_version())" \
  || echo "[setup] WARNING: tesseract binary not found — install with: sudo apt install tesseract-ocr"

echo "[setup] done. Interpreter: $PY"
