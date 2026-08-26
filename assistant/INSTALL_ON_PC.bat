@echo off
chcp 65001 >nul
echo WR Assistant - one-click install to Desktop\Assistant
echo.

set "TARGET=%USERPROFILE%\Desktop\Assistant"
set "WR=%USERPROFILE%\Desktop\WR"

if not exist "%WR%" (
    echo Cloning WR repo...
    cd /d "%USERPROFILE%\Desktop"
    git clone https://github.com/LiDarcy-dot/WR.git -b cursor/local-assistant-scaffold-d6ce
)

cd /d "%WR%\assistant"
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\install_desktop.ps1" -BotToken "8098256261:AAGe1FoFU-rM8xJMXKaK9VHEl7aBUXE3L0Y" -OwnerId 489485288
