#Requires -Version 5.1
# Add/update TELEGRAM_PROXY in Assistant\.env
# Usage:
#   .\scripts\set_telegram_proxy.ps1 "socks5://tgproxy:PASS@31.15.16.97:1080"
# Prefer: START_BOT / UPDATE — ensure_telegram_proxy.ps1 does this from proxy.default
param(
    [Parameter(Mandatory = $false)]
    [string]$Proxy = $env:TELEGRAM_PROXY
)

$ErrorActionPreference = "Stop"
$Target = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path -LiteralPath (Join-Path $Target "main.py"))) {
    $Target = Join-Path $env:USERPROFILE "Desktop\Assistant"
}
$EnvFile = Join-Path $Target ".env"

if (-not $Proxy) {
    $DefaultFile = Join-Path $Target "proxy.default"
    if (Test-Path -LiteralPath $DefaultFile) {
        foreach ($line in (Get-Content -LiteralPath $DefaultFile -Encoding UTF8)) {
            $t = $line.Trim()
            if ($t -and -not $t.StartsWith("#")) { $Proxy = $t; break }
        }
    }
}
if (-not $Proxy) {
    throw 'Pass proxy URL, example: .\scripts\set_telegram_proxy.ps1 "socks5://user:pass@host:1080"'
}
$Proxy = $Proxy.Trim().Trim('"').Trim("'")
if ($Proxy -notmatch '^(socks5h?|http|https)://') {
    throw "Bad proxy URL. Expected socks5://user:pass@host:port"
}
if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw "File not found: $EnvFile - install Assistant first"
}

if ($Proxy.StartsWith("socks5://")) {
    $Proxy = "socks5h://" + $Proxy.Substring("socks5://".Length)
}

$raw = [System.IO.File]::ReadAllText($EnvFile)
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

$utf8 = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllLines($EnvFile, $out.ToArray(), $utf8)

Write-Host "OK: TELEGRAM_PROXY saved to .env" -ForegroundColor Green
$hostPart = ($Proxy -split "@")[-1]
Write-Host ("proxy host: " + $hostPart)
Write-Host "Restart START_BOT.bat now"
