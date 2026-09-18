#Requires -Version 5.1
# Add/update TELEGRAM_PROXY in Desktop\Assistant\.env without touching other keys.
# Usage:
#   .\scripts\set_telegram_proxy.ps1 "socks5://tgproxy:PASS@31.15.16.97:1080"
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
$Proxy = $Proxy.Trim().Trim('"').Trim("'")
if ($Proxy -notmatch '^(socks5h?|http|https)://') {
    throw "Ожидал URL вида socks5://user:pass@host:port"
}
if (-not (Test-Path $EnvFile)) {
    throw "Не найден $EnvFile — сначала поставь ассистента в Desktop\Assistant"
}

# Prefer socks5h (DNS through proxy)
if ($Proxy.StartsWith("socks5://")) {
    $Proxy = "socks5h://" + $Proxy.Substring("socks5://".Length)
}

$raw = [System.IO.File]::ReadAllText($EnvFile)
# strip UTF-8 BOM if present
if ($raw.Length -gt 0 -and [int][char]$raw[0] -eq 0xFEFF) {
    $raw = $raw.Substring(1)
}
$lines = $raw -split "`r?`n", -1
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

# UTF-8 without BOM (BOM breaks some env parsers)
$utf8 = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllLines($EnvFile, $out.ToArray(), $utf8)

Write-Host "OK: TELEGRAM_PROXY записан в $EnvFile" -ForegroundColor Green
# show masked
if ($Proxy -match '@') {
    $right = $Proxy.Split('@')[-1]
    Write-Host ("proxy host: " + $right)
}
Write-Host "Проверка: в .env должна быть строка TELEGRAM_PROXY=socks5h://..."
Select-String -Path $EnvFile -Pattern '^TELEGRAM_PROXY=' | ForEach-Object {
    $v = $_.Line
    if ($v -match '://([^:]+):([^@]+)@') {
        Write-Host ($v -replace ':([^@]+)@', ':***@')
    } else { Write-Host $v }
}
Write-Host "Перезапусти START_BOT.bat (закрой старое окно или подожди watchdog)."
