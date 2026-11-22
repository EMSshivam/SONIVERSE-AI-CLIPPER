#!/usr/bin/env bash
# Start SONIVERSE AI Clipper on macOS / Linux.   ./run.sh [desktop|web|doctor|cli ...]      (default: desktop)
cd "$(dirname "$0")"
MODE="${1:-desktop}"
if [ ! -x .venv/bin/python ]; then exec bash scripts/launch.sh; fi        # not set up yet: the launcher does it for you
case "$MODE" in
  desktop) exec bash scripts/launch.sh ;;
  doctor)  exec .venv/bin/python -m clipper doctor ;;
  cli)     shift; exec .venv/bin/python -m clipper "$@" ;;
  web)     exec .venv/bin/python -m clipper serve ;;
  *)       echo "usage: ./run.sh [desktop|web|doctor|cli ...]"; exit 1 ;;
esac
