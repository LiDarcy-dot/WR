#Requires -Version 5.1
# Add/update TELEGRAM_PROXY in Desktop\Assistant\.env without touching other keys.
# Usage:
#   .\scripts\set_telegram_proxy.ps1 "socks5://tgproxy:PASS@31.15.16.97:1080"
# Or:
#   $env:TELEGRAM_PROXY = "socks5://..."
#   .\scripts\set_telegram_proxy.ps1
param(
    [Parameter(Mandatory = $false)]
    [string]$Proxy = $env:TELEGRAM_PROXY
)

$ErrorActionPreference = "Stop"
$Target = Join-Path $env:USERPROFILE "Desktop\Assistant"
$EnvFile = Join-Path $Target ".env"

if (-not $Proxy) {
    throw "Передай прокси: .\scripts\set_telegram_proxy.ps1 `"socks5://tgproxy:PASS@IP:1080`""
}
if ($Proxy -notmatch '^(socks5|socks5h|http|https)://') {
    throw "Ожидал URL вида socks5://user:pass@host:port"
}
if (-not (Test-Path $EnvFile)) {
    throw "Не найден $EnvFile — сначала поставь ассистента в Desktop\Assistant"
}

$lines = Get-Content -LiteralPath $EnvFile -ErrorAction Stop
$out = New-Object System.Collections.Generic.List[string]
$found = $false
foreach ($line in $lines) {
    if ($line -match '^\s*TELEGRAM_PROXY\s*=') {
        $out.Add("TELEGRAM_PROXY=$Proxy")
        $found = $true
    } else {
        $out.Add($line)
    }
}
if (-not $found) {
    if ($out.Count -gt 0 -and $out[$out.Count - 1] -ne "") { $out.Add("") }
    $out.Add("TELEGRAM_PROXY=$Proxy")
}

Set-Content -LiteralPath $EnvFile -Value $out -Encoding UTF8
Write-Host "OK: TELEGRAM_PROXY записан в $EnvFile" -ForegroundColor Green
Write-Host "Перезапусти START_BOT.bat"
