#Requires -Version 5.1
param(
    [Parameter(Mandatory = $true)][string]$BotToken,
    [Parameter(Mandatory = $true)][long]$OwnerId,
    [string]$TargetDir = "$env:USERPROFILE\Desktop\Assistant",
    [string]$Model = "qwen/qwen3.5-9b",
    [string]$LmBaseUrl = "http://127.0.0.1:1234/v1",
    [string]$Timezone = "Europe/Moscow",
    [string]$Branch = "cursor/local-assistant-scaffold-d6ce",
    [string]$RepoUrl = "https://github.com/LiDarcy-dot/WR.git"
)

$ErrorActionPreference = "Stop"

function Require-Cmd($name) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "Missing: $name"
    }
}

Require-Cmd git
Require-Cmd py

Write-Host ""
Write-Host "WR Assistant installer" -ForegroundColor Cyan
Write-Host "Target: $TargetDir" -ForegroundColor Cyan
Write-Host ""

$tempClone = Join-Path $env:TEMP ("WR-assistant-" + [guid]::NewGuid().ToString("N"))
Write-Host "==> Downloading latest code from GitHub..." -ForegroundColor Cyan
git clone --branch $Branch --depth 1 $RepoUrl $tempClone
$copyFrom = Join-Path $tempClone "assistant"
if (-not (Test-Path (Join-Path $copyFrom "main.py"))) {
    throw "assistant/main.py not found in repo"
}

New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null

Write-Host "==> Copying files to Desktop\Assistant ..." -ForegroundColor Cyan
Get-ChildItem -Path $copyFrom -Force | Where-Object {
    $_.Name -notin @(".venv", "__pycache__", ".pytest_cache", ".env")
} | ForEach-Object {
    $dest = Join-Path $TargetDir $_.Name
    if ($_.PSIsContainer) {
        if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
        Copy-Item -Path $_.FullName -Destination $dest -Recurse -Force
    } else {
        Copy-Item -Path $_.FullName -Destination $dest -Force
    }
}

Remove-Item -Recurse -Force $tempClone -ErrorAction SilentlyContinue

Set-Location $TargetDir

Write-Host "==> Python venv + packages ..." -ForegroundColor Cyan
$venvPy = Join-Path $TargetDir ".venv\Scripts\python.exe"
$created = $false
foreach ($ver in @("3.12", "3.11", "3")) {
    Write-Host "Trying Python $ver ..." -ForegroundColor DarkYellow
    if (Test-Path ".venv") { Remove-Item -Recurse -Force ".venv" }
    & py "-$ver" -m venv .venv 2>$null
    if (Test-Path $venvPy) {
        Write-Host "OK: Python $ver" -ForegroundColor Green
        $created = $true
        break
    }
}
if (-not $created) {
    throw "Could not create venv. Install Python 3.12 from https://www.python.org/downloads/"
}

& $venvPy -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
& $venvPy -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed - try Python 3.12" }
& $venvPy -c "import telegram; print('telegram OK')"
if ($LASTEXITCODE -ne 0) { throw "telegram not installed" }

Write-Host "==> Config .env ..." -ForegroundColor Cyan
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
if ($LASTEXITCODE -ne 0) { throw "init_data failed" }

& $venvPy -c "from app.bot import run_bot; print('bot imports OK')"
if ($LASTEXITCODE -ne 0) { throw "bot import failed" }

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
Write-Host "========================================" -ForegroundColor Green
Write-Host " DONE: $TargetDir" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next:"
Write-Host "  1) LM Studio server on http://127.0.0.1:1234 (model $Model)"
Write-Host "  2) Double-click START_BOT.bat on Desktop\Assistant"
Write-Host "  3) Telegram -> /start -> /status"
Write-Host ""
Read-Host "Press Enter to close"
