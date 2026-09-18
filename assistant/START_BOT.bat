@echo off
cd /d "%~dp0"
title WR Assistant
if not exist "logs" mkdir logs

REM Watchdog: if python exits (update/crash), start again unless .wr_stop exists.
set WR_WATCHDOG=1
set WR_INSTALL_ROOT=%~dp0

echo Starting bot + web panel http://127.0.0.1:8765
echo Watchdog ON — window can stay open; bot auto-restarts after exit/crash.
echo To stop permanently: create file .wr_stop in this folder, or close this window.
echo.

:loop
if exist "%~dp0.wr_stop" (
  echo .wr_stop found — not restarting.
  goto end
)

echo [%date% %time%] pip/check + start >> "logs\watchdog.log"

REM Auto-wire Telegram SOCKS into .env (no notepad). Safe to run every loop.
if exist "%~dp0scripts\ensure_telegram_proxy.ps1" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\ensure_telegram_proxy.ps1" >> "logs\watchdog.log" 2>&1
)

call .venv\Scripts\python.exe -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo [%date% %time%] pip failed >> "logs\watchdog.log"
  echo pip failed — retry in 10s
  timeout /t 10 /nobreak >nul
  goto loop
)

call .venv\Scripts\python.exe main.py
set EXITCODE=%ERRORLEVEL%
echo [%date% %time%] bot exited code=%EXITCODE% >> "logs\watchdog.log"
echo.
echo Bot exited ^(code %EXITCODE%^). Restarting in 5s...
timeout /t 5 /nobreak >nul
goto loop

:end
echo Bot stopped.
pause
