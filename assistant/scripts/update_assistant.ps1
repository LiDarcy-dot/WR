#Requires -Version 5.1
# Update code in Desktop\Assistant without wiping DB / venv
param(
    [string]$TargetDir = "$env:USERPROFILE\Desktop\Assistant",
    [string]$Branch = "cursor/local-assistant-scaffold-d6ce",
    [string]$RepoUrl = "https://github.com/LiDarcy-dot/WR.git"
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path (Join-Path $TargetDir "main.py"))) {
    throw "Assistant not found at $TargetDir"
}

$temp = Join-Path $env:TEMP ("WR-upd-" + [guid]::NewGuid().ToString("N"))
Write-Host "==> Downloading update..." -ForegroundColor Cyan
git clone --branch $Branch --depth 1 $RepoUrl $temp
$src = Join-Path $temp "assistant"

# Preserve local secrets and data
$preserve = @(".env", ".venv", "db", "backups", "inbox", "documents", "people", "meters", "reminders", "mail_cache", "gosuslugi_cache", "profiles", "START_BOT.bat")

Write-Host "==> Updating Python files..." -ForegroundColor Cyan
Copy-Item (Join-Path $src "app") (Join-Path $TargetDir "app") -Recurse -Force
Copy-Item (Join-Path $src "main.py") (Join-Path $TargetDir "main.py") -Force
Copy-Item (Join-Path $src "requirements.txt") (Join-Path $TargetDir "requirements.txt") -Force
if (Test-Path (Join-Path $src "scripts")) {
    Copy-Item (Join-Path $src "scripts") (Join-Path $TargetDir "scripts") -Recurse -Force
}
if (Test-Path (Join-Path $src "START_BOT.bat")) {
    Copy-Item (Join-Path $src "START_BOT.bat") (Join-Path $TargetDir "START_BOT.bat") -Force
}

Remove-Item -Recurse -Force $temp -ErrorAction SilentlyContinue

$venvPy = Join-Path $TargetDir ".venv\Scripts\python.exe"
if (Test-Path $venvPy) {
    Write-Host "==> Checking imports..." -ForegroundColor Cyan
    & $venvPy -c "from app.bot import run_bot; from app.intent import classify_intent; print('OK', classify_intent('Да').kind)"
}

Write-Host ""
Write-Host "UPDATE OK. Restart bot: close window, run START_BOT.bat" -ForegroundColor Green
Read-Host "Press Enter"
