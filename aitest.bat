@echo off
cd /d %~dp0
.venv\Scripts\python tests\test_ai_chain.py
pause
