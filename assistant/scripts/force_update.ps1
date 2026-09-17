#Requires -Version 5.1
# Force-refresh app code into Desktop\Assistant (keeps .env .venv db),
# kill a stuck bot window, and start a fresh START_BOT.bat.
$ErrorActionPreference = "Stop"
$Target = Join-Path $env:USERPROFILE "Desktop\Assistant"
$Branch = "cursor/local-assistant-scaffold-d6ce"
$RepoUrl = "https://github.com/LiDarcy-dot/WR.git"

if (-not (Test-Path (Join-Path $Target "main.py"))) {
    throw "No main.py in $Target"
}

Write-Host "Stopping stuck bot processes (if any)..." -ForegroundColor Yellow
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -match 'python(\.exe)?' -and
        $_.CommandLine -and
        ($_.CommandLine -like "*$Target*" -or $_.CommandLine -like "*main.py*")
    } |
    ForEach-Object {
        try {
            Write-Host ("  kill PID " + $_.ProcessId)
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        } catch {}
    }
Start-Sleep -Seconds 2

$temp = Join-Path $env:TEMP ("WR-force-" + [guid]::NewGuid().ToString("N"))
Write-Host "Cloning..." -ForegroundColor Cyan
git clone --branch $Branch --depth 1 $RepoUrl $temp
$srcApp = Join-Path $temp "assistant\app"
$dstApp = Join-Path $Target "app"

if (-not (Test-Path (Join-Path $srcApp "intent.py"))) {
    throw "Clone missing intent.py - wrong branch?"
}

Write-Host "Replacing app folder..." -ForegroundColor Cyan
if (Test-Path $dstApp) {
    Remove-Item -LiteralPath $dstApp -Recurse -Force
}
Copy-Item -LiteralPath $srcApp -Destination $dstApp -Recurse -Force

Copy-Item (Join-Path $temp "assistant\main.py") (Join-Path $Target "main.py") -Force
Copy-Item (Join-Path $temp "assistant\requirements.txt") (Join-Path $Target "requirements.txt") -Force
$verSrc = Join-Path $temp "assistant\VERSION"
if (Test-Path $verSrc) {
    Copy-Item $verSrc (Join-Path $Target "VERSION") -Force
}
$srcScripts = Join-Path $temp "assistant\scripts"
$dstScripts = Join-Path $Target "scripts"
if (Test-Path $dstScripts) { Remove-Item -LiteralPath $dstScripts -Recurse -Force }
Copy-Item -LiteralPath $srcScripts -Destination $dstScripts -Recurse -Force

$bat = Join-Path $temp "assistant\START_BOT.bat"
if (Test-Path $bat) {
    Copy-Item $bat (Join-Path $Target "START_BOT.bat") -Force
}
$upd = Join-Path $temp "assistant\scripts\UPDATE.cmd"
if (Test-Path $upd) {
    Copy-Item $upd (Join-Path $Target "UPDATE.cmd") -Force
}
$setup = Join-Path $temp "assistant\SETUP_PC.md"
if (Test-Path $setup) {
    Copy-Item $setup (Join-Path $Target "SETUP_PC.md") -Force
}

Remove-Item -LiteralPath $temp -Recurse -Force

$intent = Join-Path $dstApp "intent.py"
$memory = Join-Path $dstApp "memory\formatters.py"
$filesStore = Join-Path $dstApp "files\store.py"
Write-Host ("intent.py exists: " + (Test-Path $intent))
Write-Host ("formatters.py exists: " + (Test-Path $memory))
Write-Host ("files\store.py exists: " + (Test-Path $filesStore))
if (-not (Test-Path $intent)) { throw "intent.py still missing after copy" }
if (-not (Test-Path $memory)) { throw "formatters.py still missing after copy" }
if (-not (Test-Path $filesStore)) { throw "files\store.py still missing after copy" }

Set-Location $Target
$py = Join-Path $Target ".venv\Scripts\python.exe"
& $py -m pip install -q -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
& $py -c "from app.intent import classify_intent; from app.update.apply import request_restart; print(classify_intent('+').kind)"
if ($LASTEXITCODE -ne 0) { throw "import failed" }

$ver = (Get-Content (Join-Path $Target "VERSION") -Raw).Trim()
Write-Host "FORCE UPDATE OK → $ver" -ForegroundColor Green

$startBat = Join-Path $Target "START_BOT.bat"
Write-Host "Starting bot..." -ForegroundColor Cyan
Start-Process -FilePath $startBat -WorkingDirectory $Target
Write-Host "Новое окно START_BOT.bat открыто. Старое можно закрыть."
if ($Host.Name -eq "ConsoleHost") {
    try { Read-Host "Press Enter" } catch { }
}
