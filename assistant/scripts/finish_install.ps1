#Requires -Version 5.1
# Finish setup when files already in Desktop\Assistant (no re-download).
param(
    [Parameter(Mandatory = $true)][string]$BotToken,
    [Parameter(Mandatory = $true)][long]$OwnerId,
    [string]$TargetDir = "$env:USERPROFILE\Desktop\Assistant",
    [string]$Model = "qwen/qwen3.5-9b",
    [string]$LmBaseUrl = "http://127.0.0.1:1234/v1",
    [string]$Timezone = "Europe/Moscow"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "python_venv.ps1")

if (-not (Test-Path (Join-Path $TargetDir "main.py"))) {
    throw "main.py not found in $TargetDir - run install_desktop.ps1 first"
}

Set-Location $TargetDir
Write-Host "==> Finish install in $TargetDir" -ForegroundColor Cyan

$venvPy = Find-AssistantVenvPython -WorkDir $TargetDir
Install-AssistantPackages -VenvPy $venvPy -WorkDir $TargetDir

Write-Host "==> Writing .env ..." -ForegroundColor Cyan
@"
TELEGRAM_BOT_TOKEN=$BotToken
TELEGRAM_OWNER_ID=$OwnerId
LM_STUDIO_BASE_URL=$LmBaseUrl
LM_STUDIO_MODEL=$Model
ASSISTANT_DATA_DIR=$TargetDir
TIMEZONE=$Timezone
"@ | Set-Content -Path ".\.env" -Encoding ASCII

Write-Host "==> Database + folders ..." -ForegroundColor Cyan
& $venvPy ".\scripts\init_data.py" --data-dir $TargetDir

& $venvPy -c "from app.bot import run_bot; print('bot imports OK')"

$startBat = Join-Path $TargetDir "START_BOT.bat"
@"
@echo off
cd /d "%~dp0"
title WR Assistant
echo Starting bot... Keep this window open.
call .venv\Scripts\python.exe main.py
echo.
echo Bot stopped.
pause
"@ | Set-Content -Path $startBat -Encoding ASCII

Write-Host ""
Write-Host "DONE. Double-click START_BOT.bat" -ForegroundColor Green
Read-Host "Press Enter to close"
