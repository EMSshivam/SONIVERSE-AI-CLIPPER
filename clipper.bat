@echo off
rem CLI:  clipper.bat run "D:\Rec\gta.mp4" --face "D:\Rec\face.mov" --mic-track 1 --preset funny_moments --export
cd /d %~dp0
.venv\Scripts\python -m clipper %*
