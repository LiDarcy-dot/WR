#Requires -Version 5.1
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "python_venv.ps1")

$here = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $here

Write-Host "==> Folder: $here" -ForegroundColor Cyan
$DataDir = $here

if (Test-Path (Join-Path $here ".venv\Scripts\python.exe")) {
    $existing = Join-Path $here ".venv\Scripts\python.exe"
    & $existing -c "import telegram" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "OK: venv already has telegram" -ForegroundColor Green
        $venvPy = $existing
    } else {
        Remove-Item -Recurse -Force .venv
        $venvPy = $null
    }
} else {
    $venvPy = $null
}

if (-not $venvPy) {
    $venvPy = Find-AssistantVenvPython -WorkDir $here
    Install-AssistantPackages -VenvPy $venvPy -WorkDir $here
}

& $venvPy ".\scripts\init_data.py" --data-dir $DataDir
& $venvPy -c "from app.bot import run_bot; print('imports OK')"

Write-Host ""
Write-Host "DONE. Run: .\.venv\Scripts\python.exe main.py" -ForegroundColor Green
Read-Host "Press Enter to close"
