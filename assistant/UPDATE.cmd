@echo off
REM Double-click this file to update the assistant (uses git, NOT irm/raw.github).
cd /d "%~dp0"
if exist "%~dp0scripts\force_update.ps1" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\force_update.ps1"
) else if exist "%~dp0force_update.ps1" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0force_update.ps1"
) else (
  echo force_update.ps1 not found. Run the PowerShell block from UPDATE_NOW.txt
  pause
  exit /b 1
)
if errorlevel 1 (
  echo UPDATE FAILED
  pause
  exit /b 1
)
