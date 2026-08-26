#Requires -Version 5.1
<#
  Переустановка зависимостей + проверка, что бот может стартовать.
  Запуск из папки assistant:
    .\scripts\repair_windows.ps1
#>
param(
    [string]$DataDir = "$env:USERPROFILE\Desktop\Assistant",
    [string]$PythonLauncher = "py -3.12"
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $here

function Test-PythonImport($pyExe, $module) {
    & $pyExe -c "import $module" 2>$null
    return ($LASTEXITCODE -eq 0)
}

Write-Host "==> Папка: $here" -ForegroundColor Cyan

# Пробуем существующий venv
$venvPy = Join-Path $here ".venv\Scripts\python.exe"
if (Test-Path $venvPy) {
    Write-Host "==> Обновляю pip и ставлю requirements в существующий venv..." -ForegroundColor Cyan
    & $venvPy -m pip install --upgrade pip
    & $venvPy -m pip install -r requirements.txt
    if (Test-PythonImport $venvPy "telegram") {
        Write-Host "OK: модуль telegram найден." -ForegroundColor Green
    } else {
        Write-Host "venv есть, но telegram не установился. Пересоздаю venv..." -ForegroundColor Yellow
        Remove-Item -Recurse -Force .venv
        $venvPy = $null
    }
}

if (-not (Test-Path $venvPy)) {
    Write-Host "==> Создаю новый venv..." -ForegroundColor Cyan
    $created = $false
    foreach ($ver in @("3.12", "3.11", "3")) {
        try {
            & py "-$ver" -m venv .venv
            if (Test-Path $venvPy) {
                Write-Host "Использую Python $ver" -ForegroundColor Green
                $created = $true
                break
            }
        } catch {
            Write-Host "Python $ver недоступен, пробую дальше..." -ForegroundColor DarkYellow
        }
    }
    if (-not $created) {
        throw "Не удалось создать venv. Установи Python 3.12 с python.org"
    }
    & $venvPy -m pip install --upgrade pip
    & $venvPy -m pip install -r requirements.txt
    if (-not (Test-PythonImport $venvPy "telegram")) {
        throw "pip install прошёл, но import telegram не работает. Пришли вывод pip install."
    }
}

if (-not (Test-Path ".\.env")) {
    Write-Host "WARN: нет файла .env — запусти bootstrap_windows.ps1 или создай .env вручную" -ForegroundColor Yellow
} else {
    Write-Host "OK: .env найден" -ForegroundColor Green
}

if (Test-Path $DataDir) {
    Write-Host "OK: папка данных $DataDir" -ForegroundColor Green
} else {
    Write-Host "==> Создаю папку данных..." -ForegroundColor Cyan
    New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
    & $venvPy ".\scripts\init_data.py" --data-dir $DataDir
}

Write-Host ""
Write-Host "Проверка импортов бота..." -ForegroundColor Cyan
& $venvPy -c "from app.bot import run_bot; print('imports OK')"

Write-Host ""
Write-Host "Готово. Запуск:" -ForegroundColor Green
Write-Host "  cd $here"
Write-Host "  .\.venv\Scripts\python.exe main.py"
Write-Host ""
Read-Host "Нажми Enter чтобы закрыть окно"
