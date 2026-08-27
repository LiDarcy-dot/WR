@echo off
cd /d "%~dp0"
title WR Assistant
echo Starting bot... Keep this window open.
call .venv\Scripts\python.exe main.py
echo.
echo Bot stopped.
pause
