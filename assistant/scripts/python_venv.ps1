#Requires -Version 5.1
# Shared: find Python and create .venv (works with 3.14, python.exe, py launcher)

function Find-AssistantVenvPython {
    param([string]$WorkDir)

    Set-Location $WorkDir
    $venvPy = Join-Path $WorkDir ".venv\Scripts\python.exe"
    if (Test-Path ".venv") {
        Remove-Item -Recurse -Force ".venv"
    }

    $attempts = @(
        @{ Label = "py -3.14"; Exe = "py"; Args = @("-3.14", "-m", "venv", ".venv") },
        @{ Label = "py -3.13"; Exe = "py"; Args = @("-3.13", "-m", "venv", ".venv") },
        @{ Label = "py -3.12"; Exe = "py"; Args = @("-3.12", "-m", "venv", ".venv") },
        @{ Label = "py -3.11"; Exe = "py"; Args = @("-3.11", "-m", "venv", ".venv") },
        @{ Label = "py -3"; Exe = "py"; Args = @("-3", "-m", "venv", ".venv") },
        @{ Label = "python"; Exe = "python"; Args = @("-m", "venv", ".venv") },
        @{ Label = "python3"; Exe = "python3"; Args = @("-m", "venv", ".venv") }
    )

    foreach ($a in $attempts) {
        if (-not (Get-Command $a.Exe -ErrorAction SilentlyContinue)) {
            continue
        }
        Write-Host "Trying $($a.Label) ..." -ForegroundColor DarkYellow
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            & $a.Exe @($a.Args) 2>&1 | Out-Null
        } catch {
            # py launcher writes errors to stderr; keep trying
        }
        $ErrorActionPreference = $prev
        if (Test-Path $venvPy) {
            $ver = & $venvPy --version 2>&1
            Write-Host "OK: $ver via $($a.Label)" -ForegroundColor Green
            return $venvPy
        }
    }

    throw @"
Could not create venv.
Install Python from https://www.python.org/downloads/
Check 'Add python.exe to PATH', then reopen PowerShell.
"@
}

function Install-AssistantPackages {
    param([string]$VenvPy, [string]$WorkDir)

    Set-Location $WorkDir
    & $VenvPy -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
    & $VenvPy -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
    & $VenvPy -c "import telegram; print('telegram OK')"
    if ($LASTEXITCODE -ne 0) { throw "telegram module missing after pip install" }
}
