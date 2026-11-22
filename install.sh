#!/usr/bin/env bash
# macOS / Linux installer: the same one-click setup the launcher runs on first start (without opening the app afterwards).
# Needs nothing installed beforehand (no Node.js, Python, npm or sudo). Flags: --with-ollama --no-electron --no-models --no-shortcut
cd "$(dirname "$0")" && exec bash scripts/bootstrap.sh "$@"
