#Requires -Version 5.1
# Reinstall deps and verify bot imports.
# Run from assistant folder:
#   .\scripts\repair_windows.ps1
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $here

function Test-PythonImport([string]$pyExe, [string]$module) {
    & $pyExe -c "import $module" 2>$null
    return ($LASTEXITCODE -eq 0)
}

Write-Host "==> Folder: $here" -ForegroundColor Cyan
$venvPy = Join-Path $here ".venv\Scripts\python.exe"
$DataDir = Join-Path $env:USERPROFILE "Desktop\Assistant"

if (Test-Path $venvPy) {
    Write-Host "==> Upgrading pip and installing requirements..." -ForegroundColor Cyan
    & $venvPy -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
    & $venvPy -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "pip install requirements failed" }
    if (Test-PythonImport $venvPy "telegram") {
        Write-Host "OK: telegram module found." -ForegroundColor Green
    } else {
        Write-Host "venv exists but telegram missing. Recreating venv..." -ForegroundColor Yellow
        Remove-Item -Recurse -Force .venv
        $venvPy = Join-Path $here ".venv\Scripts\python.exe"
    }
}

if (-not (Test-Path $venvPy)) {
    Write-Host "==> Creating new venv..." -ForegroundColor Cyan
    $created = $false
    foreach ($ver in @("3.12", "3.11", "3")) {
        Write-Host "Trying Python $ver ..." -ForegroundColor DarkYellow
        & py "-$ver" -m venv .venv
        if (Test-Path $venvPy) {
            Write-Host "Using Python $ver" -ForegroundColor Green
            $created = $true
            break
        }
    }
    if (-not $created) {
        throw "Could not create venv. Install Python 3.12 from python.org"
    }
    & $venvPy -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
    & $venvPy -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "pip install requirements failed" }
    if (-not (Test-PythonImport $venvPy "telegram")) {
        throw "telegram still missing after pip install. Paste full pip output."
    }
}

if (-not (Test-Path ".\.env")) {
    Write-Host "WARN: .env missing - run bootstrap next" -ForegroundColor Yellow
} else {
    Write-Host "OK: .env found" -ForegroundColor Green
}

if (-not (Test-Path $DataDir)) {
    Write-Host "==> Creating data folder..." -ForegroundColor Cyan
    New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
}
& $venvPy ".\scripts\init_data.py" --data-dir $DataDir

Write-Host ""
Write-Host "Checking bot imports..." -ForegroundColor Cyan
& $venvPy -c "from app.bot import run_bot; print('imports OK')"
if ($LASTEXITCODE -ne 0) { throw "bot import failed" }

Write-Host ""
Write-Host "DONE. Start bot with:" -ForegroundColor Green
Write-Host "  .\.venv\Scripts\python.exe main.py"
Write-Host ""
Read-Host "Press Enter to close"
