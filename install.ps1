# SONIVERSE AI Clipper installer (PowerShell). Kept for people who prefer a terminal; double-clicking "SONIVERSE AI Clipper.bat" does the same on first start.
# Needs nothing installed beforehand (no Node.js, Python, FFmpeg, winget or admin rights). See scripts\bootstrap.ps1 for the steps.
param([switch]$WithOllama, [switch]$NoElectron, [switch]$NoModels, [switch]$NoShortcut)
& (Join-Path $PSScriptRoot "scripts\bootstrap.ps1") -Root $PSScriptRoot -WithOllama:$WithOllama -NoElectron:$NoElectron -NoModels:$NoModels -NoShortcut:$NoShortcut
exit $LASTEXITCODE
