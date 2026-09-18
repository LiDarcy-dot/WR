#Requires -Version 5.1
# Finish after packages already installed (no wipe, no re-download)
param(
    [string]$TargetDir = "$env:USERPROFILE\Desktop\Assistant",
    [string]$BotToken = "",
    [long]$OwnerId = 0,
    [string]$Model = "qwen/qwen3.5-9b",
    [string]$LmBaseUrl = "http://127.0.0.1:1234/v1",
    [string]$Timezone = "Europe/Moscow"
)

$ErrorActionPreference = "Stop"
Set-Location $TargetDir

$venvPy = Join-Path $TargetDir ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { throw "venv missing at $venvPy" }
if (-not (Test-Path ".\main.py")) { throw "main.py missing" }

& $venvPy -c "import telegram; print('telegram OK')"
if ($LASTEXITCODE -ne 0) { throw "telegram missing - run clean_reinstall" }

if ($BotToken -and $OwnerId -gt 0) {
    Write-Host "==> Writing .env ..." -ForegroundColor Cyan
@"
TELEGRAM_BOT_TOKEN=$BotToken
TELEGRAM_OWNER_ID=$OwnerId
LM_STUDIO_BASE_URL=$LmBaseUrl
LM_STUDIO_MODEL=$Model
ASSISTANT_DATA_DIR=$TargetDir
TIMEZONE=$Timezone
"@ | Set-Content -Path ".\.env" -Encoding ASCII
} elseif (-not (Test-Path ".\.env")) {
    throw "No .env and no -BotToken/-OwnerId given"
} else {
    Write-Host "OK: keeping existing .env" -ForegroundColor Green
}

$env:PYTHONPATH = $TargetDir
Write-Host "==> Init DB ..." -ForegroundColor Cyan
& $venvPy ".\scripts\init_data.py" --data-dir $TargetDir
if ($LASTEXITCODE -ne 0) {
    # inline fallback
    & $venvPy -c @"
from pathlib import Path
import sys
sys.path.insert(0, r'$TargetDir')
from app.db import init_db
from app.storage_layout import ensure_data_layout
root = Path(r'$TargetDir')
ensure_data_layout(root)
init_db(root / 'db' / 'assistant.sqlite3')
print('OK inline init')
"@
}

& $venvPy -c "from app.bot import run_bot; print('bot imports OK')"

@"
@echo off
cd /d "%~dp0"
title WR Assistant
echo Starting bot... Keep this window open.
call .venv\Scripts\python.exe main.py
echo.
echo Bot stopped.
pause
"@ | Set-Content -Path ".\START_BOT.bat" -Encoding ASCII

Write-Host ""
Write-Host "DONE. Run START_BOT.bat" -ForegroundColor Green
Get-ChildItem $TargetDir -Name | Select-Object -First 25
Read-Host "Press Enter to close"
