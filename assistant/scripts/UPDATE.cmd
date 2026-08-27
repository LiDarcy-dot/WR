@echo off
REM Double-click this file (not force_update.ps1) to update the assistant.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0force_update.ps1"
if errorlevel 1 (
  echo UPDATE FAILED
  pause
  exit /b 1
)
