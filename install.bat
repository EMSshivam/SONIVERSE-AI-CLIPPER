@echo off
rem  Same one-click setup the launcher runs on first start (Python, FFmpeg, desktop window, models) - without opening the app afterwards.
cd /d %~dp0
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\bootstrap.ps1 %*
pause
