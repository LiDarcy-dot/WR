@echo off
cd /d "%~dp0"
title WR Assistant
echo Starting bot + web panel http://127.0.0.1:8765
echo Keep this window open.
call .venv\Scripts\python.exe -m pip install -q -r requirements.txt
call .venv\Scripts\python.exe main.py
echo.
echo Bot stopped.
pause
