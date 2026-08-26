#Requires -Version 5.1
<#
  Full install into Desktop\Assistant (code + data in one folder).
  Run in PowerShell:

  cd $env:USERPROFILE\Desktop
  git clone https://github.com/LiDarcy-dot/WR.git WR-install -b cursor/local-assistant-scaffold-d6ce
  .\WR-install\assistant\scripts\install_desktop.ps1 -BotToken "YOUR_TOKEN" -OwnerId YOUR_ID

  Or if WR already on Desktop:
  cd $env:USERPROFILE\Desktop\WR\assistant
  .\scripts\install_desktop.ps1 -BotToken "..." -OwnerId ...
#>
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

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$sourceAssistant = Split-Path -Parent $scriptDir

Write-Host "==> Target folder: $TargetDir" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null

# If run from existing clone, copy from there. Else clone fresh to temp.
$tempClone = $null
if (Test-Path (Join-Path $sourceAssistant "main.py")) {
    Write-Host "==> Using local source: $sourceAssistant" -ForegroundColor Cyan
    $copyFrom = $sourceAssistant
} else {
    $tempClone = Join-Path $env:TEMP "WR-assistant-clone"
    if (Test-Path $tempClone) { Remove-Item -Recurse -Force $tempClone }
    Write-Host "==> Cloning repo..." -ForegroundColor Cyan
    git clone --branch $Branch --depth 1 $RepoUrl $tempClone
    $copyFrom = Join-Path $tempClone "assistant"
}

Write-Host "==> Copying assistant files..." -ForegroundColor Cyan
$exclude = @(".venv", "__pycache__", ".env", ".pytest_cache", "*.pyc")
Get-ChildItem -Path $copyFrom -Force | Where-Object {
    $_.Name -notin @(".venv", "__pycache__", ".pytest_cache")
} | ForEach-Object {
    $dest = Join-Path $TargetDir $_.Name
    if ($_.PSIsContainer) {
        if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
        Copy-Item -Path $_.FullName -Destination $dest -Recurse -Force
    } else {
        Copy-Item -Path $_.FullName -Destination $dest -Force
    }
}

Set-Location $TargetDir

Write-Host "==> Creating Python venv..." -ForegroundColor Cyan
$venvPy = Join-Path $TargetDir ".venv\Scripts\python.exe"
$created = $false
foreach ($ver in @("3.12", "3.11", "3")) {
    Write-Host "Trying Python $ver ..." -ForegroundColor DarkYellow
    if (Test-Path ".venv") { Remove-Item -Recurse -Force ".venv" }
    & py "-$ver" -m venv .venv
    if (Test-Path $venvPy) {
        Write-Host "OK: Python $ver" -ForegroundColor Green
        $created = $true
        break
    }
}
if (-not $created) { throw "Could not create venv. Install Python 3.12." }

& $venvPy -m pip install --upgrade pip
& $venvPy -m pip install -r requirements.txt
& $venvPy -c "import telegram; print('telegram OK')"
if ($LASTEXITCODE -ne 0) { throw "telegram module missing" }

Write-Host "==> Writing .env ..." -ForegroundColor Cyan
@"
TELEGRAM_BOT_TOKEN=$BotToken
TELEGRAM_OWNER_ID=$OwnerId
LM_STUDIO_BASE_URL=$LmBaseUrl
LM_STUDIO_MODEL=$Model
ASSISTANT_DATA_DIR=$TargetDir
TIMEZONE=$Timezone
"@ | Set-Content -Path ".\.env" -Encoding ASCII

Write-Host "==> Init database + folders ..." -ForegroundColor Cyan
& $venvPy ".\scripts\init_data.py" --data-dir $TargetDir

$startBat = Join-Path $TargetDir "START_BOT.bat"
@"
@echo off
cd /d "%~dp0"
echo Starting WR Assistant bot...
".venv\Scripts\python.exe" main.py
pause
"@ | Set-Content -Path $startBat -Encoding ASCII

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "INSTALLED TO: $TargetDir" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "1) Keep LM Studio server on http://127.0.0.1:1234"
Write-Host "2) Double-click START_BOT.bat  OR run:"
Write-Host "   cd `"$TargetDir`""
Write-Host "   .\.venv\Scripts\python.exe main.py"
Write-Host ""
Write-Host "3) Telegram: /start  then  /status"
Write-Host ""

if ($tempClone -and (Test-Path $tempClone)) {
    Remove-Item -Recurse -Force $tempClone -ErrorAction SilentlyContinue
}

Read-Host "Press Enter to close"
