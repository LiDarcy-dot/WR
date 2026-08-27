#Requires -Version 5.1
# Clean reinstall of WR Assistant into Desktop\Assistant
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
        throw "Missing command: $name"
    }
}

Require-Cmd git
if (-not (Get-Command py -ErrorAction SilentlyContinue) -and -not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Missing Python. Install from https://www.python.org/downloads/ and check Add to PATH"
}

Write-Host ""
Write-Host "CLEAN REINSTALL -> $TargetDir" -ForegroundColor Cyan
Write-Host ""

# Backup existing .env if present
$oldEnv = $null
$envPath = Join-Path $TargetDir ".env"
if (Test-Path $envPath) {
    $oldEnv = Get-Content $envPath -Raw
    Write-Host "Found existing .env (will rewrite with new token params)" -ForegroundColor Yellow
}

# Wipe target (keep parent Desktop)
if (Test-Path $TargetDir) {
    Write-Host "==> Removing old Assistant folder..." -ForegroundColor Yellow
    # stop if python from that venv is somehow locked - try remove
    Remove-Item -Recurse -Force $TargetDir -ErrorAction Stop
}

New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null

$tempClone = Join-Path $env:TEMP ("WR-clean-" + [guid]::NewGuid().ToString("N"))
Write-Host "==> Downloading code from GitHub..." -ForegroundColor Cyan
git clone --branch $Branch --depth 1 $RepoUrl $tempClone
$copyFrom = Join-Path $tempClone "assistant"
if (-not (Test-Path (Join-Path $copyFrom "main.py"))) {
    throw "assistant/main.py missing in clone"
}

Write-Host "==> Copying files..." -ForegroundColor Cyan
Copy-Item -Path (Join-Path $copyFrom "*") -Destination $TargetDir -Recurse -Force
# also copy START_BOT if present
Remove-Item -Recurse -Force $tempClone -ErrorAction SilentlyContinue

Set-Location $TargetDir

# Create venv with any available Python
Write-Host "==> Creating venv..." -ForegroundColor Cyan
$venvPy = Join-Path $TargetDir ".venv\Scripts\python.exe"
$created = $false
$attempts = @(
    @{ L = "py -3.14"; E = "py"; A = @("-3.14", "-m", "venv", ".venv") },
    @{ L = "py -3.13"; E = "py"; A = @("-3.13", "-m", "venv", ".venv") },
    @{ L = "py -3.12"; E = "py"; A = @("-3.12", "-m", "venv", ".venv") },
    @{ L = "py -3.11"; E = "py"; A = @("-3.11", "-m", "venv", ".venv") },
    @{ L = "py -3"; E = "py"; A = @("-3", "-m", "venv", ".venv") },
    @{ L = "python"; E = "python"; A = @("-m", "venv", ".venv") }
)

foreach ($a in $attempts) {
    if (-not (Get-Command $a.E -ErrorAction SilentlyContinue)) { continue }
    Write-Host "Trying $($a.L) ..." -ForegroundColor DarkYellow
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $a.E @($a.A) 2>&1 | Out-Null } catch {}
    $ErrorActionPreference = $prev
    if (Test-Path $venvPy) {
        Write-Host ("OK: " + (& $venvPy --version)) -ForegroundColor Green
        $created = $true
        break
    }
}
if (-not $created) {
    throw "Could not create venv. Install Python 3.12+ with Add to PATH, reopen PowerShell."
}

Write-Host "==> Installing packages (this can take a few minutes)..." -ForegroundColor Cyan
& $venvPy -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }

& $venvPy -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "pip with pinned versions failed, trying without pins..." -ForegroundColor Yellow
    & $venvPy -m pip install "python-telegram-bot[job-queue]" httpx pydantic pydantic-settings python-dateutil cryptography
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
}

Write-Host "==> Verify telegram import..." -ForegroundColor Cyan
& $venvPy -c "import telegram; print('telegram', telegram.__version__)"
if ($LASTEXITCODE -ne 0) { throw "telegram still missing" }

Write-Host "==> Writing .env ..." -ForegroundColor Cyan
@"
TELEGRAM_BOT_TOKEN=$BotToken
TELEGRAM_OWNER_ID=$OwnerId
LM_STUDIO_BASE_URL=$LmBaseUrl
LM_STUDIO_MODEL=$Model
ASSISTANT_DATA_DIR=$TargetDir
TIMEZONE=$Timezone
"@ | Set-Content -Path ".\.env" -Encoding ASCII

Write-Host "==> Init DB + folders ..." -ForegroundColor Cyan
& $venvPy ".\scripts\init_data.py" --data-dir $TargetDir
if ($LASTEXITCODE -ne 0) { throw "init_data failed" }

& $venvPy -c "from app.bot import run_bot; print('bot imports OK')"
if ($LASTEXITCODE -ne 0) { throw "bot import failed" }

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
Write-Host "========================================" -ForegroundColor Green
Write-Host " CLEAN INSTALL OK: $TargetDir" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Check files:"
Get-ChildItem $TargetDir -Name | Select-Object -First 30
Write-Host ""
Write-Host "Next: double-click START_BOT.bat"
Write-Host "Then Telegram: /start and /status"
Write-Host ""
Read-Host "Press Enter to close"
