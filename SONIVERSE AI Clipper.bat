@echo off
rem  SONIVERSE AI Clipper - just double-click this file.
rem  First start: it sets everything up by itself (Python, FFmpeg, the desktop window, AI models). Needs internet once; no admin rights, no Node.js.
rem  Every later start: the app opens straight away.
setlocal
set "ELECTRON_RUN_AS_NODE="
cd /d "%~dp0"
title SONIVERSE AI Clipper

set "EL=%~dp0electron\node_modules\electron\dist\electron.exe"
if not exist ".venv\Scripts\python.exe" goto :setup
if not exist "%EL%" goto :setup
goto :run

:setup
echo.
echo  ================================================================
echo   First start: setting up SONIVERSE AI Clipper for this computer
echo   (Python, FFmpeg, the desktop window, AI models).
echo   This takes a few minutes and needs internet. Do not close this window.
echo  ================================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap.ps1"
if errorlevel 1 (
  echo.
  echo  Setup did not finish - read the message above. You can run this file again to retry.
  pause
  exit /b 1
)

:run
if /I "%SV_NO_LAUNCH%"=="1" exit /b 0
if exist "%EL%" (
  start "" "%EL%" "%~dp0electron"
  exit /b 0
)
echo Desktop window not available - opening the browser dashboard instead (close this window to stop).
title SONIVERSE AI Clipper (close this window to stop)
.venv\Scripts\python -m clipper serve
pause
