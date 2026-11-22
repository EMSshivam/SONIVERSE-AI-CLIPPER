#!/usr/bin/env bash
# Shared by "SONIVERSE AI Clipper.command" (macOS) and "SONIVERSE AI Clipper.sh" (Linux): set up on first start, then open the app.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
unset ELECTRON_RUN_AS_NODE      # if it leaks in (e.g. from an IDE terminal) Electron would behave like plain Node and never open a window
case "$(uname -s)" in
  Darwin) EL="$ROOT/electron/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron"; FLAGS="" ;;
  *)      EL="$ROOT/electron/node_modules/electron/dist/electron"; FLAGS="--no-sandbox" ;;   # unpacked Electron has no SUID sandbox helper; the app only loads its own local page
esac
if [ ! -x .venv/bin/python ] || [ ! -x "$EL" ]; then
  echo
  echo " ================================================================"
  echo "  First start: setting up SONIVERSE AI Clipper for this computer"
  echo "  (Python, FFmpeg, the desktop window, AI models)."
  echo "  This takes a few minutes and needs internet. Do not close this window."
  echo " ================================================================"
  bash "$ROOT/scripts/bootstrap.sh" || { echo; echo " Setup did not finish - read the message above. Run this again to retry."; read -r -p " Press Enter to close..." _; exit 1; }
fi
[ "$SV_NO_LAUNCH" = "1" ] && exit 0
if [ -x "$EL" ]; then
  nohup "$EL" $FLAGS "$ROOT/electron" >/dev/null 2>&1 &
  disown 2>/dev/null || true
  exit 0
fi
echo "Desktop window not available - opening the browser dashboard instead (close this window to stop)."
exec .venv/bin/python -m clipper serve
