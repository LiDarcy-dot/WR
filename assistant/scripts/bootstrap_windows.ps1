#Requires -Version 5.1
param(
    [Parameter(Mandatory = $true)][string]$BotToken,
    [Parameter(Mandatory = $true)][long]$OwnerId,
    [string]$DataDir = "$env:USERPROFILE\Desktop\Assistant",
    [string]$Model = "qwen/qwen3.5-9b",
    [string]$LmBaseUrl = "http://127.0.0.1:1234/v1",
    [string]$Timezone = "Europe/Moscow",
    [string]$RepoUrl = "https://github.com/LiDarcy-dot/WR.git",
    [string]$Branch = "cursor/local-assistant-scaffold-d6ce",
    [string]$InstallRoot = "$env:USERPROFILE\Desktop\WR"
)

$ErrorActionPreference = "Stop"

function Require-Cmd($name) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "Missing command: $name"
    }
}

Write-Host "==> Checking Git and Python..." -ForegroundColor Cyan
Require-Cmd git
Require-Cmd py

if (-not (Test-Path $InstallRoot)) {
    Write-Host "==> Cloning repo to $InstallRoot ..." -ForegroundColor Cyan
    git clone $RepoUrl $InstallRoot
}

Set-Location $InstallRoot
git fetch origin
git checkout $Branch
git pull origin $Branch

$assistant = Join-Path $InstallRoot "assistant"
Set-Location $assistant

Write-Host "==> venv + dependencies..." -ForegroundColor Cyan
$venvPy = Join-Path $assistant ".venv\Scripts\python.exe"
$pythonOk = $false
foreach ($ver in @("3.12", "3.11", "3")) {
    Write-Host "Trying Python $ver ..." -ForegroundColor DarkYellow
    & py "-$ver" -m venv .venv
    if (Test-Path $venvPy) {
        Write-Host "venv on Python $ver" -ForegroundColor Green
        $pythonOk = $true
        break
    }
}
if (-not $pythonOk) {
    throw "Could not create venv. Install Python 3.12 from python.org"
}

& $venvPy -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
& $venvPy -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
& $venvPy -c "import telegram; print('telegram OK')"
if ($LASTEXITCODE -ne 0) {
    throw "python-telegram-bot not installed. Run .\scripts\repair_windows.ps1"
}

Write-Host "==> Writing .env (local only)..." -ForegroundColor Cyan
@"
TELEGRAM_BOT_TOKEN=$BotToken
TELEGRAM_OWNER_ID=$OwnerId
LM_STUDIO_BASE_URL=$LmBaseUrl
LM_STUDIO_MODEL=$Model
ASSISTANT_DATA_DIR=$DataDir
TIMEZONE=$Timezone
"@ | Set-Content -Path ".\.env" -Encoding ASCII

New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
Write-Host "==> Init data folder + DB..." -ForegroundColor Cyan
& $venvPy ".\scripts\init_data.py" --data-dir $DataDir
if ($LASTEXITCODE -ne 0) { throw "init_data failed" }

Write-Host ""
Write-Host "DONE." -ForegroundColor Green
Write-Host "1) LM Studio Local Server on port 1234, model $Model"
Write-Host "2) VPN for Telegram recommended"
Write-Host "3) Start:"
Write-Host "   cd $assistant"
Write-Host "   .\.venv\Scripts\python.exe main.py"
Write-Host ""
Read-Host "Press Enter to close"
