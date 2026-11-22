#!/usr/bin/env bash
# SONIVERSE AI Clipper - one-click setup for macOS and Linux. Nothing needs to be installed beforehand (no Node.js, Python, npm, sudo):
#   1. uv (small Python installer, checksum-verified)  ->  a private Python 3.12 + .venv in this folder
#   2. the AI libraries (+ NVIDIA CUDA libraries only when an NVIDIA GPU is present)
#   3. portable FFmpeg + the Electron desktop window + the Whisper model / reframing engine for THIS computer
# Safe to run again: it only fetches what is missing.      Usage: scripts/bootstrap.sh [--with-ollama] [--no-electron] [--no-models] [--no-shortcut]
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export UV_LINK_MODE=copy
say() { printf '\n\033[36m=== %s\033[0m\n' "$1"; }
fail() { printf '\n\033[31mERROR: %s\033[0m\n' "$1" >&2; exit 1; }

WITH_OLLAMA=""; NO_ELECTRON=""; NO_MODELS=""; NO_SHORTCUT=""
for a in "$@"; do case "$a" in
  --with-ollama) WITH_OLLAMA="--with-ollama" ;; --no-electron) NO_ELECTRON="--no-electron" ;;
  --no-models) NO_MODELS="--no-models" ;; --no-shortcut) NO_SHORTCUT=1 ;; esac; done

dl() { # dl URL FILE
  if command -v curl >/dev/null 2>&1; then curl -fsSL --retry 3 -A "SONIVERSE-AI-Clipper/1.0" -o "$2" "$1"
  elif command -v wget >/dev/null 2>&1; then wget -q -U "SONIVERSE-AI-Clipper/1.0" -O "$2" "$1"
  else fail "Neither curl nor wget is available - install one of them (it is part of every normal macOS / Linux system)."; fi
}
sha256_of() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }

say "1/4  Python (private copy, nothing is installed system-wide)"
UNAME_S="$(uname -s)"; UNAME_M="$(uname -m)"
case "$UNAME_S" in
  Darwin) OS_T="apple-darwin" ;;
  Linux)  OS_T="unknown-linux-gnu" ;;
  *) fail "Unsupported system: $UNAME_S (use Windows scripts\\bootstrap.ps1 on Windows)." ;;
esac
case "$UNAME_M" in
  arm64|aarch64) ARCH_T="aarch64" ;;
  x86_64|amd64)  ARCH_T="x86_64" ;;
  *) fail "Unsupported CPU: $UNAME_M" ;;
esac
UVDIR="$ROOT/tools/uv"; UV="$UVDIR/uv"
if [ ! -x "$UV" ]; then
  mkdir -p "$UVDIR"; NAME="uv-$ARCH_T-$OS_T.tar.gz"; BASE="https://github.com/astral-sh/uv/releases/latest/download"
  TMP="$(mktemp -d)"
  echo "Downloading uv ($NAME) ..."
  dl "$BASE/$NAME" "$TMP/$NAME" || fail "Could not download uv. Check your internet connection / proxy and run this again."
  if dl "$BASE/$NAME.sha256" "$TMP/sum" 2>/dev/null; then
    WANT="$(cut -d' ' -f1 < "$TMP/sum")"; GOT="$(sha256_of "$TMP/$NAME")"
    [ -z "$WANT" ] || [ "$WANT" = "$GOT" ] || fail "uv download failed its checksum - try again."
    echo "uv: SHA256 checksum OK"
  fi
  tar -xzf "$TMP/$NAME" -C "$TMP"
  F="$(find "$TMP" -name uv -type f | head -n1)"; [ -n "$F" ] || fail "uv was not found in the download."
  cp "$F" "$UV"; chmod +x "$UV"; rm -rf "$TMP"
fi
PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "Creating the Python environment (downloads Python 3.12 once if you do not have it) ..."
  "$UV" venv --seed --python 3.12 "$ROOT/.venv" || fail "Could not create the Python environment."
fi

say "2/4  AI libraries (a few minutes the first time)"
"$UV" pip install --python "$PY" -r "$ROOT/requirements.txt" || fail "Installing the Python packages failed (see above). Check your internet connection and run this again."
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  echo "NVIDIA GPU found: adding the CUDA libraries so Whisper runs on the GPU"
  "$UV" pip install --python "$PY" -r "$ROOT/requirements-cuda.txt" || true
  "$UV" pip install --python "$PY" --upgrade ctranslate2 || true
else
  echo "No NVIDIA GPU found: CPU mode (works everywhere, just slower on long videos; models are chosen to suit this computer)."
fi
mkdir -p input output cache projects assets/models
[ -f config.local.yaml ] || printf '# Your overrides (see config.yaml for every option).\n' > config.local.yaml
MP="assets/models/blaze_face_short_range.tflite"
[ -f "$MP" ] || dl "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite" "$MP" 2>/dev/null || echo "Could not download the face model (face tracking falls back to OpenCV - still works)."

say "3/4  FFmpeg, desktop window, models for this computer"
SHORTCUT_ARG="--shortcut"; [ -z "$NO_SHORTCUT" ] || SHORTCUT_ARG=""
"$PY" scripts/bootstrap_tools.py --root "$ROOT" $NO_ELECTRON $NO_MODELS $WITH_OLLAMA $SHORTCUT_ARG || fail "FFmpeg could not be set up. Install it (macOS: brew install ffmpeg | Linux: sudo apt install ffmpeg) and run this again."

say "4/4  Done"
printf '\033[32mSetup finished.\033[0m\n'
