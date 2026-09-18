#Requires -Version 5.1
# Quick check: can this PC reach Telegram via TELEGRAM_PROXY from .env?
$ErrorActionPreference = "Stop"
$Target = Join-Path $env:USERPROFILE "Desktop\Assistant"
$EnvFile = Join-Path $Target ".env"
$py = Join-Path $Target ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "no venv python" }
if (-not (Test-Path $EnvFile)) { throw "no .env" }

& $py -c @"
from pathlib import Path
import re, httpx, asyncio
text = Path(r'$EnvFile').read_text(encoding='utf-8-sig')
m = re.search(r'(?m)^TELEGRAM_PROXY\s*=\s*(.+)$', text)
proxy = (m.group(1).strip().strip('\"').strip(\"'\") if m else '')
print('proxy set:', bool(proxy))
if not proxy:
    raise SystemExit('TELEGRAM_PROXY missing in .env')
if proxy.startswith('socks5://'):
    proxy = 'socks5h://' + proxy[len('socks5://'):]
async def main():
    async with httpx.AsyncClient(proxy=proxy, timeout=25.0) as c:
        r = await c.get('https://api.telegram.org')
        print('api.telegram.org', r.status_code)
asyncio.run(main())
"@
