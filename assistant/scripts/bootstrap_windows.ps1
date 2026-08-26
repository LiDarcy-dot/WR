#Requires -Version 5.1
<#
.SYNOPSIS
  Клонирует WR (если нужно), ставит зависимости, пишет .env, инициализирует папку данных.

.EXAMPLE
  cd $env:USERPROFILE\Desktop
  # после clone:
  cd WR\assistant
  .\scripts\bootstrap_windows.ps1 `
    -BotToken "ТВОЙ_ТОКЕН" `
    -OwnerId 489485288 `
    -DataDir "$env:USERPROFILE\Desktop\Assistant" `
    -Model "qwen/qwen3.5-9b"
#>
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
        throw "Не найдено: $name. Установи и перезапусти PowerShell."
    }
}

Write-Host "==> Проверка Git и Python..." -ForegroundColor Cyan
Require-Cmd git
Require-Cmd py

if (-not (Test-Path $InstallRoot)) {
    Write-Host "==> Клонирую репозиторий в $InstallRoot ..." -ForegroundColor Cyan
    git clone $RepoUrl $InstallRoot
}

Set-Location $InstallRoot
git fetch origin
git checkout $Branch
git pull origin $Branch

$assistant = Join-Path $InstallRoot "assistant"
Set-Location $assistant

Write-Host "==> venv + зависимости..." -ForegroundColor Cyan
py -3 -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\pip.exe" install -r requirements.txt

Write-Host "==> Пишу .env (локально, не в git)..." -ForegroundColor Cyan
@"
TELEGRAM_BOT_TOKEN=$BotToken
TELEGRAM_OWNER_ID=$OwnerId
LM_STUDIO_BASE_URL=$LmBaseUrl
LM_STUDIO_MODEL=$Model
ASSISTANT_DATA_DIR=$DataDir
TIMEZONE=$Timezone
"@ | Set-Content -Path ".\.env" -Encoding UTF8

New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
Write-Host "==> Инициализация папки данных и БД..." -ForegroundColor Cyan
& ".\.venv\Scripts\python.exe" ".\scripts\init_data.py" --data-dir $DataDir

Write-Host ""
Write-Host "Готово." -ForegroundColor Green
Write-Host "1) В LM Studio включи Local Server (порт 1234), загрузи модель $Model"
Write-Host "2) VPN для Telegram на ПК желателен"
Write-Host "3) Запуск бота:"
Write-Host "   cd $assistant"
Write-Host "   .\.venv\Scripts\Activate.ps1"
Write-Host "   python main.py"
Write-Host ""
Write-Host "Или сразу:" -ForegroundColor Yellow
Write-Host "   .\.venv\Scripts\python.exe main.py"
