#Requires -Version 5.1
# Auto-write TELEGRAM_PROXY into .env from proxy.default (no notepad).
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path -LiteralPath (Join-Path $Root "main.py"))) {
    $Root = Join-Path $env:USERPROFILE "Desktop\Assistant"
}
$EnvFile = Join-Path $Root ".env"
$DefaultFile = Join-Path $Root "proxy.default"

if (-not (Test-Path -LiteralPath $EnvFile)) {
    Write-Host "WARN: no .env at $EnvFile"
    exit 0
}

$Proxy = ""
if (Test-Path -LiteralPath $DefaultFile) {
    $lines = Get-Content -LiteralPath $DefaultFile -Encoding UTF8
    foreach ($line in $lines) {
        $t = $line.Trim()
        if ($t -and -not $t.StartsWith("#")) {
            $Proxy = $t
            break
        }
    }
}
if (-not $Proxy) {
    $Proxy = "socks5h://tgproxy:2G99IVcdJzSr1w@31.15.16.97:1080"
}
$Proxy = $Proxy.Trim().Trim('"').Trim("'")
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
$hostPart = ($Proxy -split "@")[-1]
Write-Host ("OK: TELEGRAM_PROXY -> " + $hostPart)
