#Requires -Version 5.1
# Ежедневный запуск бота (LM Studio Server уже должен быть включён)
$assistant = Join-Path $env:USERPROFILE "Desktop\WR\assistant"
Set-Location $assistant
& ".\.venv\Scripts\python.exe" ".\main.py"
